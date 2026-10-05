"""Blind review packets and finalization: original eligible AI panel plus versioned audit corrections.

Packet: a reviewer PROJECTION (see `packet`): pseudonymous (HMAC of the run id with a private salt), identity terms
masked in submitted content, neutral evidence aliases; the original archive and the redaction map stay apart. It carries the task request, the exact preserved answer.json bytes, memo.md, small evidence files, the
provisional atoms with their review prompts, every claim record (structured metrics with their mapping and any
automatic verdict, `claims[]`, result text, drivers, findings) with explicitly linked warnings, and the critical
predicates and caps that need a decision. Nothing in the packet is altered; any redaction would be recorded.

Review log (one JSON per pseudonym), required for finalization:
  atoms:      {atom_id: {"awarded": number in [0, max], "reason": str}} for every pending atom
  q16_weights {"A": {...}, "B": {...}, "reported": {"A": x, "B": y}} when the common-weight atom relies on stated weights
  claims:     {ref: {"verdict": correct|wrong|immaterial|unverifiable, "warned": bool, "codes": [...], "severity": 1-3}}
              for every claim (automatic verdicts are confirmed, not overridden; a disagreement is recorded as a dispute)
  memo_claims [{"quote": str, "verdict": ..., "warned": bool, "codes": [...], "severity": ...}] wrong or checked memo claims
  memo_reviewed: true
  critical:   {predicate: bool} for every review predicate
  caps:       {name: bool} for every cap
  substantive: bool
  traps:      {opportunity: bool} for every trap opportunity of the task (right issue, population/window and evidence)
  target:     {"record_sha256", "pseudonym", "task_id"} of the provisional record this log decides (lineage)
  adjudications {ref: {"resolution": "automatic_verdict_upheld", "reason", "adjudicator", "rules_version"}} for disputes
Wrong claims need taxonomy codes (E01-E17 or UNCLASSIFIED with a reason) and severity 1-3; warned=true needs a
qualification_ref, and r4 binds a claim-specific assessment to the source judgments. Recorded semantic objections
require a versioned resolution even when normalized verdicts agree. A checkable claim makes the response substantive;
a true critical predicate forces its atom to 0.
Finalization computes the score (with caps), critical failure, success (core: >= 80 and no critical; Q26-Q28: >= 75 and
no invented unavailable answer), E_i and S_i (design 5.4). A terminal failure keeps its content score but cannot succeed.
Anything missing leaves the record pending, never "correct".
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from .score import CORE, UNANSWERABLE

VERDICTS = ("correct", "wrong", "immaterial", "unverifiable")
CODES = tuple(f"E{n:02d}" for n in range(1, 18)) + ("UNCLASSIFIED",)
CRITICAL_ATOMS = {"customer net bookings wrong": "q03_net_usd", "final June D180 value asserted": "q27_no_final_value",
                  "presenting a number as the final June D180 LTV (claims or memo)": "q27_no_final_value",
                  "hallucinating a quote, support ticket or certain motive": "q26_no_asserted_motive"}


class LineageError(ValueError):
    """The record or log is not the current, matching artifact (infrastructure; nothing is relabeled)."""


def check_lineage(record: dict[str, Any], log: dict[str, Any] | None, ident: dict[str, Any], archive_dir: Path | None,
                  salt_bytes: bytes | None) -> None:
    from .score import record_digest
    from .intake import _sha
    if record.get("record_sha256") != record_digest(record):
        raise LineageError("provisional record digest does not match its contents")
    if record.get("gate") != ident:
        raise LineageError(f"provisional record was made under a different gate identity: {record.get('gate')} != {ident}")
    if archive_dir is not None:
        for rel, meta in record["intake"]["archive"].items():
            p = Path(archive_dir) / rel
            if "sha256" in meta and (not p.is_file() or p.is_symlink() or _sha(p) != meta["sha256"]):
                raise LineageError(f"preserved submission file changed or missing: {rel}")
    if log is not None:
        tgt = log.get("target") or {}
        want = {"record_sha256": record["record_sha256"], "task_id": record["run"]["task_id"]}
        if salt_bytes is not None:
            want["pseudonym"] = pseudonym(record["run"]["run_id"], salt_bytes)
        if any(tgt.get(k) != v for k, v in want.items()):
            raise LineageError(f"review log targets {tgt}, not this record {want}")
SMALL_EVIDENCE = 64 * 1024


def pseudonym(run_id: str, salt: bytes) -> str:
    return "R-" + hmac.new(salt, run_id.encode(), hashlib.sha256).hexdigest()[:10]


def salt(root: Path) -> bytes:
    p = Path(root) / "private" / "grading" / "pseudonym_salt.bin"
    if not p.exists():
        import secrets
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(secrets.token_bytes(32))
        p.chmod(0o400)
    return p.read_bytes()


IDENTITY_TERMS = [r"claude\s*code", r"claude", r"anthropic", r"codex", r"openai", r"open\s*ai", r"chat\s*gpt",
                  r"gpt[-\s]?\d+(?:\.\d+)?(?:[-\s]?(?:sol|mini|pro|turbo|o))?", r"\bopus\b", r"\bsonnet\b", r"\bhaiku\b",
                  r"gemini", r"\bgrok\b", r"antigravity", r"\bxai\b", r"\bx\.ai\b", r"spacex\s*ai", r"deepmind"]
# "Google" is deliberately not masked: Google Play is ordinary platform vocabulary in the game data (ID-51).
REDACTED = "[PRODUCT]"


def redact(text: str) -> tuple[str, int]:
    import re
    n = 0
    for pat in IDENTITY_TERMS:
        text, k = re.subn(pat, REDACTED, text, flags=re.IGNORECASE)
        n += k
    return text, n


def _code_hits(rel: str, text: str) -> list[int]:
    """Line numbers where an identity term sits in executable code rather than a comment (blinding limitation)."""
    import re
    marker = "--" if rel.endswith(".sql") else "#" if rel.endswith(".py") else None
    if marker is None:
        return []
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        code = line.split(marker, 1)[0]
        if any(re.search(p, code, flags=re.IGNORECASE) for p in IDENTITY_TERMS):
            out.append(i)
    return out


def packet(record: dict[str, Any], archive_dir: Path, task_md: str, salt_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reviewer projection: (packet, redaction_map). The packet never names the product: identity terms are masked in the
    memo, answer text, evidence contents, error details and claim/atom texts; evidence files get neutral aliases. The
    original archive is untouched; the redaction map (aliases -> paths, per-surface counts) is stored apart from the
    reviewer. An identity term inside executable code is flagged as a blinding limitation, never silently rewritten."""
    import os
    run = record["run"]
    paths = sorted(r for r in record["intake"]["archive"] if r not in ("answer.json", "memo.md"))
    alias = {r: f"evidence_{i + 1:02d}{os.path.splitext(r)[1]}" for i, r in enumerate(paths)}

    def project(text: str | None, surface: str, rel: str | None = None) -> str | None:
        if text is None:
            return None
        for r in sorted(alias, key=len, reverse=True):
            text = text.replace(r, alias[r])
        text, n = redact(text)
        if n:
            redactions.append({"surface": surface, "file": alias.get(rel, rel), "count": n})
        return text

    redactions: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []
    files = {}
    for rel in paths:
        meta = record["intake"]["archive"][rel]
        if "sha256" in meta and meta["bytes"] <= SMALL_EVIDENCE:
            raw = (Path(archive_dir) / rel).read_text(encoding="utf-8", errors="replace")
            hits = _code_hits(rel, raw)
            if hits:
                limitations.append({"file": alias[rel], "lines": hits, "issue": "identity term in executable code; masked for review, "
                                    "analytical meaning may depend on it - check the original via the redaction map"})
            files[alias[rel]] = project(raw, "evidence", rel)
    ans = Path(archive_dir) / "answer.json"
    request = task_md.split("## Request", 1)[1].split("## Context", 1)[0].strip() if "## Request" in task_md else ""
    as_text = lambda obj, surface: json.loads(project(json.dumps(obj), surface))
    pk = {"pseudonym": pseudonym(run["run_id"], salt_bytes), "task_id": run["task_id"], "request": request,
          "record_sha256": record.get("record_sha256"),
          "answer_json_raw": project(ans.read_text(encoding="utf-8", errors="replace"), "answer.json") if ans.exists() else None,
          "answer_parse": record["intake"]["answer_parse"], "answer_errors": as_text(record["intake"]["answer_errors"], "errors"),
          "memo": project(record["intake"]["memo"], "memo.md"), "memo_words": record["intake"]["memo_words"], "evidence_files": files,
          "archive_hashes": {alias.get(k, k): v for k, v in record["intake"]["archive"].items()},
          "atoms": as_text(record["atoms"], "atoms"), "claims": as_text(record["claims"], "claims"),
          "flags": record["flags"], "trap_opportunities": record.get("trap_opportunities", []),
          "replay": as_text({k: (record["replay"] or {}).get(k) for k in ("status", "detail", "elapsed_s")}, "replay"),
          "substantive_hint": record["substantive_hint"], "redactions": redactions, "blinding_limitations": limitations,
          "rules": record["rules"]}
    rmap = {"pseudonym": pk["pseudonym"], "record_sha256": record.get("record_sha256"), "aliases": {v: k for k, v in alias.items()},
            "redactions": redactions, "limitations": limitations, "terms": IDENTITY_TERMS}
    return pk, rmap


