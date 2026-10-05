"""Interim local restricted-process replay (design 5.1: 60-second / 4-GB replay, no network, raw database only).

Owner-approved INTERIM stand-in for the separate replay VM; revised after replay/alias audits round 1 and 2 (2026-10-03).

Job boundary. `replay()` starts a FRESH supervisor process per job (`python -m evaluation.replay --job SPEC`) under an
outer deadline (contestant deadline + SUPERVISOR_EXTRA_S); the supervisor stages the files, runs the contestant file
under macOS `sandbox-exec`, then parses the result tables in a second sandboxed step. Missing the outer deadline is an
`infrastructure` outcome (never an agent error) and the recorded contestant pid is killed.

Sandbox: no network; no fork/vfork/posix_spawn and no exec except the replay interpreter (a replay is one process);
file contents readable only from the system libraries, the replay environment (.tools/replay-env), the base Python
install WITHOUT its site-packages, and the job's own directory; writes only inside the job directory.

Execution contract (to be published to contestants before scored attempts):
  - the transformation runs as ONE process (threads allowed; subprocess / process-based multiprocessing are not);
  - packages: exactly the common lock (private/environment/contestant-macos-arm64.lock);
  - 60 s wall clock; 4 GiB (4,294,967,296 bytes) memory as a MONITORED soft limit (footprint polled every 50 ms;
    allocation between polls is not bounded; the hard limit belongs to the final replay VM);
  - each written file must stay below 64 MiB (67,108,864 bytes; a file reaching it is `output_limit`, since the OS
    truncates silently); the work directory may hold at most WORK_QUOTA bytes and WORK_FILES files besides the database
    (monitored every second);
  - result tables: .csv, .json or .parquet files the script CREATED during the run at paths that were not staged
    inputs (staged files never count, even if rewritten or touched), at most 50 files, each at most MAX_ROWS rows /
    MAX_CELLS cells (SQL results too). They are copied out before cleanup and parsed IN FULL by a sandboxed reader with
    its own budget (30 s, 2 GiB, one output file per table under a 1 GiB limit); CSV cells as exact strings, JSON as
    parsed values, Parquet with column types; nulls and duplicate rows preserved. A 64 KiB preview is kept separately.
    A declared shape or format violation is `invalid_output`; a reader failure on compliant files is `infrastructure`.
  - a formal replay starts only after a LIVE runtime check against the stored attestation (content and symlinks);
    a missing or mismatched attestation stops the job as `infrastructure` and is never re-attested automatically.
Interim limits: one shared host kernel; monitored, not hard, memory; host-platform lock, not yet the contestant guest's.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

TIME_LIMIT_S = 60
MEMORY_LIMIT_BYTES = 4 * 1024 ** 3
SUPERVISOR_EXTRA_S = 90
MAX_STAGED_BYTES = 50 * 1024 ** 2
FILE_SIZE_LIMIT = 64 * 1024 ** 2
WORK_QUOTA = 512 * 1024 ** 2
WORK_FILES = 10_000
LOG_TAIL = 64 * 1024
PREVIEW_BYTES = 64 * 1024
MAX_RESULT_FILES = 50
MAX_ROWS = 1_000_000
MAX_CELLS = 10_000_000
READER_TIME_S = 30
READER_MEMORY = 2 * 1024 ** 3
RESULT_SUFFIXES = {".csv", ".json", ".parquet"}
RESERVED = {"game.duckdb", "_replay_out", "tmp"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY_ENV = PROJECT_ROOT / ".tools" / "replay-env"
DEFAULT_ATTESTATION = PROJECT_ROOT / "private" / "environment" / "replay-runtime-macos-arm64.json"
REPLAY_ENV = Path(os.environ.get("ANALYST_BENCH_REPLAY_ENV", str(DEFAULT_REPLAY_ENV)))            # fixtures only
ATTESTATION = Path(os.environ.get("ANALYST_BENCH_ATTESTATION", str(DEFAULT_ATTESTATION)))          # fixtures only
REPLAY_LOCK = PROJECT_ROOT / "private" / "environment" / "contestant-macos-arm64.lock"
READER_FILE_LIMIT = 1024 ** 3        # the trusted reader's own per-file limit (one output file per table)
STATUSES = ("ok", "error", "timeout", "memory", "output_limit", "rejected", "database_modified", "invalid_output", "infrastructure")

SQL_RUNNER = r'''
import json, sys, duckdb
con = duckdb.connect("game.duckdb", read_only=True, config={"memory_limit": "4GB", "threads": 4,
                     "autoinstall_known_extensions": False, "autoload_known_extensions": False})
cur = con.execute(open(sys.argv[1], encoding="utf-8").read())
cols = [d[0] for d in cur.description] if cur.description else []
types = [str(d[1]) for d in cur.description] if cur.description else []
rows = cur.fetchmany(%d + 1) if cols else []
if len(rows) > %d or len(rows) * len(cols) > %d:
    raise SystemExit("SHAPE_LIMIT: result exceeds the row or cell limit")
with open("_replay_out/result.json", "w", encoding="utf-8") as f:
    json.dump({"columns": cols, "types": types, "rows": rows}, f, default=str)
''' % (MAX_ROWS, MAX_ROWS, MAX_CELLS)

READER = r'''
import csv, json, os
MAX_ROWS, MAX_CELLS = %d, %d
csv.field_size_limit(%d)
class Shape(Exception):
    pass
def jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)
def count_cells(v):
    if isinstance(v, list):
        return sum(count_cells(x) for x in v)
    if isinstance(v, dict):
        return sum(count_cells(x) for x in v.values())
    return 1
index = {}
for n, rel in enumerate(json.load(open("manifest.json"))):
    path = os.path.join("files", rel)
    try:
        if rel.endswith(".csv"):
            cols, data, cells = None, [], 0
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if cols is None:
                        cols = row
                        continue
                    data.append(row)
                    cells += len(row)
                    if len(data) > MAX_ROWS or cells > MAX_CELLS:
                        raise Shape("more than %%d rows or %%d cells" %% (MAX_ROWS, MAX_CELLS))
            table = {"format": "csv", "columns": cols or [], "types": ["text"] * len(cols or []), "rows": data}
        elif rel.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                value = json.load(f)
            rows = value if isinstance(value, list) else value.get("rows") if isinstance(value, dict) else None
            if isinstance(rows, list) and len(rows) > MAX_ROWS or count_cells(value) > MAX_CELLS:
                raise Shape("more than %%d rows or %%d cells" %% (MAX_ROWS, MAX_CELLS))
            table = {"format": "json", "value": value}
        else:
            import pyarrow.parquet as pq
            meta = pq.ParquetFile(path).metadata
            if meta.num_rows > MAX_ROWS or meta.num_rows * meta.num_columns > MAX_CELLS:
                raise Shape("more than %%d rows or %%d cells" %% (MAX_ROWS, MAX_CELLS))
            t = pq.read_table(path)
            cols = t.column_names
            table = {"format": "parquet", "columns": cols, "types": [str(f.type) for f in t.schema],
                     "rows": [[jsonable(r[c]) for c in cols] for r in t.to_pylist()]}
        if "rows" in table:
            table["row_count"] = len(table["rows"])
        out = "table_%%d.json" %% n
        with open(out, "w", encoding="utf-8") as f:
            json.dump(table, f)
        index[rel] = {"file": out}
    except Shape as exc:
        index[rel] = {"error_kind": "shape_limit", "error": str(exc)}
    except (ValueError, UnicodeDecodeError, csv.Error) as exc:
        index[rel] = {"error_kind": "parse_error", "error": ("%%s: %%s" %% (type(exc).__name__, exc))[:500]}
    except Exception as exc:
        if type(exc).__module__.startswith("pyarrow") or "Parquet" in type(exc).__name__ or "Arrow" in type(exc).__name__:
            index[rel] = {"error_kind": "parse_error", "error": ("%%s: %%s" %% (type(exc).__name__, exc))[:500]}
        else:
            raise
with open("index.json", "w", encoding="utf-8") as f:
    json.dump(index, f)
''' % (MAX_ROWS, MAX_CELLS, FILE_SIZE_LIMIT)


class ReplayRejected(Exception):
    """The submission cannot be staged (path escape, symlink, reserved name, missing file, size)."""


@dataclass
class ReplayResult:
    status: str
    elapsed_s: float = 0.0                       # contestant process wall time (the 60 s deadline)
    job_elapsed_s: float = 0.0                   # whole supervised job (outer deadline = contestant + SUPERVISOR_EXTRA_S)
    peak_bytes: int = 0
    returncode: int | None = None
    table: dict[str, Any] | None = None          # SQL: the last statement's complete result
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)   # Python: complete parsed result files
    files: dict[str, dict[str, Any]] = field(default_factory=dict)    # per result file: sha256, bytes, preview, retained path
    stdout_tail: str = ""
    stderr_tail: str = ""
    detail: str = ""
    environment: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _sha_regular(path: Path) -> str | None:
    """SHA-256 of a regular file reached without following links; None for anything else, 'unreadable' if it cannot be read."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return "unreadable"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        h = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unreadable"
    finally:
        os.close(fd)


