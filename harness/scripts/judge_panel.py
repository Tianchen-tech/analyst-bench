"""Leave-own-provider-out judge panel (ID-50) over the blind packets of both waves. Run on the host.

    python scripts/judge_panel.py run [--waves 1,2] [--judges gpt,claude,grok] [--only R-...] [--limit N]
    python scripts/judge_panel.py status

Every packet is judged once by each available judge whose provider is not the packet author's provider: GPT (Codex),
Claude (Claude Code) and Grok (Grok Build); Gemini is unavailable (ID-52). Each judgment is validated, repaired at most
twice, and stored under private/judge/panel/<pseudonym>/<judge>.json with its raw calls. The author's product is looked
up from the grader-side slot record and is never put in a prompt. One thread per judge (providers run in parallel,
packets one at a time per judge). Combining judgments into review logs is a separate step, after the owner fixes the
rule for two-judge disagreements (ID-50 follow-up).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from judge import backends as B
from judge import judge as J

ROOT = Path(__file__).resolve().parents[1]
WAVE_DIRS = {"1": "wave1", "2": "wave2"}
OUT = ROOT / "private" / "judge" / "panel"
REPAIRS = 2
_print = threading.Lock()


def say(obj) -> None:
    with _print:
        print(json.dumps(obj, ensure_ascii=False), flush=True)


def normalize_keys(log):
    if not isinstance(log, dict):
        return log
    out = dict(log)
    for k in ("atoms", "claims", "critical", "caps", "traps"):
        if isinstance(out.get(k), dict):
            out[k] = {(key.strip() if isinstance(key, str) else key): v for key, v in out[k].items()}
    if isinstance(out.get("claims"), dict):
        out["claims"] = {(k if not isinstance(k, str) or k.startswith("/") or ("/" + k) in out["claims"] else "/" + k): v
                         for k, v in out["claims"].items()}
    return out


def packets(waves: list[str]) -> list[dict]:
    """[{pseudonym, wave, packet, author}] with the author's product from the grader-side slot record."""
    out = []
    for w in waves:
        grading = ROOT / "private" / "grading" / WAVE_DIRS[w]
        by_sha = {}
        for d in grading.glob("P1-*"):
            if (d / "provisional.json").exists():
                by_sha[json.loads((d / "provisional.json").read_text())["record_sha256"]] = d
        for p in sorted((ROOT / "private" / "review" / WAVE_DIRS[w] / "packets").glob("R-*.json")):
            pk = json.loads(p.read_text())
            d = by_sha.get(pk["record_sha256"])
            if d is None:
                raise SystemExit(f"{pk['pseudonym']}: no provisional record for this packet (regrade first)")
            author = json.loads((d / "grader_only" / "slot.json").read_text())["product"]
            out.append({"pseudonym": pk["pseudonym"], "wave": w, "packet": pk, "author": author})
    return out


