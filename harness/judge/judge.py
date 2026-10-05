"""Judge protocol v1 (ID-47): build the blind prompt, call Grok headless, validate, and combine independent judgments.

  prompt      protocol.md + the public task.md + the task's private reference (gold without provenance/bindings) + the
              blind packet (answer.json, memo, evidence, replay status) + the exact decision keys. No product identity,
              run id, repetition or slot order is ever included (the packet is already the reviewer projection).
  call        `grok --prompt-file` in a fresh empty working directory, web search, subagents and tools off, structured
              JSON output; raw stdout/stderr kept with hashes.
  validate    every required key present with a valid value; automatic claim verdicts are kept (a judge disagreement is
              recorded as a dispute note, never as an override); up to two repair calls listing what was missing.
  consensus   two independent judgments; any decision on which they differ triggers a third, and the majority (median for
              atom points) decides. Items with no majority are listed for the owner. Memo claims count when a majority
              of runs report the same quote (fuzzy match).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "protocol.md"
PROTOCOL_VERSION = "judge-v1"
VERDICTS = ("correct", "wrong", "immaterial", "unverifiable")
CODES = tuple(f"E{n:02d}" for n in range(1, 18)) + ("UNCLASSIFIED",)
GOLD_DROP = ("provenance", "bindings", "agreement")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "atoms": {"type": "object", "additionalProperties": {"type": "object", "properties": {
            "awarded": {"type": "number"}, "reason": {"type": "string"}}, "required": ["awarded", "reason"]}},
        "claims": {"type": "object", "additionalProperties": {"type": "object", "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)}, "warned": {"type": "boolean"},
            "qualification_ref": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string", "enum": list(CODES)}},
            "severity": {"type": "integer", "enum": [1, 2, 3]}, "unclassified_reason": {"type": "string"}},
            "required": ["verdict", "warned"]}},
        "memo_claims": {"type": "array", "items": {"type": "object", "properties": {
            "quote": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)}, "warned": {"type": "boolean"},
            "qualification_ref": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string", "enum": list(CODES)}},
            "severity": {"type": "integer", "enum": [1, 2, 3]}, "unclassified_reason": {"type": "string"}},
            "required": ["quote", "verdict", "warned"]}},
        "memo_reviewed": {"type": "boolean"},
        "critical": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "caps": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "substantive": {"type": "boolean"},
        "traps": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "disputes": {"type": "array", "items": {"type": "string"}},
        "q16_weights": {"type": "object"},
    },
    "required": ["atoms", "claims", "memo_claims", "memo_reviewed", "critical", "caps", "substantive", "traps", "disputes"],
}


def sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def needs(pk: dict[str, Any]) -> dict[str, Any]:
    f = pk.get("flags") or {}
    return {"atoms": {a["atom"]: a["max"] for a in pk["atoms"] if a["state"] == "pending"},
            "claims": [c["ref"] for c in pk["claims"]],
            "auto": {c["ref"]: c["auto_verdict"] for c in pk["claims"] if c.get("auto_verdict")},
            "critical": list(f.get("critical_review") or []), "caps": list((f.get("caps_review") or {}).keys()),
            "traps": list(pk.get("trap_opportunities") or [])}


def build_prompt(pk: dict[str, Any], task_md: str, gold: dict[str, Any], protocol: str | None = None) -> str:
    n = needs(pk)
    ref = {k: v for k, v in gold.items() if k not in GOLD_DROP}
    sub = {k: pk.get(k) for k in ("answer_json_raw", "answer_parse", "answer_errors", "memo", "memo_words", "evidence_files",
                                  "replay", "blinding_limitations")}
    context = {"atoms": [{k: a.get(k) for k in ("atom", "max", "awarded", "state", "reason", "inputs")} for a in pk["atoms"]],
               "claims": [{k: c.get(k) for k in ("ref", "kind", "text", "mapping", "gold", "auto_verdict", "linked_warnings")}
                          for c in pk["claims"]],
               "critical_automatic": (pk.get("flags") or {}).get("critical_auto"),
               "caps_review": (pk.get("flags") or {}).get("caps_review")}
    decisions = {"atoms (pending; key -> max points)": n["atoms"], "claims (every key)": n["claims"],
                 "critical (every predicate)": n["critical"], "caps (every cap)": n["caps"], "traps (every opportunity)": n["traps"],
                 "q16_weights": "optional, Q16 only" if pk["task_id"] == "Q16" else "omit"}
    return "\n\n".join([
        (protocol if protocol is not None else PROTOCOL.read_text(encoding="utf-8")).strip(),
        f"# TASK ({pk['task_id']})\n\n{task_md.strip()}",
        "# REFERENCE (private; the analyst never saw it)\n\n```json\n" + json.dumps(ref, indent=1, ensure_ascii=False) + "\n```",
        "# SUBMISSION\n\n```json\n" + json.dumps(sub, indent=1, ensure_ascii=False) + "\n```",
        "# SCORER CONTEXT (automatic results and claim records)\n\n```json\n" + json.dumps(context, indent=1, ensure_ascii=False) + "\n```",
        "# DECISIONS (return every key)\n\n```json\n" + json.dumps(decisions, indent=1, ensure_ascii=False) + "\n```",
    ]) + "\n"


def extract_json(text: str) -> dict[str, Any] | None:
    """The judge object from Grok's stdout: a bare object, or wrapped in a result/content field, or in a code fence."""
    cands: list[Any] = []
    try:
        cands.append(json.loads(text))
    except ValueError:
        pass
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            cands.append(json.loads(m[1]))
        except ValueError:
            pass
    i = text.find("{")
    if i >= 0 and not cands:
        try:
            cands.append(json.JSONDecoder().raw_decode(text[i:])[0])
        except ValueError:
            pass
    seen: list[Any] = []
    while cands:
        c = cands.pop(0)
        if isinstance(c, dict):
            if "atoms" in c and "claims" in c:
                return c
            for k in ("structuredOutput", "structured_output", "result", "output", "content", "message", "text", "response"):
                v = c.get(k)
                if isinstance(v, (dict, list)):
                    cands.append(v)
                elif isinstance(v, str):
                    try:
                        cands.append(json.loads(v))
                    except ValueError:
                        j = v.find("{")
                        if j >= 0:
                            try:
                                cands.append(json.JSONDecoder().raw_decode(v[j:])[0])
                            except ValueError:
                                pass
        elif isinstance(c, list):
            cands.extend(c)
        seen.append(c)
    return None