def _read_regular(path: Path, limit: int, tail: bool = False) -> str | None:
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return None
        with open(path, "rb") as f:
            if tail and st.st_size > limit:
                f.seek(st.st_size - limit)
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def safe_member(answer_dir: Path, rel: str) -> Path:
    """Resolve a contestant-supplied relative path, refusing escapes, absolute paths, reserved names and symlinks."""
    answer_dir = answer_dir.resolve()
    if not isinstance(rel, str) or not rel or "\\" in rel or "\0" in rel:
        raise ReplayRejected(f"invalid path {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or rel.startswith("~"):
        raise ReplayRejected(f"path escapes the answer directory: {rel}")
    if pure.parts[0] in RESERVED or pure.parts[0].startswith("_replay"):
        raise ReplayRejected(f"reserved name: {rel}")
    cur = answer_dir
    for part in pure.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ReplayRejected(f"symlink in path: {rel}")
    st = os.lstat(cur) if os.path.lexists(cur) else None
    if st is None or not stat.S_ISREG(st.st_mode) or not cur.resolve().is_relative_to(answer_dir):
        raise ReplayRejected(f"not a regular file inside the answer directory: {rel}")
    return cur


# --- runtime --------------------------------------------------------------------------------------------------------

def replay_python() -> tuple[Path, bool]:
    """(interpreter, formal-eligible). Only the default environment with the default attestation can be formal, and only
    after a live runtime check at job entry; an interpreter override is always non-formal and unchecked."""
    override = os.environ.get("ANALYST_BENCH_REPLAY_PYTHON")
    if override:
        return Path(override), False
    return REPLAY_ENV / "bin" / "python", REPLAY_ENV == DEFAULT_REPLAY_ENV and ATTESTATION == DEFAULT_ATTESTATION


def _base_prefix(py: Path) -> Path:
    return py.resolve().parent.parent


def runtime_files(py: Path) -> list[Path]:
    """Every file or symlink the replay may load: the replay environment and the base install minus its site-packages."""
    base = _base_prefix(py)
    env = py.parent.parent if py.parent.parent != base else None
    out = []
    for root in [r for r in (env, base) if r is not None]:
        for p in root.rglob("*"):
            if (p.is_symlink() or p.is_file()) and not (root == base and "site-packages" in p.relative_to(base).parts):
                out.append(p)
    return sorted(set(out))


def attest_runtime(py: Path | None = None) -> dict[str, Any]:
    """Content attestation of the replay runtime (all loadable files) plus the lock it was built from."""
    py = py or replay_python()[0]
    h = hashlib.sha256()
    files = runtime_files(py)
    for p in files:
        h.update(str(p.relative_to(PROJECT_ROOT) if p.is_relative_to(PROJECT_ROOT) else p).encode() + b"\0")
        if p.is_symlink():
            h.update(b"symlink\0" + os.readlink(p).encode() + b"\0")
        else:
            h.update(b"file\0" + hashlib.sha256(p.read_bytes()).digest())
    dists = sorted(p.name for p in (py.parent.parent / "lib").rglob("*.dist-info"))
    return {"python": str(py), "python_resolved": str(py.resolve()), "files": len(files), "content_sha256": h.hexdigest(),
            "distributions": dists, "lock": str(REPLAY_LOCK.relative_to(PROJECT_ROOT)),
            "lock_sha256": hashlib.sha256(REPLAY_LOCK.read_bytes()).hexdigest()}


def verify_runtime_for_job(py: Path, checked: bool) -> tuple[dict[str, Any] | None, str | None]:
    """Live check at job entry. Returns (identity, None) or (None, reason). The attestation is never rewritten here."""
    ident: dict[str, Any] = {"python": str(py), "python_resolved": str(py.resolve()), "runtime_checked": checked}
    if not checked:
        return dict(ident, formal_runtime=False), None
    if not ATTESTATION.is_file():
        return None, f"runtime attestation missing: {ATTESTATION}"
    stored = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    live = attest_runtime(py)
    diff = [k for k in ("content_sha256", "files", "distributions", "lock_sha256", "python_resolved") if stored.get(k) != live.get(k)]
    if diff:
        return None, f"runtime does not match its attestation: {diff}"
    return dict(ident, formal_runtime=REPLAY_ENV == DEFAULT_REPLAY_ENV and ATTESTATION == DEFAULT_ATTESTATION,
                attestation_sha256=hashlib.sha256(ATTESTATION.read_bytes()).hexdigest(),
                runtime_content_sha256_live=live["content_sha256"], lock_sha256_live=live["lock_sha256"]), None


def _profile(work: Path, py: Path) -> str:
    base = _base_prefix(py)
    env = py.parent.parent
    reads = " ".join(f'(subpath "{p}")' for p in sorted({str(env), str(base), str(work)}))
    return f"""(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny process-exec)
(allow process-exec (literal "{py}") (literal "{py.resolve()}"))
(deny file-read-data)
(allow file-read-data (literal "/") (subpath "/usr/lib") (subpath "/System") (subpath "/usr/share")
  (subpath "/private/var/db/timezone") (subpath "/dev") (literal "/private/etc/localtime") {reads})
(deny file-read-data (subpath "{base / 'lib' / 'python3.12' / 'site-packages'}"))
(deny file-write*)
(allow file-write* (subpath "{work}") (literal "/dev/null"))
"""


class _RUsageInfoV2(ctypes.Structure):
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins", "ri_wired_size",
        "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime", "ri_proc_exit_abstime", "ri_child_user_time",
        "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups", "ri_child_pageins",
        "ri_child_elapsed_abstime", "ri_diskio_bytesread", "ri_diskio_byteswritten")]


_LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")


def _footprint(pid: int) -> int | None:
    info = _RUsageInfoV2()
    return int(info.ri_phys_footprint) if _LIBPROC.proc_pid_rusage(pid, 2, ctypes.byref(info)) == 0 else None


def _limiter(file_limit: int):
    def _limit_child() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return _limit_child


def _work_usage(work: Path) -> tuple[int, int]:
    total = count = 0
    for dirpath, dirnames, filenames in os.walk(work, followlinks=False):
        for name in filenames:
            if dirpath == str(work) and name == "game.duckdb":
                continue
            count += 1
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total, count


def _snapshot(work: Path) -> dict[str, tuple[int, int, int]]:
    out = {}
    for p in work.rglob("*"):
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out[p.relative_to(work).as_posix()] = (st.st_ino, st.st_mtime_ns, st.st_size)
    return out


def _sandboxed(py: Path, cwd: Path, argv: list[str], env: dict[str, str], time_limit: float, memory_limit: int,
               out_path: Path, err_path: Path, pid_file: Path | None = None,
               file_limit: int = FILE_SIZE_LIMIT) -> tuple[str | None, int | None, float, int, bool]:
    """Run one sandboxed single process; returns (forced status or None, returncode, elapsed, peak, measurement_failed)."""
    profile = cwd.parent / f"{cwd.name}.sb"
    profile.write_text(_profile(cwd, py), encoding="utf-8")
    with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
        start = time.monotonic()
        proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(profile), str(py), "-E", "-s", *argv], cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f, start_new_session=True,
                                preexec_fn=_limiter(file_limit))
        if pid_file:
            pid_file.write_text(str(proc.pid))
        status, peak, failed, tick = None, 0, False, 0
        while proc.poll() is None:
            fp = _footprint(proc.pid)
            if fp is None:
                if proc.poll() is None:
                    failed, status = True, "infrastructure"
            else:
                peak = max(peak, fp)
                if peak > memory_limit:
                    status = "memory"
            if status is None and time.monotonic() - start > time_limit:
                status = "timeout"
            tick += 1
            if status is None and tick % 20 == 0:
                total, count = _work_usage(cwd)
                if total > WORK_QUOTA or count > WORK_FILES:
                    status = "output_limit"
            if status:
                for kill in (lambda: os.killpg(proc.pid, signal.SIGKILL), proc.kill):
                    try:
                        kill()
                    except ProcessLookupError:
                        pass
                break
            time.sleep(0.05)
        proc.wait(timeout=10)
        elapsed = time.monotonic() - start
    return status, proc.returncode, elapsed, peak, failed