def judge_one(item: dict, judge: str) -> dict:
    pk, ps = item["packet"], item["pseudonym"]
    d = OUT / ps
    final = d / f"{judge}.json"
    if final.exists():
        return {"pseudonym": ps, "judge": judge, "status": "already judged"}
    task = pk["task_id"]
    task_md = (ROOT / "private" / "tasks" / "export" / task / "task.md").read_text(encoding="utf-8")
    gold = json.loads((ROOT / "private" / "gold" / f"{task}.json").read_text(encoding="utf-8"))
    base = J.build_prompt(pk, task_md, gold)
    prompt, calls, missing = base, [], []
    for i in range(REPAIRS + 1):
        r = B.call(judge, prompt, d / "raw", f"{judge}.{i}")
        calls.append({k: r[k] for k in ("tag", "returncode", "prompt_sha256", "stdout_sha256", "meta")})
        log = normalize_keys(r["parsed"])
        if isinstance(log, dict):
            log = J.keep_automatic(log, pk)
        missing = J.problems(log, pk)
        if not missing:
            doc = {**log, "judge": {"judge": judge, "provider": B.JUDGES[judge], "model": B.MODELS[judge][0], "effort": B.MODELS[judge][1],
                                    "protocol_sha256": J.sha(J.PROTOCOL.read_bytes()), "judge_code_sha256": J.sha((J.HERE / "judge.py").read_bytes()),
                                    "backends_sha256": J.sha((J.HERE / "backends.py").read_bytes()), "prompt_sha256": J.sha(base),
                                    "calls": calls, "judged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                   "target": {"record_sha256": pk["record_sha256"], "pseudonym": ps, "task_id": task}}
            final.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            return {"pseudonym": ps, "task": task, "judge": judge, "status": "judged", "calls": len(calls)}
        auto_wrong = [ref for ref, v in J.needs(pk)["auto"].items() if v == "wrong"
                      and any(m.startswith(f"claim {ref}: ") for m in missing)]
        note = ("" if not auto_wrong else "\n\nThe automatic arithmetic check against the REFERENCE found these claims WRONG: "
                + json.dumps(auto_wrong) + ". Their verdict stays `wrong` (record any disagreement in `disputes`). For each of "
                "them give `codes` (taxonomy) and `severity` (1-3).")
        prompt = base + "\n\n# YOUR PREVIOUS OUTPUT WAS INCOMPLETE OR INVALID\n\nMissing or invalid: " + json.dumps(missing[:60]) + note + \
            "\n\nPrevious output:\n```json\n" + json.dumps(log, ensure_ascii=False)[:60000] + "\n```\n\nReturn the complete, corrected JSON object."
    return {"pseudonym": ps, "judge": judge, "status": f"FAILED: {missing[:5]}; last returncode {calls[-1]['returncode']}"}


def quota_hit(ps: str, judge: str) -> bool:
    """A usage-limit message in the judge's latest raw call: stop that judge instead of burning repairs on more packets."""
    import re
    from runners.controller import AVAILABILITY_PATTERNS
    raws = sorted((OUT / ps / "raw").glob(f"{judge}.*.stderr")) + sorted((OUT / ps / "raw").glob(f"{judge}.*.stdout"))
    text = "\n".join(f.read_text(errors="replace")[-4000:] for f in raws[-2:])
    return any(re.search(p, text, re.I) for p in AVAILABILITY_PATTERNS[:3] + [r"limit reached", r"try again (?:at|in|later)"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("run", "status"))
    ap.add_argument("--waves", default="1,2")
    ap.add_argument("--judges", default=",".join(B.JUDGES))
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    items = packets(a.waves.split(","))
    if a.only:
        items = [x for x in items if x["pseudonym"] in set(a.only.split(","))]
    plan = {j: [x for x in items if B.PROVIDER[x["author"]] != B.JUDGES[j]] for j in a.judges.split(",")}
    if a.command == "status":
        st = {j: {"assigned": len(v), "judged": sum((OUT / x["pseudonym"] / f"{j}.json").exists() for x in v)} for j, v in plan.items()}
        print(json.dumps({"packets": len(items), "by_judge": st}, indent=1))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    locks = []
    for j in plan:                                   # one lock per judge: different judges may run in separate processes
        lk = open(OUT / f".lock-{j}", "a")
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(f"REFUSED: judge {j} is already running in another judge_panel process", file=sys.stderr)
            return 2
        locks.append(lk)
    failures = []

    def worker(j: str) -> None:
        todo = [x for x in plan[j] if not (OUT / x["pseudonym"] / f"{j}.json").exists()]
        for x in todo[: a.limit] if a.limit else todo:
            try:
                res = judge_one(x, j)
            except Exception as exc:                          # one packet's failure never stops the judge's queue
                res = {"pseudonym": x["pseudonym"], "judge": j, "status": f"FAILED: {type(exc).__name__}: {str(exc)[:300]}"}
            if res["status"].startswith("FAILED"):
                failures.append(res)
                if quota_hit(x["pseudonym"], j):
                    say({"judge": j, "status": "STOPPED: the judge's subscription reports a usage/rate limit; rerun after the reset "
                                               "(judged packets are kept and skipped)"})
                    return
            say(res)

    threads = [threading.Thread(target=worker, args=(j,)) for j in plan]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    say({"done": True, "failures": len(failures)})
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
