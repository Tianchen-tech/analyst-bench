"""Pilot-1 contestant controller (design 6.1-6.5; host-sandbox boundary, ID-44, owner-confirmed 2026-10-03).

One call to `run_slot` is one fresh session:
  stage     a new run root with work/ (exactly task.md + a read-only clone of game.duckdb, hashes verified), home/
            (HOME and the per-run product profile copied from the clean authenticated baseline) and tmp/; a canary
            file outside work/ that a sandboxed probe must fail to read BEFORE the run starts;
  sandbox   macOS sandbox-exec: file contents readable only from system locations, the product install, the common
            analysis environment (.tools/replay-env + base Python) and the run root's work/home/tmp; writes only there;
            network only to the controller's allowlist proxy on 127.0.0.1 (all other egress denied and logged);
  run       the adapter's argv (subprocess argument array; the opening prompt is never shell-interpolated); clean
            environment with no API keys; stdout (product JSON events) and stderr go to files outside work/;
  deadline  1,200 s wall clock from submission; every descendant ever observed is tracked (ps polling) and the whole
            tree is killed at the cap; outputs are snapshotted only after the kill, so later writes are impossible;
  record    design-6.1 run fields: identities (version command, executable hash, observed model from the transcript),
            settings snapshot hash, the runner binding (hashes of the controller, proxy, adapter and products.json in force), times, stop reason, usage when exposed, egress allowed/denied, output hashes, the
            unchanged database hash, the canary result. Nothing is resumed, repaired or replaced here.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .proxy import AllowlistProxy, summarize

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = PROJECT_ROOT / "private" / "runners" / "products.json"
REPLAY_ENV = PROJECT_ROOT / ".tools" / "replay-env"
SYSTEM_READS = ["/usr/lib", "/usr/share", "/usr/bin", "/bin", "/System", "/Library/Preferences", "/Library/Keychains",
                "/private/etc", "/private/var/db/timezone", "/private/var/db/mds", "/dev", "/usr/sbin", "/sbin"]


RUNNER_FILES = ["private/runners/controller.py", "private/runners/proxy.py", "private/runners/adapters/_common.py",
                "private/runners/products.json"]


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def runner_binding(adapter_id: str) -> dict[str, str]:
    """Hashes of the runner code and configuration in force for one adapter (bound by the run bundle, pilot1-bundle-v2)."""
    files = [*RUNNER_FILES, f"private/runners/adapters/{adapter_id}.py"]
    return {f: _sha(PROJECT_ROOT / f) for f in files}


def config() -> dict[str, Any]:
    return json.loads(PRODUCTS.read_text(encoding="utf-8"))


def _abs(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else PROJECT_ROOT / q


def contestant_profile(run_root: Path, proxy_port: int, extra_reads: list[Path], extra_rules: str = "") -> str:
    """`extra_rules`: an adapter's declared SANDBOX_EXTRA (e.g. Antigravity's local language-server port, ID-49), appended
    last so it is visible in the per-run profile and its hash; the default for every other product is none."""
    py = (REPLAY_ENV / "bin" / "python").resolve()
    base = py.parent.parent
    reads = [*SYSTEM_READS, str(REPLAY_ENV), str(base), *(str(p) for p in extra_reads),
             str(run_root / "work"), str(run_root / "home"), str(run_root / "tmp")]
    allow_reads = " ".join(f'(subpath "{r}")' for r in sorted(set(reads)))
    writes = " ".join(f'(subpath "{run_root / d}")' for d in ("work", "home", "tmp"))
    return f"""(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote ip "localhost:{proxy_port}"))