def _base_env(work: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(work), "TMPDIR": str(work / "tmp"), "TZ": "UTC", "LC_ALL": "en_US.UTF-8",
            "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "4",
            "OPENBLAS_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(work / "tmp")}


def _run_job(spec: dict[str, Any]) -> ReplayResult:
    """Supervisor body: runs in a fresh process for exactly one replay."""
    job_start = time.monotonic()
    answer_dir, database = Path(spec["answer_dir"]), Path(spec["database"])
    try:
        main = safe_member(answer_dir, spec["transformation"])
        extra = [safe_member(answer_dir, e) for e in spec.get("evidence") or [] if e != spec["transformation"]]
        if main.suffix not in (".sql", ".py"):
            raise ReplayRejected(f"transformation must be .sql or .py: {spec['transformation']}")
        if sum(p.stat().st_size for p in [main, *extra]) > MAX_STAGED_BYTES:
            raise ReplayRejected("staged files exceed the size cap")
    except ReplayRejected as exc:
        return ReplayResult("rejected", detail=str(exc))
    db_sha = _sha_regular(database)
    if db_sha in (None, "unreadable"):
        return ReplayResult("infrastructure", detail="the source database is not a readable regular file")
    py, eligible = replay_python()
    if not py.exists():
        return ReplayResult("infrastructure", detail=f"replay interpreter missing: {py}")
    checked = "ANALYST_BENCH_REPLAY_PYTHON" not in os.environ          # default env or a fixture env with its attestation
    ident, why = verify_runtime_for_job(py, checked)
    if ident is None:
        return ReplayResult("infrastructure", detail=why, job_elapsed_s=round(time.monotonic() - job_start, 3))
    environment = {**ident, "time_limit_s": spec["time_limit_s"], "memory_limit_bytes": spec["memory_limit"],
                   "memory_limit_kind": "monitored soft limit (50 ms sampling); not kernel-enforced",
                   "file_size_limit": FILE_SIZE_LIMIT, "work_quota_bytes": WORK_QUOTA, "single_process": True}
    ctl = Path(spec["control_dir"])
    work = ctl / "work"
    (work / "_replay_out").mkdir(parents=True)
    (work / "tmp").mkdir()
    for p in [main, *extra]:
        dest = work / p.resolve().relative_to(answer_dir.resolve())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest, follow_symlinks=False)
    db = work / "game.duckdb"
    if subprocess.run(["/bin/cp", "-c", str(database), str(db)], capture_output=True).returncode != 0:
        shutil.copyfile(database, db)
    db.chmod(0o444)
    (work / "_replay_out" / "run_sql.py").write_text(SQL_RUNNER, encoding="utf-8")
    before = _snapshot(work)
    rel = main.resolve().relative_to(answer_dir.resolve()).as_posix()
    argv = ["_replay_out/run_sql.py", rel] if main.suffix == ".sql" else [rel]
    environment["profile_sha256"] = hashlib.sha256(_profile(work, py).encode()).hexdigest()
    status, rc, elapsed, peak, failed = _sandboxed(py, work, argv, _base_env(work), spec["time_limit_s"], spec["memory_limit"],
                                                   ctl / "stdout.log", ctl / "stderr.log", ctl / "child.pid")
    peak = max(peak, int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
    if status is None and peak > spec["memory_limit"]:
        status = "memory"
    if status is None:
        status = "ok" if rc == 0 else ("output_limit" if rc == -signal.SIGXFSZ else "error")
        if status == "error" and main.suffix == ".sql" and "SHAPE_LIMIT" in (_read_regular(ctl / "stderr.log", LOG_TAIL, tail=True) or ""):
            status = "invalid_output"
    res = ReplayResult(status, round(elapsed, 3), 0.0, peak, rc, stdout_tail=_read_regular(ctl / "stdout.log", LOG_TAIL, tail=True) or "",
                       stderr_tail=_read_regular(ctl / "stderr.log", LOG_TAIL, tail=True) or "", environment=environment)

    def done(r: ReplayResult) -> ReplayResult:
        r.job_elapsed_s = round(time.monotonic() - job_start, 3)
        return r

    if failed:
        res.detail = "memory footprint could not be read while the process was alive"
    if "sandbox_apply" in res.stderr_tail:
        res.status, res.detail = "infrastructure", "sandbox could not be applied (run the replay on the grader host)"
        return done(res)
    if _sha_regular(db) != db_sha:
        res.status, res.detail = "database_modified", "the replay database was changed, replaced, made unreadable or removed"
        return done(res)
    if _sha_regular(database) != db_sha:
        res.status, res.detail = "infrastructure", "the source database changed during the replay"
        return done(res)
    if res.status != "ok":
        return done(res)
    nonregular, written = [], []
    for dirpath, dirnames, filenames in os.walk(work, followlinks=False):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            r = p.relative_to(work).as_posix()
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                nonregular.append(r)
                continue
            if st.st_size >= FILE_SIZE_LIMIT and r != "game.duckdb":
                res.status, res.detail = "output_limit", f"file reached the {FILE_SIZE_LIMIT}-byte cap: {r}"
                return done(res)
            if p.suffix in RESULT_SUFFIXES and not r.startswith("_replay_out/") and r not in before:
                written.append(r)              # staged inputs never count as results, even if rewritten or touched
    for n in ("stdout.log", "stderr.log"):
        if (ctl / n).stat().st_size >= FILE_SIZE_LIMIT:
            res.status, res.detail = "output_limit", f"{n} reached the {FILE_SIZE_LIMIT}-byte cap"
            return done(res)
    total, count = _work_usage(work)
    if total > WORK_QUOTA or count > WORK_FILES:
        res.status, res.detail = "output_limit", f"work directory holds {total} bytes in {count} files"
        return done(res)
    if nonregular:
        res.status, res.detail = "invalid_output", f"non-regular nodes in the work directory: {sorted(nonregular)[:10]}"
        return done(res)
    if len(written) > MAX_RESULT_FILES:
        res.status, res.detail = "invalid_output", f"more than {MAX_RESULT_FILES} result files"
        return done(res)
    if main.suffix == ".sql":
        text = _read_regular(work / "_replay_out" / "result.json", FILE_SIZE_LIMIT)
        try:
            res.table = json.loads(text) if text is not None else None
        except ValueError:
            res.table = None
        if not isinstance(res.table, dict) or not isinstance(res.table.get("rows"), list):
            res.status, res.detail = "invalid_output", "the SQL result could not be read"
            return done(res)
    # copy written result files out, then parse them in full in a separate sandboxed reader
    reader = ctl / "reader"
    (reader / "files").mkdir(parents=True)
    (reader / "tmp").mkdir()
    retain = Path(spec["retain_dir"]) if spec.get("retain_dir") else None
    for r in sorted(written):
        src, dst = work / r, reader / "files" / r
        dst.parent.mkdir(parents=True, exist_ok=True)
        sha = _sha_regular(src)
        if sha in (None, "unreadable"):
            res.status, res.detail = "invalid_output", f"result file is not a readable regular file: {r}"
            return done(res)
        shutil.copyfile(src, dst, follow_symlinks=False)
        if _sha_regular(dst) != sha:
            res.status, res.detail = "invalid_output", f"result file changed while being copied: {r}"
            return done(res)
        res.files[r] = {"sha256": sha, "bytes": dst.stat().st_size,
                        "preview": _read_regular(dst, PREVIEW_BYTES) if dst.suffix != ".parquet" else None,
                        "preview_truncated": dst.stat().st_size > PREVIEW_BYTES}
        if retain:
            keep = retain / r
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dst, keep, follow_symlinks=False)
            res.files[r]["retained_path"] = str(keep)
    if written:
        (reader / "manifest.json").write_text(json.dumps(sorted(written)), encoding="utf-8")
        (reader / "read_tables.py").write_text(READER, encoding="utf-8")
        rstatus, rrc, _, _, _ = _sandboxed(py, reader, ["read_tables.py"], _base_env(reader), READER_TIME_S, READER_MEMORY,
                                           ctl / "reader.out", ctl / "reader.err", file_limit=READER_FILE_LIMIT)
        index_text = _read_regular(reader / "index.json", READER_FILE_LIMIT)
        if rstatus or rrc != 0 or index_text is None:
            # the trusted reader failed on files that met every contestant limit: a grading-infrastructure issue
            res.status = "infrastructure"
            res.detail = f"the result reader failed within its own budget ({rstatus or rrc}): " + \
                         (_read_regular(ctl / "reader.err", 2000, tail=True) or "")
            return done(res)
        index = json.loads(index_text)
        bad = {k: v for k, v in index.items() if "error_kind" in v}
        if bad:
            res.status, res.detail = "invalid_output", f"result files violate the declared shape or format: {bad}"
            return done(res)
        for rel_name, entry in index.items():
            text = _read_regular(reader / entry["file"], READER_FILE_LIMIT)
            if text is None:
                res.status, res.detail = "infrastructure", f"the reader's table file for {rel_name} is missing"
                return done(res)
            res.tables[rel_name] = json.loads(text)
    return done(res)