def problems(log: dict[str, Any] | None, pk: dict[str, Any]) -> list[str]:
    """What a judgment still lacks (mirrors evaluation.grader.review.finalize's requirements)."""
    if not isinstance(log, dict):
        return ["no JSON object"]
    n, out = needs(pk), []
    for aid, mx in n["atoms"].items():
        d = (log.get("atoms") or {}).get(aid)
        if pk["task_id"] == "Q16" and aid == "q16_common_weight" and isinstance(log.get("q16_weights"), dict) and log["q16_weights"]:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("awarded"), (int, float)) or isinstance(d.get("awarded"), bool) \
                or not 0 <= d["awarded"] <= mx + 1e-9 or not str(d.get("reason", "")).strip():
            out.append(f"atom {aid} (0..{mx})")
    for ref in n["claims"]:
        d = (log.get("claims") or {}).get(ref)
        if not isinstance(d, dict) or d.get("verdict") not in VERDICTS or not isinstance(d.get("warned"), bool):
            out.append(f"claim {ref}")
            continue
        out += _claim_problems(d, f"claim {ref}")
    for m in log.get("memo_claims") or []:
        if not isinstance(m, dict) or m.get("verdict") not in VERDICTS or not isinstance(m.get("warned"), bool) or not str(m.get("quote", "")).strip():
            out.append("memo claim entry incomplete")
        else:
            out += _claim_problems(m, f"memo claim {str(m['quote'])[:40]!r}")
    if log.get("memo_reviewed") is not True:
        out.append("memo_reviewed")
    for k, names in (("critical", n["critical"]), ("caps", n["caps"]), ("traps", n["traps"])):
        for name in names:
            if not isinstance((log.get(k) or {}).get(name), bool):
                out.append(f"{k}: {name}")
    if not isinstance(log.get("substantive"), bool):
        out.append("substantive")
    return out


