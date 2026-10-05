"""Judge-panel agreement and combination (ID-50). Grader side: it knows each packet's author to pick the eligible judges.

    python scripts/panel_combine.py stats                    # how often the eligible judges disagree, and on what
    python scripts/panel_combine.py combine                  # lenient and strict review logs (owner rule, ID-55)

Material items are those that can change a score or a reported metric: pending-atom points, critical predicates, caps,
traps, the substantive decision, whether a claim is wrong (E) and, for wrong claims, whether it was warned (S), and the
set of wrong memo claims. Verdict changes among correct / immaterial / unverifiable are counted separately as minor.
Stats are reported by the author's product, so the owner sees whether disagreement is concentrated anywhere.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from judge import backends as B
from judge import judge as J

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "private" / "judge" / "panel"
sys.path.insert(0, str(ROOT / "scripts"))
from judge_panel import packets  # noqa: E402


def eligible(author: str) -> list[str]:
    return [j for j, prov in B.JUDGES.items() if prov != B.PROVIDER[author]]


def load(item: dict) -> dict[str, dict]:
    return {j: json.loads((PANEL / item["pseudonym"] / f"{j}.json").read_text()) for j in eligible(item["author"])
            if (PANEL / item["pseudonym"] / f"{j}.json").exists()}


def material_diffs(logs: dict[str, dict], pk: dict) -> tuple[list[str], list[str]]:
    n, mat, minor = J.needs(pk), [], []
    L = list(logs.values())
    for aid in n["atoms"]:
        vals = {round(float((l.get("atoms") or {}).get(aid, {}).get("awarded", -1)), 6) for l in L}
        if len(vals) > 1:
            mat.append(f"atom {aid} {sorted(vals)}")
    for ref in n["claims"]:
        vs = [l["claims"][ref]["verdict"] for l in L]
        wrong = {v == "wrong" for v in vs}
        if len(wrong) > 1:
            mat.append(f"claim {ref} wrong? {vs}")
        elif vs[0] == "wrong" and len({l["claims"][ref]["warned"] for l in L}) > 1:
            mat.append(f"claim {ref} warned?")
        elif len(set(vs)) > 1:
            minor.append(f"claim {ref} {vs}")
    for k in ("critical", "caps", "traps"):
        for name in n[k]:
            if len({l[k][name] for l in L}) > 1:
                mat.append(f"{k} {name}")
    if len({l["substantive"] for l in L}) > 1:
        mat.append("substantive")
    counts = [len([m for m in (l.get("memo_claims") or []) if m.get("verdict") == "wrong"]) for l in L]
    if len({c > 0 for c in counts}) > 1:
        mat.append(f"wrong memo claims {counts}")
    return mat, minor


LOGS = ROOT / "private" / "review" / "panel"


def _pick_wrong(ds: list[dict], strict: bool) -> dict:
    wrong = [d for d in ds if d["verdict"] == "wrong"]
    if strict and wrong:
        d = wrong[0]
        warned = all(x["warned"] for x in wrong)                  # strict: unwarned if any wrong-saying judge says so
        out = {"verdict": "wrong", "warned": warned, "codes": d.get("codes"), "severity": max(x.get("severity") or 1 for x in wrong)}
        if warned:
            out["qualification_ref"] = next(x.get("qualification_ref") for x in wrong if x.get("qualification_ref"))
        if d.get("unclassified_reason"):
            out["unclassified_reason"] = d["unclassified_reason"]
        return out
    if not strict and len(wrong) < len(ds):
        d = next(x for x in ds if x["verdict"] != "wrong")
        return {"verdict": d["verdict"], "warned": d["warned"], **({"qualification_ref": d["qualification_ref"]} if d["warned"] else {})}
    # every judge says wrong (lenient) or none does (strict): same verdict class
    if wrong:
        warned_by = [x for x in wrong if x["warned"]]
        w = bool(warned_by) if not strict else all(x["warned"] for x in wrong)
        d = wrong[0]
        out = {"verdict": "wrong", "warned": w, "codes": d.get("codes"), "severity": min(x.get("severity") or 3 for x in wrong)}
        if d.get("unclassified_reason"):
            out["unclassified_reason"] = d["unclassified_reason"]
        if w:
            out["qualification_ref"] = (warned_by or wrong)[0].get("qualification_ref")
        return out
    d = ds[0]
    return {"verdict": d["verdict"], "warned": d["warned"], **({"qualification_ref": d["qualification_ref"]} if d["warned"] else {})}


def combine_two(logs: list[dict], pk: dict, strict: bool) -> dict:
    """ID-55: lenient = benefit of the doubt from either judge; strict = any judge's objection counts."""
    n = J.needs(pk)
    out = {"atoms": {}, "claims": {}, "memo_claims": [], "memo_reviewed": True, "critical": {}, "caps": {}, "traps": {},
           "disputes": sorted({d for l in logs for d in (l.get("disputes") or [])})}
    for aid in n["atoms"]:
        cand = [l["atoms"][aid] for l in logs if aid in (l.get("atoms") or {})]
        if cand:
            pick = (min if strict else max)(cand, key=lambda a: float(a["awarded"]))
            out["atoms"][aid] = {"awarded": float(pick["awarded"]), "reason": pick["reason"]}
    if any(l.get("q16_weights") for l in logs) and "q16_common_weight" in n["atoms"] and "q16_common_weight" not in out["atoms"]:
        out["q16_weights"] = next(l["q16_weights"] for l in logs if l.get("q16_weights"))
    for ref in n["claims"]:
        out["claims"][ref] = _pick_wrong([l["claims"][ref] for l in logs], strict)
    for k in ("critical", "caps"):
        for name in n[k]:
            vals = [l[k][name] for l in logs]
            out[k][name] = any(vals) if strict else all(vals)
    for t in n["traps"]:
        vals = [l["traps"][t] for l in logs]
        out["traps"][t] = all(vals) if strict else any(vals)
    out["substantive"] = any(l["substantive"] for l in logs)
    memos = [[m for m in (l.get("memo_claims") or []) if m.get("verdict") == "wrong"] for l in logs]
    if strict:
        for ms in memos:
            for m in ms:
                if not any(J._same_quote(m["quote"], o["quote"]) for o in out["memo_claims"]):
                    out["memo_claims"].append(m)
    else:
        for m in memos[0]:
            if all(any(J._same_quote(m["quote"], o["quote"]) for o in other) for other in memos[1:]):
                out["memo_claims"].append(m)
    return out