def replay(answer_dir: Path, transformation: str, database: Path, evidence: list[str] | None = None,
           time_limit_s: float = TIME_LIMIT_S, memory_limit: int = MEMORY_LIMIT_BYTES, retain_dir: Path | None = None) -> ReplayResult:
    """Run one replay job in a fresh supervisor under an outer deadline covering staging, execution and extraction.
    `retain_dir` (optional) receives byte copies of the result files for later audit."""
    base = os.environ.get("TMPDIR") or "/private/tmp"
    with tempfile.TemporaryDirectory(prefix="replay-", dir=base) as tmp:
        ctl = Path(tmp).resolve()
        spec = {"answer_dir": str(Path(answer_dir).resolve()), "transformation": transformation, "database": str(Path(database).resolve()),
                "evidence": evidence or [], "time_limit_s": time_limit_s, "memory_limit": memory_limit, "control_dir": str(ctl / "job"),
                "retain_dir": str(Path(retain_dir).resolve()) if retain_dir else None}
        (ctl / "job").mkdir()
        (ctl / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        with open(ctl / "supervisor.err", "wb") as sup_err:
            sup = subprocess.Popen([sys.executable, "-m", "evaluation.replay", "--job", str(ctl / "spec.json")], cwd=str(PROJECT_ROOT),
                                   stdout=subprocess.DEVNULL, stderr=sup_err, start_new_session=True)
            try:
                sup.wait(timeout=time_limit_s + SUPERVISOR_EXTRA_S)
            except subprocess.TimeoutExpired:
                for pid in (sup.pid, _int(ctl / "job" / "child.pid")):
                    if pid:
                        for kill in (lambda p: os.killpg(p, signal.SIGKILL), lambda p: os.kill(p, signal.SIGKILL)):
                            try:
                                kill(pid)
                            except (ProcessLookupError, PermissionError):
                                pass
                sup.wait(timeout=10)
                return ReplayResult("infrastructure", detail="the replay supervisor exceeded its outer deadline")
        out = ctl / "result.json"
        if sup.returncode != 0 or not out.is_file():
            err = (ctl / "supervisor.err").read_text(errors="replace")[-2000:]
            return ReplayResult("infrastructure", detail=f"the replay supervisor failed: {err}")
        return ReplayResult(**json.loads(out.read_text(encoding="utf-8")))


def _int(p: Path) -> int | None:
    try:
        return int(p.read_text())
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    spec_path = Path(sys.argv[sys.argv.index("--job") + 1])
    job = json.loads(spec_path.read_text(encoding="utf-8"))
    result = _run_job(job)
    (spec_path.parent / "result.json").write_text(json.dumps(result.to_json(), default=str), encoding="utf-8")


def check_runtime() -> tuple[bool, Any]:
    """Recompute the runtime content attestation and compare it with the stored one (and the lock hash)."""
    ident, why = verify_runtime_for_job(REPLAY_ENV / "bin" / "python", True)
    return (True, None) if ident else (False, why)