(allow network* (local unix-socket))
(deny file-read-data)
(allow file-read-data (literal "/") (literal "/private") (literal "/private/var") {allow_reads})
(deny file-read-data (subpath "{base / 'lib' / 'python3.12' / 'site-packages'}"))
(deny file-write*)
(allow file-write* {writes} (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/ttys[0-9]+$"))
{extra_rules}"""


def _descendants(root_pid: int) -> set[int]:
    out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        try:
            pid, ppid = map(int, line.split())
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    found, stack = set(), [root_pid]
    while stack:
        p = stack.pop()
        for c in children.get(p, []):
            if c not in found:
                found.add(c)
                stack.append(c)
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _kill_tree(proc: subprocess.Popen, known: set[int]) -> int:
    known |= _descendants(proc.pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in [proc.pid, *sorted(known)]:
            try:
                os.killpg(pid, sig) if pid == proc.pid else os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1.0 if sig == signal.SIGTERM else 0.2)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    return sum(1 for pid in known if _alive(pid))


def _snapshot(work: Path, dest: Path, exclude: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dirpath, dirnames, filenames in os.walk(work, followlinks=False):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            rel = p.relative_to(work).as_posix()
            if rel in exclude:
                continue
            if p.is_symlink() or not p.is_file():
                out[rel] = {"special": True}
                continue
            d = dest / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, d, follow_symlinks=False)
            d.chmod(0o444)
            out[rel] = {"sha256": _sha(d), "bytes": d.stat().st_size}
    return out


def _probe_canary(profile: Path, run_root: Path, canary: Path) -> dict[str, Any]:
    r = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat", str(canary)], capture_output=True, text=True,
                       cwd=run_root / "work", timeout=30)
    leaked = canary.read_text() in r.stdout
    r2 = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/ls", str(PROJECT_ROOT / "private")], capture_output=True,
                        text=True, cwd=run_root / "work", timeout=30)
    return {"canary_readable": leaked, "private_repo_listable": r2.returncode == 0, "passed": not leaked and r2.returncode != 0}


AVAILABILITY_PATTERNS = [r"usage limit", r"rate.?limit", r"\b429\b", r"quota", r"overloaded", r"\b529\b", r"limit reached",
                         r"try again (?:at|in|later)", r"insufficient_quota",
                         r"not logged in|login required|please (?:log|sign) in|authentication (?:failed|error|required)|unauthori[sz]ed|\b401\b"]


QUOTA_OK_STATUSES = {"allowed", "allowed_warning"}         # Claude Code rate_limit_event: below the limit (a warning is not a hit)


def _quota_telemetry(line: str) -> bool:
    """A product quota event that reports usage below the limit. Claude Code emits `allowed_warning` once utilization
    passes a threshold; treating it as a limit hit would label that product's no-output runs as availability events."""
    try:
        ev = json.loads(line)
    except ValueError:
        return False
    if not isinstance(ev, dict) or ev.get("type") != "rate_limit_event":
        return False
    info = ev.get("rate_limit_info")
    return isinstance(info, dict) and info.get("status") in QUOTA_OK_STATUSES


def availability_signals(*paths: Path) -> list[str]:
    """Quota, rate-limit, overload or authentication signals in the product's own output. A run that produced no answer
    and shows one of these is an availability/infrastructure event (ID-43), handled by the failure policy, never an
    analysis error; the classification is recorded with the matched lines for owner review."""
    import re
    hits = []
    for p in paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")[-200000:]
        except OSError:
            continue
        for line in text.splitlines():
            if _quota_telemetry(line):                               # informational quota telemetry, not a limit hit
                continue
            if any(re.search(pat, line, flags=re.IGNORECASE) for pat in AVAILABILITY_PATTERNS):
                hits.append(line.strip()[:300])
    return hits[:20]


def run_slot(product: str, task_dir: Path, out_dir: Path, run_meta: dict[str, Any], time_limit_s: float | None = None,
             adapter_override: Any = None) -> dict[str, Any]:
    """Run one fresh session. `adapter_override` (tests only) supplies a fake product adapter; the record says so."""
    cfg = config()
    spec = dict(cfg["products"][product])
    limit = float(time_limit_s if time_limit_s is not None else cfg["time_limit_s"])
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise RuntimeError(f"output directory {out_dir} is not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    if adapter_override is not None:
        adapter = adapter_override
    else:
        import importlib
        adapter = importlib.import_module(f"runners.adapters.{spec['adapter']}")
    record: dict[str, Any] = {"run": run_meta, "product_name": product, "adapter_id": adapter.ADAPTER_ID, "interface": "cli",
                              "protocol_version": "pilot1-controller-v1", "time_limit_s": limit, "test_adapter": adapter_override is not None}
    # a short run root: some products bind AF_UNIX sockets under their temp directory (path length limit ~104 bytes)
    with tempfile.TemporaryDirectory(prefix="ab-", dir="/private/tmp") as tmp:
        run_root = Path(tmp).resolve()
        work, home, rtmp = run_root / "work", run_root / "home", run_root / "tmp"
        for d in (work, home, rtmp):
            d.mkdir()
        shutil.copyfile(Path(task_dir) / "task.md", work / "task.md")
        if subprocess.run(["/bin/cp", "-c", str(Path(task_dir) / "game.duckdb"), str(work / "game.duckdb")], capture_output=True).returncode:
            shutil.copyfile(Path(task_dir) / "game.duckdb", work / "game.duckdb")
        (work / "game.duckdb").chmod(0o444)
        listing = sorted(p.name for p in work.iterdir())
        record["staging"] = {"listing": listing, "task_sha256": _sha(work / "task.md"), "database_sha256": _sha(work / "game.duckdb"),
                             "source_task_sha256": _sha(Path(task_dir) / "task.md"), "source_database_sha256": _sha(Path(task_dir) / "game.duckdb")}
        if listing != ["game.duckdb", "task.md"] or record["staging"]["task_sha256"] != record["staging"]["source_task_sha256"] \
                or record["staging"]["database_sha256"] != record["staging"]["source_database_sha256"]:
            raise RuntimeError(f"staging failed: {record['staging']}")
        canary = run_root / "canary.txt"
        canary.write_text("CANARY-" + hashlib.sha256(os.urandom(16)).hexdigest())
        extra_reads, env_extra = adapter.prepare(spec, home, PROJECT_ROOT)
        record["identity"] = adapter.identity(spec, PROJECT_ROOT)
        record["settings_snapshot"] = adapter.settings_snapshot(spec)
        record["settings_snapshot_sha256"] = hashlib.sha256(json.dumps(record["settings_snapshot"], sort_keys=True).encode()).hexdigest()
        if adapter_override is None:
            record["runner_binding"] = runner_binding(adapter.ADAPTER_ID)
        egress_log = out_dir / "egress.jsonl"
        egress_log.touch()
        with AllowlistProxy(spec["egress_allowlist"], egress_log) as proxy:
            profile = run_root / "contestant.sb"
            sandbox_extra = getattr(adapter, "SANDBOX_EXTRA", "")
            record["sandbox_extra"] = sandbox_extra or None
            profile.write_text(contestant_profile(run_root, proxy.port, extra_reads, sandbox_extra), encoding="utf-8")
            record["profile_sha256"] = _sha(profile)
            record["canary_check"] = _probe_canary(profile, run_root, canary)
            if not record["canary_check"]["passed"]:
                raise RuntimeError(f"isolation canary check failed: {record['canary_check']}")
            proxy_url = f"http://127.0.0.1:{proxy.port}"
            env = {"PATH": f"{REPLAY_ENV / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(home), "TMPDIR": str(rtmp), "TZ": "UTC",
                   "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
                   "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "MPLBACKEND": "Agg",
                   "HTTPS_PROXY": proxy_url, "HTTP_PROXY": proxy_url, "ALL_PROXY": proxy_url,
                   "https_proxy": proxy_url, "http_proxy": proxy_url, "all_proxy": proxy_url, "NO_PROXY": "", "no_proxy": "", **env_extra}
            for k in list(env):
                if k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
                    raise RuntimeError(f"{k} must never be in a contestant environment (subscription authentication only)")
            argv = adapter.argv(spec, work, cfg["opening_prompt"])
            record["argv_redacted"] = [a if a != cfg["opening_prompt"] else "<OPENING_PROMPT>" for a in argv]
            stdout_p, stderr_p = out_dir / "transcript.jsonl", out_dir / "stderr.log"
            known: set[int] = set()
            record["started_at_utc"] = _now()
            start = time.monotonic()
            with open(stdout_p, "wb") as so, open(stderr_p, "wb") as se:
                proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(profile), *argv], cwd=work, env=env, stdin=subprocess.DEVNULL,
                                        stdout=so, stderr=se, start_new_session=True)
                stop = None
                while proc.poll() is None:
                    if time.monotonic() - start >= limit:
                        stop = "timeout"
                        break
                    known |= _descendants(proc.pid)
                    time.sleep(0.25)
                ended = time.monotonic()                     # measured at exit or at the deadline, before the kill routine
                left = _kill_tree(proc, known)
                record["elapsed_seconds"] = round(min(ended - start, limit) if stop else ended - start, 3)
                record["ended_at_utc"] = _now()
                record["stop_reason"] = stop or ("exited" if proc.returncode == 0 else f"exit_code_{proc.returncode}")
                record["returncode"] = proc.returncode
                record["descendants_seen"] = len(known)
                record["processes_left_after_kill"] = left
        if hasattr(adapter, "collect"):                     # product session evidence from the disposable home
            record["session_evidence"] = adapter.collect(home, out_dir)
        outputs = out_dir / "outputs"
        outputs.mkdir()
        record["output_hashes"] = _snapshot(work, outputs, exclude={"game.duckdb", "task.md"})
        record["database_unchanged"] = _sha(work / "game.duckdb") == record["staging"]["database_sha256"]
        record["task_unchanged"] = _sha(work / "task.md") == record["staging"]["task_sha256"]
    record["egress"] = summarize(egress_log)
    from .proxy import host_allowed
    background = spec.get("background_hosts", [])
    is_bg = lambda d: host_allowed(d["target"].rpartition(":")[0], 443, background)
    record["egress"]["denied_product_background"] = [d for d in record["egress"]["denied"] if is_bg(d)]
    record["egress"]["denied"] = [d for d in record["egress"]["denied"] if not is_bg(d)]
    record["external_access_attempts"] = len(record["egress"]["denied"])          # excludes known product background traffic
    record["transcript_path"] = "transcript.jsonl"
    record["transcript_sha256"] = _sha(stdout_p)
    record["usage"], record["observed"] = adapter.parse(stdout_p, stderr_p)
    record["availability_signals"] = availability_signals(stdout_p, stderr_p)
    record["outcome_status"] = ("timeout" if record["stop_reason"] == "timeout" else
                                "completed" if {"answer.json", "memo.md"} <= set(record["output_hashes"]) else
                                "availability_limit" if record["availability_signals"] else "incomplete")
    record["clarification_requests"] = record["retries"] = record["analytical_interventions"] = 0
    (out_dir / "run_record.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return record