def _claim_problems(d: dict[str, Any], where: str) -> list[str]:
    out = []
    if d.get("verdict") == "wrong":
        codes = d.get("codes")
        if not isinstance(codes, list) or not codes or any(c not in CODES for c in codes):
            out.append(f"{where}: codes for a wrong claim")
        if "UNCLASSIFIED" in (codes or []) and not str(d.get("unclassified_reason", "")).strip():
            out.append(f"{where}: unclassified_reason")
        if d.get("severity") not in (1, 2, 3):
            out.append(f"{where}: severity for a wrong claim")
    if d.get("warned") is True and not str(d.get("qualification_ref", "")).strip():
        out.append(f"{where}: qualification_ref for warned=true")
    return out


def keep_automatic(log: dict[str, Any], pk: dict[str, Any]) -> dict[str, Any]:
    """Automatic verdicts are arithmetic and stay; a judge disagreement becomes a recorded dispute note."""
    log = json.loads(json.dumps(log))
    notes = list(log.get("disputes") or [])
    for ref, auto in needs(pk)["auto"].items():
        d = (log.get("claims") or {}).get(ref)
        if isinstance(d, dict) and d.get("verdict") != auto:
            notes.append(f"judge verdict {d.get('verdict')!r} differs from the automatic {auto!r} for {ref}; automatic kept")
            d["verdict"] = auto
            if auto != "wrong":
                d.pop("codes", None), d.pop("severity", None)
    log["disputes"] = notes
    return log


# ------------------------------------------------------------------------------------------------------- consensus --

def _majority(values: list[Any]) -> tuple[Any, bool]:
    keyed = [json.dumps(v, sort_keys=True) for v in values]
    best = max(set(keyed), key=keyed.count)
    return json.loads(best), keyed.count(best) * 2 > len(values)


def _same_quote(a: str, b: str) -> bool:
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def differences(logs: list[dict[str, Any]], pk: dict[str, Any]) -> list[str]:
    """Decision items on which the judgments differ (what a third judgment must settle)."""
    n, out = needs(pk), []
    for aid in n["atoms"]:
        if len({round(float((l["atoms"].get(aid) or {}).get("awarded", -1)), 6) for l in logs}) > 1:
            out.append(f"atom {aid}")
    for ref in n["claims"]:
        if len({(l["claims"][ref]["verdict"], l["claims"][ref]["warned"]) for l in logs}) > 1:
            out.append(f"claim {ref}")
    for k in ("critical", "caps", "traps"):
        for name in n[k]:
            if len({l[k][name] for l in logs}) > 1:
                out.append(f"{k} {name}")
    if len({l["substantive"] for l in logs}) > 1:
        out.append("substantive")
    if len({json.dumps(l.get("q16_weights") or None, sort_keys=True) for l in logs}) > 1:
        out.append("q16_weights")
    base = logs[0].get("memo_claims") or []
    for other in logs[1:]:
        om = other.get("memo_claims") or []
        if len(base) != len(om) or any(not any(_same_quote(a["quote"], b["quote"]) and a["verdict"] == b["verdict"] for b in om) for a in base):
            out.append("memo claims")
            break
    return out