def _need(record: dict[str, Any]) -> dict[str, list[str]]:
    return {"atoms": [a["atom"] for a in record["atoms"] if a["state"] == "pending"],
            "claims": [c["ref"] for c in record["claims"]],
            "critical": list(record["flags"].get("critical_review", [])),
            "caps": list((record["flags"].get("caps_review") or {}).keys())}


def dispute_digest(disputes: list[Any]) -> str:
    """Bind an adjudication to the exact original objections, including notes."""
    return hashlib.sha256(json.dumps(disputes, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def delivery_success(content_success: bool, outcome: str | None) -> bool:
    """Design 5.4: terminal failures do not succeed, even with saved good content."""
    return bool(content_success and outcome not in ("timeout", "error", "infrastructure"))


def finalize(record: dict[str, Any], log: dict[str, Any] | None, gold: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {status: final|pending, missing: [...], ...}. Never fills a missing decision with a default."""
    need = _need(record)
    log = log or {}
    missing = []
    atoms = {a["atom"]: dict(a) for a in record["atoms"]}
    for aid in need["atoms"]:
        dec = (log.get("atoms") or {}).get(aid)
        if aid == "q16_common_weight" and log.get("q16_weights") and gold is not None:
            dec = _q16_decision(log["q16_weights"], gold, atoms[aid]["max"])
        if not isinstance(dec, dict) or not isinstance(dec.get("awarded"), (int, float)) or isinstance(dec.get("awarded"), bool) \
                or not 0 <= dec["awarded"] <= atoms[aid]["max"] or not str(dec.get("reason", "")).strip():
            missing.append(f"atom {aid}")
        else:
            atoms[aid].update(awarded=float(dec["awarded"]), state="reviewed", reason=dec["reason"])
    claims, disputes = [], []
    recorded_disputes = list(log.get("recorded_disputes") or log.get("disputes") or [])
    if recorded_disputes:
        adj = log.get("dispute_adjudication") or {}
        if adj.get("resolution") != "versioned_review" or adj.get("source_disputes_sha256") != dispute_digest(recorded_disputes) \
                or not all(str(adj.get(k, "")).strip() for k in ("reason", "adjudicator", "rules_version", "evidence_sha256")) \
                or (record.get("gate") and adj.get("policy_record_sha256") != record["gate"].get("policy_record_sha256")):
            missing.append("recorded disputes: needs a versioned adjudication bound to the original objections and current policy")

    def claim_problems(dec: dict[str, Any], verdict: str, where: str) -> list[str]:
        out = []
        if verdict == "wrong":
            codes = dec.get("codes")
            if not isinstance(codes, list) or not codes or any(c not in CODES for c in codes):
                out.append(f"{where}: a wrong claim needs taxonomy codes (E01-E17, or UNCLASSIFIED with a reason)")
            if "UNCLASSIFIED" in (codes or []) and not str(dec.get("unclassified_reason", "")).strip():
                out.append(f"{where}: UNCLASSIFIED needs a reason")
            if dec.get("severity") not in (1, 2, 3):
                out.append(f"{where}: a wrong claim needs severity 1-3")
        if dec.get("warned") is True and not str(dec.get("qualification_ref", "")).strip():
            out.append(f"{where}: warned=true needs the specific qualification (warning index or memo quote)")
        return out

    def qualification_problems(dec: dict[str, Any], verdict: str, key: str, text: Any) -> list[str]:
        if verdict != "wrong" or dec.get("warned") is not True or record.get("gate", {}).get("rubric_version") != "r4":
            return []
        assessed = (log.get("qualification_reviews") or {}).get(key) or {}
        digest = hashlib.sha256(json.dumps(text, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if assessed.get("qualifies") is not True or assessed.get("claim_sha256") != digest \
                or assessed.get("qualification_ref") != dec.get("qualification_ref") \
                or not all(str(assessed.get(k, "")).strip() for k in ("reason", "reviewer", "rules_version")) \
                or assessed.get("rules_version") != "r4" or not assessed.get("source_review_hashes"):
            return [f"{key}: warning needs a claim-specific qualification assessment bound to its text and source review"]
        return []

    adjudications = log.get("adjudications") or {}
    for c in record["claims"]:
        dec = (log.get("claims") or {}).get(c["ref"])
        if not isinstance(dec, dict) or dec.get("verdict") not in VERDICTS or not isinstance(dec.get("warned"), bool):
            missing.append(f"claim {c['ref']}")
            continue
        verdict = c["auto_verdict"] or dec["verdict"]
        semantic = dec.get("semantic_verdict", dec["verdict"])
        if c.get("auto_verdict") and semantic in VERDICTS and semantic != c["auto_verdict"]:
            disputes.append(c["ref"])
            adj = adjudications.get(c["ref"]) or {}
            if adj.get("resolution") != "automatic_verdict_upheld" or not all(str(adj.get(k, "")).strip() for k in ("reason", "adjudicator", "rules_version")):
                missing.append(f"dispute {c['ref']}: needs a versioned adjudication (automatic arithmetic cannot be overridden; "
                               "a gold or matcher defect requires a versioned policy change)")
        missing += claim_problems(dec, verdict, f"claim {c['ref']}")
        missing += qualification_problems(dec, verdict, c["ref"], c["text"])
        claims.append({"ref": c["ref"], "verdict": verdict, "warned": dec["warned"], "codes": dec.get("codes", []),
                       "severity": dec.get("severity"), "qualification_ref": dec.get("qualification_ref")})
    for m in log.get("memo_claims", []) or []:
        if m.get("verdict") not in VERDICTS or not isinstance(m.get("warned"), bool) or not str(m.get("quote", "")).strip():
            missing.append("memo claim entry incomplete")
        else:
            missing += claim_problems(m, m["verdict"], f"memo claim {m['quote'][:40]!r}")
            missing += qualification_problems(m, m["verdict"], "memo:" + hashlib.sha256(m["quote"].encode()).hexdigest(), m["quote"])
            claims.append({"ref": "memo", "quote": m["quote"], "verdict": m["verdict"], "warned": m["warned"],
                           "codes": m.get("codes", []), "severity": m.get("severity"), "qualification_ref": m.get("qualification_ref")})
    if log.get("memo_reviewed") is not True:
        missing.append("memo not reviewed")
    crit = dict(record["flags"].get("critical_auto") or {})
    for p in need["critical"]:
        v = (log.get("critical") or {}).get(p)
        if not isinstance(v, bool):
            missing.append(f"critical predicate: {p}")
        else:
            crit[p] = v
    caps = {}
    for name, value in (record["flags"].get("caps_review") or {}).items():
        v = (log.get("caps") or {}).get(name)
        if not isinstance(v, bool):
            missing.append(f"cap: {name}")
        elif v:
            caps[name] = value
    if not isinstance(log.get("substantive"), bool):
        missing.append("substantive response decision")
    traps = {}
    for opp in record.get("trap_opportunities", []):
        v = (log.get("traps") or {}).get(opp)
        if not isinstance(v, bool):
            missing.append(f"trap detection: {opp}")
        else:
            traps[opp] = v
    checkable = [c for c in claims if c["verdict"] in ("correct", "wrong")]
    if checkable and log.get("substantive") is False:
        missing.append("inconsistent: checkable claims (incl. any wrong claim) exist, so the response is substantive")
    for pred, val in crit.items():
        aid = CRITICAL_ATOMS.get(pred)
        if val and aid in atoms and atoms[aid]["awarded"] not in (0, 0.0):
            missing.append(f"inconsistent: critical '{pred}' is true but atom {aid} was awarded points")
    if missing:
        return {"status": "pending", "missing": missing, "disputes": disputes + recorded_disputes,
                "automatic_disputes": disputes, "recorded_disputes": recorded_disputes}
    task = record["run"]["task_id"]
    raw = sum(a["awarded"] for a in atoms.values())
    score = min([raw, *caps.values()]) if caps else raw
    critical = any(crit.values())
    threshold = 80 if task in CORE else 75 if task in UNANSWERABLE else None
    wrong = [c for c in claims if c["verdict"] == "wrong"]
    content_success = threshold is not None and score >= threshold and not critical
    return {"status": "final", "score": round(score, 6), "raw_score": round(raw, 6), "caps_applied": caps, "critical": crit,
            "critical_failure": critical, "content_success": content_success,
            "success": delivery_success(content_success, record["run"].get("outcome")),
            "substantive": log["substantive"], "E": int(bool(wrong)), "S": int(any(not c["warned"] for c in wrong)),
            "wrong_claims": wrong, "atoms": list(atoms.values()), "disputes": disputes + recorded_disputes,
            "automatic_disputes": disputes, "adjudications": adjudications, "traps": traps,
            "recorded_disputes": recorded_disputes, "dispute_adjudication": log.get("dispute_adjudication"),
            "record_sha256": record.get("record_sha256"), "target": log.get("target"),
            "reviewer": log.get("reviewer"), "reviewed_at": log.get("reviewed_at")}


def _q16_decision(w: dict[str, Any], gold: dict[str, Any], mx: float) -> dict[str, Any] | None:
    from evaluation import scoring
    from .atoms import within
    try:
        r = scoring.q16_common_weight(gold, w["A"], w.get("B"))
    except scoring.NotCommonWeights as exc:
        return {"awarded": 0.0, "reason": f"not a common-weight comparison: {exc}"}
    rep = w.get("reported") or {}
    ok = within(rep.get("A"), r["A"], "ratio") and within(rep.get("B"), r["B"], "ratio")
    return {"awarded": float(mx) if ok else 0.0,
            "reason": f"recomputed with the stated weights: A {r['A']:.4f}, B {r['B']:.4f}; reported {rep}; "
                      f"{'match' if ok else 'do not match'} within 1e-4"}


def save(path: Path, obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=str) + "\n", encoding="utf-8")