def combine() -> dict:
    out = {"lenient": 0, "strict": 0}
    for it in packets(["1", "2"]):
        logs = load(it)
        need = eligible(it["author"])
        if len(logs) < len(need):
            raise SystemExit(f"{it['pseudonym']}: missing judgments {sorted(set(need) - set(logs))}")
        pk = it["packet"]
        ordered = [dict(logs[j], disputes=[d if isinstance(d, str) else json.dumps(d, ensure_ascii=False)
                                           for d in (logs[j].get("disputes") or [])]) for j in need]
        for variant in ("lenient", "strict"):
            if len(ordered) >= 3:                                   # three judges: majority (median points) in both versions
                log, unresolved = J.consensus(ordered, pk)
                for u in unresolved:                                # a three-way split: the variant's two-judge rule
                    if not u.startswith("claim "):
                        raise SystemExit(f"{it['pseudonym']}: no majority on {u}")
                    ref = u.split(" ", 2)[1].rstrip(":")
                    log["claims"][ref] = _pick_wrong([l["claims"][ref] for l in ordered], strict=(variant == "strict"))
                    log.setdefault("panel_notes", []).append(f"{ref}: three-way split resolved by the {variant} rule")
            else:
                log = combine_two(ordered, pk, strict=(variant == "strict"))
            log["target"] = {"record_sha256": pk["record_sha256"], "pseudonym": it["pseudonym"], "task_id": pk["task_id"]}
            log["reviewer"] = (f"LLM judge panel (ID-50), leave-own-provider-out: {', '.join(need)}; "
                               + ("majority of three" if len(need) >= 3 else f"{variant} combination of two (ID-55)"))
            log["panel"] = {"judges": need, "variant": variant,
                            "judgment_sha256": {j: J.sha((PANEL / it['pseudonym'] / f'{j}.json').read_bytes()) for j in need}}
            d = LOGS / variant
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{it['pseudonym']}.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            out[variant] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("stats", "combine"))
    a = ap.parse_args()
    if a.command == "combine":
        print(json.dumps(combine(), indent=1))
        return 0
    items = packets(["1", "2"])
    by_prod: dict[str, Counter] = defaultdict(Counter)
    kinds: Counter = Counter()
    pending = []
    for it in items:
        logs = load(it)
        need = eligible(it["author"])
        if len(logs) < len(need):
            pending.append((it["pseudonym"], sorted(set(need) - set(logs))))
            continue
        pairs = [(a_, b_) for i, a_ in enumerate(need) for b_ in need[i + 1:]]
        mat, minor = material_diffs(logs, it["packet"])
        c = by_prod[it["author"]]
        c["packets"] += 1
        c["packets_with_material_disagreement"] += bool(mat)
        c["material_items"] += len(mat)
        c["minor_items"] += len(minor)
        c["judges_per_packet"] = len(need)
        for m in mat:
            kinds[m.split(" ")[0]] += 1
    print(json.dumps({"pending_judgments": len(pending), "by_author_product": by_prod, "material_by_kind": kinds}, indent=1, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