def consensus(logs: list[dict[str, Any]], pk: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Combine 2 (agreeing) or 3 judgments. Returns (log, unresolved items for the owner)."""
    n, unresolved = needs(pk), []
    out: dict[str, Any] = {"atoms": {}, "claims": {}, "memo_claims": [], "memo_reviewed": True, "critical": {}, "caps": {},
                           "traps": {}, "disputes": sorted({d for l in logs for d in (l.get("disputes") or [])})}
    for aid in n["atoms"]:
        vals = [float(l["atoms"][aid]["awarded"]) for l in logs if aid in (l.get("atoms") or {})]
        if not vals:                                            # q16 decided through stated weights in every run
            continue
        med = statistics.median(vals)
        src = min(logs, key=lambda l: abs(float((l["atoms"].get(aid) or {"awarded": 1e9})["awarded"]) - med))
        out["atoms"][aid] = {"awarded": med, "reason": src["atoms"][aid]["reason"] + (f" [judge median of {vals}]" if len(set(vals)) > 1 else "")}
    for ref in n["claims"]:
        ds = [l["claims"][ref] for l in logs]
        verdict, ok = _majority([d["verdict"] for d in ds])
        warned, okw = _majority([d["warned"] for d in ds])
        if not ok:
            unresolved.append(f"claim {ref}: verdicts {[d['verdict'] for d in ds]}")
        pick = next((d for d in ds if d["verdict"] == verdict and d["warned"] == warned), next(d for d in ds if d["verdict"] == verdict))
        c = {"verdict": verdict, "warned": warned}
        if warned:
            c["qualification_ref"] = next(d.get("qualification_ref") for d in ds if d["warned"] and d.get("qualification_ref"))
        if verdict == "wrong":
            c["codes"], c["severity"] = pick.get("codes"), pick.get("severity")
            if pick.get("unclassified_reason"):
                c["unclassified_reason"] = pick["unclassified_reason"]
        out["claims"][ref] = c
    for k in ("critical", "caps", "traps"):
        for name in n[k]:
            v, ok = _majority([l[k][name] for l in logs])
            out[k][name] = v
            if not ok:
                unresolved.append(f"{k} {name}")
    out["substantive"], ok = _majority([l["substantive"] for l in logs])
    if not ok:
        unresolved.append("substantive")
    qw, ok = _majority([l.get("q16_weights") or None for l in logs])
    if qw:
        out["q16_weights"] = qw
    if not ok:
        unresolved.append("q16_weights")
    need = len(logs) // 2 + 1
    for m in logs[0].get("memo_claims") or [] if len(logs) == 2 else [m for l in logs for m in (l.get("memo_claims") or [])]:
        support = sum(1 for l in logs if any(_same_quote(m["quote"], o["quote"]) and m["verdict"] == o["verdict"] for o in (l.get("memo_claims") or [])))
        if support >= need and not any(_same_quote(m["quote"], o["quote"]) for o in out["memo_claims"]):
            out["memo_claims"].append(m)
    return out, unresolved


# ------------------------------------------------------------------------------------------------------------- call --

def grok_argv(binary: str, prompt_file: Path, workdir: Path, model: str | None, effort: str | None) -> list[str]:
    argv = [binary, "--prompt-file", str(prompt_file), "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
            "--disable-web-search", "--no-subagents", "--cwd", str(workdir), "--max-turns", "4"]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    return argv


def call(binary: str, prompt: str, out_dir: Path, tag: str, model: str | None, effort: str | None, timeout: int = 1200) -> dict[str, Any]:
    """One fresh headless Grok call in an empty working directory. Raw outputs are kept beside the prompt."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{tag}.prompt.md").write_text(prompt, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="judge-") as wd:
        pf = Path(wd) / "prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        argv = grok_argv(binary, pf, Path(wd), model, effort)
        try:
            r = subprocess.run(argv, cwd=wd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            rc, so, se = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as exc:
            rc, so, se = "timeout", exc.stdout or "", exc.stderr or ""
            so, se = (so.decode() if isinstance(so, bytes) else so), (se.decode() if isinstance(se, bytes) else se)
    (out_dir / f"{tag}.stdout").write_text(so, encoding="utf-8")
    (out_dir / f"{tag}.stderr").write_text(se, encoding="utf-8")
    meta: dict[str, Any] = {}
    try:
        top = json.loads(so)
        meta = {"models": sorted((top.get("modelUsage") or {}).keys()), "num_turns": top.get("num_turns"),
                "stop_reason": top.get("stopReason"), "usage": top.get("usage"),
                "reported_cost_usd": top.get("total_cost_usd"),
                "reported_cost_label": "CLI-reported figure; under a grok.com subscription login this is not a separate charge"}
    except (ValueError, AttributeError):
        pass
    return {"tag": tag, "returncode": rc, "prompt_sha256": sha(prompt), "stdout_sha256": sha(so), "parsed": extract_json(so), "meta": meta,
            "argv_redacted": [a if not a.startswith("{") else "<schema>" for a in argv]}
