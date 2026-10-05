"""Pilot-1 formal wave driver (design 6.4-6.5, 9.1; ID-43/44/45): the 36 scheduled slots of the certified run bundle.

One wave = one bundle. State is an append-only ledger (private/runs/wave/ledger.jsonl); every decision is derived from
it, so the driver can stop between slots and resume later without re-running or skipping anything. Rules:

  order        slots run strictly in bundle order; nothing is reordered, selected or retried for quality.
  binding      before every slot the bundle must pass its full check (runner files, adapters, products.json, freeze,
               gold, grading policy, grader), the ledger's bundle hash and driver hash must be the current ones, and the
               product executable must hash to the observed identity. After every slot the controller record must show
               the bound runner, runtime settings, executable, version and model. Any difference stops the wave
               (a forced update or model change is never pooled; the owner restarts under a new bundle).
  quota        subscription allowance only (ID-43). Owner instruction 2026-10-04: run until the allowance is used up,
               then pause. A slot starts unless the product's last observation shows the five-hour or weekly allowance
               exhausted (100%); then the driver waits for the provider's reset time. A run that hits the limit midway
               is an availability event; its replacement waits for the reset (never a blind 30-minute retry).
               Any sign of paid overage stops the wave.
  outcomes     controller outcome -> grader outcome: completed -> completed; timeout -> timeout (no replacement);
               incomplete -> error (no replacement); structured availability evidence (a product quota/auth/overload
               event, not a text match in tool output) with missing outputs or a product error result -> infrastructure.
               A pattern-only availability label without structured evidence stays `error` and is flagged for owner
               review. An exception before the product starts (staging) or a run interrupted by the host/driver is
               infrastructure. A failed canary stops the wave (isolation not established).
  replacement  one replacement attempt per slot for an infrastructure outcome, in a new sandbox, no earlier than 30
               minutes after the failure and after the provider's reset; both records are kept and the original is
               labelled. A second infrastructure outcome leaves the slot unresolved. Two consecutive infrastructure
               outcomes for one product stop the wave until the owner acknowledges the cause (`--acknowledge REASON`).
  sealing      the driver prints only slot identity, outcome status, elapsed time and quota; it never reads or prints
               answers or memos. The operator must not open slot outputs before the wave is complete (design 6.4).
  signals      Ctrl-C, SIGTERM or SIGHUP during a run is deferred: the run finishes (at most 1,200 s) and the driver
               stops before the next slot.
  exclusivity  one driver at a time: an exclusive lock on the wave directory for the whole session. Immediately before
               every slot the driver re-reads the ledger and stops if the current driver hash is not its own (a driver
               left waiting from before an accepted change) or if the slot was already started by another process.
               (Wave 1, 2026-10-04: a pre-change driver left waiting in another terminal woke after the reset and tried
               slot 24's replacement while the current driver was running it; see WAVE1_REPORT.md.)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .controller import AVAILABILITY_PATTERNS, PROJECT_ROOT, _sha

WAVE_DIR = PROJECT_ROOT / "private" / "runs" / "wave"
BUNDLE = PROJECT_ROOT / "private" / "run_bundle" / "manifest.json"
WAVES = {"1": (WAVE_DIR, BUNDLE),
         "2": (PROJECT_ROOT / "private" / "runs" / "wave2", PROJECT_ROOT / "private" / "run_bundle" / "wave2" / "manifest.json")}
EXPORT = PROJECT_ROOT / "private" / "tasks" / "export"
DRIVER_FILES = ["private/runners/wave.py", "scripts/run_wave.py"]
FIVE_HOUR_GATE = 1.0                       # owner, 2026-10-04: no early stop; pause only when the allowance is exhausted
WEEKLY_GATE = 1.0
WEEKLY_NEAR = 0.95                         # an availability failure with the weekly window this full waits for the weekly reset
WAIT_CHUNK_S = 30.0
REPLACEMENT_DELAY_S = 30 * 60
DEFAULT_RETRY_WAIT_S = 30 * 60
UNKNOWN_RESET_WAIT_S = 5 * 3600            # an availability failure with no reset time: wait one full five-hour window
GRADER_OUTCOME = {"completed": "completed", "timeout": "timeout", "incomplete": "error", "availability_limit": "error"}


class WaveStop(RuntimeError):
    """The wave must stop for the owner (binding, isolation, budget or repeated infrastructure failure)."""


def now() -> float:
    return time.time()


def utc(t: float | None = None) -> str:
    return datetime.fromtimestamp(now() if t is None else t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def driver_sha256(root: Path = PROJECT_ROOT) -> str:
    h = hashlib.sha256()
    for f in DRIVER_FILES:
        p = root / f
        h.update(f.encode() + b"\0" + (_sha(p).encode() if p.exists() else b"missing") + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------------- ledger --

class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def append(self, kind: str, **data: Any) -> dict[str, Any]:
        ev = {"t": round(now(), 3), "utc": utc(), "event": kind, **data}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, sort_keys=True, default=str) + "\n")
            f.flush()
        return ev


# ----------------------------------------------------------------------------------------------- quota / evidence --

def _jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                out.append(ev)
    return out


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def quota_from_slot(adapter: str, out_dir: Path) -> dict[str, Any] | None:
    """Last quota observation in a slot's own product evidence: fractions in [0, 1] and reset epochs."""
    out_dir = Path(out_dir)
    q = None
    if adapter == "claude_code_print":
        for ev in _jsonl(out_dir / "transcript.jsonl"):
            info = ev.get("rate_limit_info") if ev.get("type") == "rate_limit_event" else None
            if isinstance(info, dict):
                win = info.get("unifiedWindows") or {}
                fh, sd = win.get("five_hour") or {}, win.get("seven_day") or {}
                q = {"status": info.get("status"), "five_hour": fh.get("utilization"), "five_hour_resets_at": fh.get("resetsAt"),
                     "weekly": sd.get("utilization"), "weekly_resets_at": sd.get("resetsAt"),
                     "overage_status": info.get("overageStatus"), "using_overage": info.get("isUsingOverage")}
                if q["five_hour"] is None and info.get("rateLimitType") == "five_hour":
                    q["five_hour"], q["five_hour_resets_at"] = info.get("utilization"), info.get("resetsAt")
    else:
        for f in sorted(out_dir.glob("session_rollout_*.jsonl")):
            for ev in _jsonl(f):
                for d in _walk(ev):
                    rl = d.get("rate_limits")
                    if isinstance(rl, dict) and isinstance(rl.get("primary"), dict):
                        p, s = rl["primary"], rl.get("secondary") or {}
                        pct = lambda v: None if v is None else float(v) / 100.0
                        q = {"status": None, "five_hour": pct(p.get("used_percent")), "five_hour_resets_at": p.get("resets_at"),
                             "weekly": pct(s.get("used_percent")), "weekly_resets_at": s.get("resets_at"),
                             "overage_status": None, "using_overage": None}
    return q


def availability_retry(q: dict[str, Any] | None) -> float:
    """When a replacement may start after a product availability failure: the provider's reset (the weekly one when that
    window is nearly full, else the five-hour one); five hours when no reset time was observed."""
    q = q or {}
    if (q.get("weekly") or 0) >= WEEKLY_NEAR and q.get("weekly_resets_at"):
        return float(q["weekly_resets_at"])
    if q.get("five_hour_resets_at") and q["five_hour_resets_at"] > now():
        return float(q["five_hour_resets_at"])
    return now() + UNKNOWN_RESET_WAIT_S


def overage_signal(q: dict[str, Any] | None) -> str | None:
    if not q:
        return None
    if q.get("using_overage") is True:
        return "the product reports usage on paid overage"
    if q.get("overage_status") not in (None, "rejected", "disabled"):
        return f"paid overage is not disabled (overageStatus {q.get('overage_status')!r})"
    return None


_PAT = re.compile("|".join(AVAILABILITY_PATTERNS), re.IGNORECASE)
_QUOTA_OK = {"allowed", "allowed_warning"}


def structured_availability(adapter: str, out_dir: Path) -> list[str]:
    """Availability evidence from the product's own structured events and stderr, never from agent tool output."""
    out_dir = Path(out_dir)
    hits: list[str] = []
    events = _jsonl(out_dir / "transcript.jsonl")
    if adapter in ("grok_build", "antigravity_cli"):           # wave 2: product error records only (status ERROR / error objects)
        for ev in events:
            for d in _walk(ev):
                err = d.get("error")
                if (d.get("status") == "ERROR" or d.get("type") == "error" or isinstance(err, (str, dict))) and err and \
                        _PAT.search(json.dumps(err)):
                    hits.append("product error: " + json.dumps(err)[:200])
    elif adapter == "claude_code_print":
        for ev in events:
            info = ev.get("rate_limit_info") if ev.get("type") == "rate_limit_event" else None
            if isinstance(info, dict) and info.get("status") not in _QUOTA_OK:
                hits.append(f"rate_limit_event status {info.get('status')!r}")
            if ev.get("type") == "result" and ev.get("is_error") and _PAT.search(json.dumps(ev.get("result") or ev.get("error") or "")):
                hits.append("error result: " + json.dumps(ev.get("result") or ev.get("error"))[:200])
            if ev.get("type") == "system" and "error" in str(ev.get("subtype", "")) and _PAT.search(json.dumps(ev)):
                hits.append("system error event: " + json.dumps(ev)[:200])
    else:
        for ev in events:
            if ev.get("type") in ("error", "turn.failed", "stream_error") and _PAT.search(json.dumps(ev)):
                hits.append(f"{ev.get('type')}: " + json.dumps(ev)[:200])
    try:
        for line in (out_dir / "stderr.log").read_text(encoding="utf-8", errors="replace").splitlines():
            if _PAT.search(line):
                hits.append("stderr: " + line.strip()[:200])
    except OSError:
        pass
    return hits[:20]


def product_error_result(adapter: str, out_dir: Path) -> bool:
    events = _jsonl(Path(out_dir) / "transcript.jsonl")
    if adapter == "antigravity_cli":
        return any((ev.get("result") or {}).get("status") == "ERROR" for ev in events if ev.get("event") == "result")
    if adapter == "grok_build":
        return any(d.get("type") == "error" or d.get("stopReason") == "error" for ev in events for d in _walk(ev))
    if adapter == "claude_code_print":
        return any(ev.get("type") == "result" and ev.get("is_error") for ev in events)
    return any(ev.get("type") in ("error", "turn.failed") for ev in events)


# -------------------------------------------------------------------------------------------------------- planning --

@dataclass
class Bundle:
    sha256: str
    doc: dict[str, Any]
    products: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = BUNDLE) -> "Bundle":
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(_sha(Path(path)), doc, {p["name"]: p for p in doc["products"]})

    def slots(self) -> list[dict[str, Any]]:
        return sorted(self.doc["slots"], key=lambda s: s["order"])


def slot_key(s: dict[str, Any]) -> str:
    return f"{s['order']:02d}"


def run_id(s: dict[str, Any], adapter: str, attempt: int) -> str:
    return f"P1-{s['task']}-{adapter}-r{s['repetition']}" + ("" if attempt == 0 else f"-replacement{attempt}")


@dataclass
class SlotState:
    attempts: list[dict[str, Any]] = field(default_factory=list)      # slot_end events
    open_start: dict[str, Any] | None = None                           # slot_start without an end

    @property
    def resolved(self) -> bool:
        if not self.attempts:
            return False
        last = self.attempts[-1]
        return last["grader_outcome"] != "infrastructure" or len(self.attempts) >= 2


def state(events: list[dict[str, Any]]) -> dict[str, SlotState]:
    st: dict[str, SlotState] = {}
    for ev in events:
        if ev["event"] == "slot_start":
            st.setdefault(ev["slot"], SlotState()).open_start = ev
        elif ev["event"] == "slot_end":
            s = st.setdefault(ev["slot"], SlotState())
            s.attempts.append(ev)
            s.open_start = None
    return st


# ---------------------------------------------------------------------------------------------------------- driver --

class DeferredSignals:
    """Ctrl-C / SIGTERM / SIGHUP during a run: let the run finish, stop before the next slot."""

    def __init__(self, say: Callable[[str], None]):
        self.stop_requested, self.say, self._old = False, say, {}

    def __enter__(self) -> "DeferredSignals":
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self._old[sig] = signal.signal(sig, self._handle)
        return self

    def _handle(self, signum, frame) -> None:
        self.stop_requested = True
        self.say("stop requested: the current run finishes (at most 1,200 s), then the driver stops before the next slot")

    def __exit__(self, *exc: Any) -> None:
        for sig, h in self._old.items():
            signal.signal(sig, h)


class Wave:
    def __init__(self, dataset: Path, wave_dir: Path = WAVE_DIR, bundle_path: Path = BUNDLE, root: Path = PROJECT_ROOT,
                 run_slot: Callable[..., dict[str, Any]] | None = None, check_bundle: Callable[[], tuple[bool, Any]] | None = None,
                 executable_sha: Callable[[str], str] | None = None, sleep: Callable[[float], None] = time.sleep,
                 say: Callable[[str], None] = print, five_hour_gate: float = FIVE_HOUR_GATE, weekly_gate: float = WEEKLY_GATE,
                 task_root: Path = EXPORT, wave: str = "1"):
        from . import controller
        self.dataset, self.wave_dir, self.root, self.task_root = Path(dataset), Path(wave_dir), Path(root), Path(task_root)
        self.bundle_path = Path(bundle_path)
        self.ledger = Ledger(self.wave_dir / "ledger.jsonl")
        self.run_slot = run_slot or controller.run_slot
        self.check_bundle = check_bundle or self._check_bundle
        self.executable_sha = executable_sha or self._executable_sha
        self.sleep, self._say = sleep, say
        self.five_hour_gate, self.weekly_gate = five_hour_gate, weekly_gate
        self.wave = wave

    def say(self, msg: str) -> None:
        try:
            self._say(f"[{utc()}] {msg}")
        except OSError:                                  # a closed terminal must not break a running wave
            pass

    # -- binding --
    def _check_bundle(self) -> tuple[bool, Any]:
        from evaluation import run_bundle
        return run_bundle.check(self.root, self.dataset, self.wave)

    def _executable_sha(self, product: str) -> str:
        from . import controller
        spec = controller.config()["products"][product]
        return _sha(controller._abs(spec["binary"]).resolve())

    def verify_binding(self, bundle: Bundle) -> None:
        ok, detail = self.check_bundle()
        if not ok:
            raise WaveStop(f"the run bundle no longer certifies: {detail}")
        if _sha(self.bundle_path) != bundle.sha256:
            raise WaveStop("the run bundle changed while the wave was running")
        for name, p in bundle.products.items():
            if self.executable_sha(name) != p["observed"]["executable_sha256"]:
                raise WaveStop(f"{name}: the product executable changed (forced update?); stop and restart under a new bundle")

    def verify_record(self, bundle: Bundle, rec: dict[str, Any]) -> list[str]:
        p = bundle.products[rec["product_name"]]
        runner = {r["path"]: r["sha256"] for r in bundle.doc["runner"].values()}
        want_binding = {**runner, p["adapter_artifact"]["path"]: p["adapter_artifact"]["sha256"]}
        ident = rec.get("identity") or {}
        o = rec.get("observed") or {}
        models = set(o.get("models_in_session") or []) | set(o.get("models_in_transcript") or [])
        bad = []
        if rec.get("runner_binding") != want_binding:
            bad.append("runner files or adapter differ from the bundle")
        if rec.get("settings_snapshot_sha256") != p["settings"]["runtime_settings_snapshot_sha256"]:
            bad.append("runtime settings differ from the bundle")
        if ident.get("executable_sha256") != p["observed"]["executable_sha256"] or ident.get("version_command") != p["observed"]["product_version"]:
            bad.append("product executable or version differs from the bundle")
        allowed = {p["observed"]["model_display_name"], *(p["observed"].get("served_model_aliases") or [])}
        if models and not models <= allowed:
            bad.append(f"observed model {sorted(models)} is not {p['observed']['model_display_name']}")
        return bad

    # -- quota --
    def last_quota(self, events: list[dict[str, Any]], product: str) -> dict[str, Any] | None:
        for ev in reversed(events):
            if ev["event"] == "slot_end" and ev.get("product") == product and ev.get("quota"):
                return ev["quota"]
        return None

    def quota_wait_until(self, q: dict[str, Any] | None) -> tuple[float | None, str]:
        if not q:
            return None, "no observation yet"
        until, why = None, []
        if q.get("five_hour") is not None and q["five_hour"] >= self.five_hour_gate:
            until = q.get("five_hour_resets_at") or now() + DEFAULT_RETRY_WAIT_S
            why.append(f"five-hour {q['five_hour']:.0%} >= {self.five_hour_gate:.0%}")
        if q.get("weekly") is not None and q["weekly"] >= self.weekly_gate:
            w = q.get("weekly_resets_at") or now() + DEFAULT_RETRY_WAIT_S
            until = max(until or 0, w)
            why.append(f"weekly {q['weekly']:.0%} >= {self.weekly_gate:.0%}")
        if until is not None and until <= now():
            return None, "reset time passed"
        return until, "; ".join(why)

    # -- one wave session --
    def start(self, bundle: Bundle, accept_driver_change: str | None = None) -> list[dict[str, Any]]:
        events = self.ledger.events()
        starts = [e for e in events if e["event"] == "wave_start"]
        dsha = driver_sha256(self.root)
        current = [e["driver_sha256"] for e in events if e["event"] in ("wave_start", "driver_change")]
        if not starts:
            self.ledger.append("wave_start", bundle_sha256=bundle.sha256, driver_sha256=dsha, dataset=str(self.dataset),
                               slots=len(bundle.slots()), five_hour_gate=self.five_hour_gate, weekly_gate=self.weekly_gate)
        else:
            if starts[0]["bundle_sha256"] != bundle.sha256:
                raise WaveStop("this wave belongs to another run bundle; a new bundle needs a new wave (owner decision)")
            if current[-1] != dsha:
                if not (accept_driver_change or "").strip():
                    raise WaveStop("the wave driver changed since the wave started; the owner must accept the change "
                                   "(--accept-driver-change REASON)")
                self.ledger.append("driver_change", previous_driver_sha256=current[-1], driver_sha256=dsha,
                                   reason=accept_driver_change, five_hour_gate=self.five_hour_gate, weekly_gate=self.weekly_gate)
            self.ledger.append("wave_resume", bundle_sha256=bundle.sha256, driver_sha256=dsha)
        events = self.ledger.events()
        for key, s in state(events).items():                      # a run cut off by the host/driver: infrastructure
            if s.open_start is not None:
                ev = s.open_start
                self.ledger.append("slot_end", slot=key, product=ev["product"], task=ev["task"], repetition=ev["repetition"],
                                   attempt=ev["attempt"], run_id=ev["run_id"], dir=ev["dir"], controller_outcome=None,
                                   grader_outcome="infrastructure", reason="interrupted: the driver or host stopped during the run",
                                   needs_owner_review=True, quota=None, failed_at=ev["t"])
        return self.ledger.events()

    def next_action(self, bundle: Bundle, events: list[dict[str, Any]]) -> tuple[dict[str, Any], int, float] | None:
        """(slot, attempt number, earliest start epoch) for the next attempt in bundle order, or None when complete."""
        st = state(events)
        for s in bundle.slots():
            ss = st.get(slot_key(s), SlotState())
            if ss.resolved:
                continue
            attempt = len(ss.attempts)
            earliest = 0.0
            if attempt:
                last = ss.attempts[-1]
                earliest = max((last.get("failed_at") or last["t"]) + REPLACEMENT_DELAY_S, last.get("retry_not_before") or 0)
            return s, attempt, earliest
        return None

    def consecutive_infra(self, events: list[dict[str, Any]], product: str) -> int:
        """Consecutive infrastructure outcomes for a product since the owner last acknowledged a stop."""
        n = 0
        for ev in reversed(events):
            if ev["event"] == "owner_ack":
                break
            if ev["event"] != "slot_end" or ev.get("product") != product:
                continue
            if ev["grader_outcome"] != "infrastructure":
                break
            n += 1
        return n

    def acknowledge(self, reason: str) -> None:
        """The owner checked the cause of a stop (e.g. authentication restored) and lets the wave continue."""
        if not reason.strip():
            raise ValueError("an acknowledgement needs the owner's reason")
        self.ledger.append("owner_ack", reason=reason)

    def run(self, max_slots: int | None = None, wait: bool = True, accept_driver_change: str | None = None) -> str:
        self.wave_dir.mkdir(parents=True, exist_ok=True)
        lock = open(self.wave_dir / "driver.lock", "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise WaveStop("another wave driver is running on this wave (one driver at a time)")
        try:
            return self._run(max_slots, wait, accept_driver_change)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    def ensure_current(self, s: dict[str, Any]) -> None:
        """Right before a slot: this process must run the ledger's current driver, and nobody may have started the slot."""
        events = self.ledger.events()
        current = [e["driver_sha256"] for e in events if e["event"] in ("wave_start", "driver_change")]
        if current and current[-1] != driver_sha256(self.root):
            raise WaveStop("this driver is not the wave's current driver (a newer driver was accepted); this process stops")
        if state(events).get(slot_key(s), SlotState()).open_start is not None:
            raise WaveStop(f"slot {slot_key(s)} was started by another process; this process stops")

    def _run(self, max_slots: int | None, wait: bool, accept_driver_change: str | None) -> str:
        bundle = Bundle.load(self.bundle_path)
        self.verify_binding(bundle)
        events = self.start(bundle, accept_driver_change)
        done = 0
        with DeferredSignals(self.say) as sig:
            while True:
                if sig.stop_requested:
                    self.ledger.append("wave_pause", reason="operator stop request")
                    return "stopped"
                if max_slots is not None and done >= max_slots:
                    return "max_slots"
                events = self.ledger.events()
                nxt = self.next_action(bundle, events)
                if nxt is None:
                    if not any(e["event"] == "wave_complete" for e in events):
                        self.ledger.append("wave_complete", bundle_sha256=bundle.sha256)
                    self.say("wave complete: all 36 slots resolved")
                    return "complete"
                s, attempt, earliest = nxt
                product = s["product"]
                for name in bundle.products:
                    if self.consecutive_infra(events, name) >= 2:
                        raise WaveStop(f"{name}: two consecutive infrastructure outcomes; check authentication/service, then resume")
                q_until, q_why = self.quota_wait_until(self.last_quota(events, product))
                reasons = [q_why] if q_until else []
                if earliest > now():
                    reasons.append("replacement not before 30 minutes after the failure and the provider's reset")
                until = max(q_until or 0, earliest)
                if until > now():
                    why = "; ".join(reasons)
                    self.ledger.append("quota_wait", product=product, slot=slot_key(s), until_utc=utc(until), reason=why)
                    self.say(f"waiting for {product} until {utc(until)} ({why})")
                    if not wait:
                        return "waiting"
                    while now() < until and not sig.stop_requested:
                        self.sleep(min(WAIT_CHUNK_S, max(1.0, until - now())))
                    continue
                self.verify_binding(bundle)
                self.ensure_current(s)
                self.run_one(bundle, s, attempt)
                done += 1

    def run_one(self, bundle: Bundle, s: dict[str, Any], attempt: int) -> dict[str, Any]:
        p = bundle.products[s["product"]]
        adapter = p["adapter"]
        rid = run_id(s, adapter, attempt)
        out = self.wave_dir / "slots" / f"{slot_key(s)}-{rid}"
        meta = {"run_id": rid, "task_id": s["task"], "repetition": s["repetition"], "scheduled_position": s["order"],
                "block": s["block"], "prompt_arm": "baseline", "excluded_from_scoring": False, "replacement": attempt > 0,
                "bundle_sha256": bundle.sha256}
        start = self.ledger.append("slot_start", slot=slot_key(s), product=s["product"], task=s["task"], repetition=s["repetition"],
                                   attempt=attempt, run_id=rid, dir=str(out.relative_to(self.root)) if out.is_relative_to(self.root) else str(out))
        self.say(f"slot {s['order'] + 1}/36 {s['block']} {s['product']}" + (f" (replacement {attempt})" if attempt else "") + " started")
        end: dict[str, Any] = {"slot": slot_key(s), "product": s["product"], "task": s["task"], "repetition": s["repetition"],
                               "attempt": attempt, "run_id": rid, "dir": start["dir"]}
        try:
            rec = self.run_slot(s["product"], self.task_root / s["task"], out, meta)
        except Exception as exc:                                       # staging/canary/runner failure before or around the run
            canary = "canary" in str(exc)
            self.ledger.append("slot_end", **end, controller_outcome=None, grader_outcome="infrastructure",
                               reason=f"runner exception: {type(exc).__name__}: {str(exc)[:300]}", needs_owner_review=True,
                               quota=None, failed_at=now())
            if canary:
                raise WaveStop(f"isolation canary failed: {exc}") from exc
            self.say(f"slot {s['order'] + 1}/36 infrastructure: runner exception ({type(exc).__name__})")
            return {}
        q = quota_from_slot(adapter, out)
        drift = self.verify_record(bundle, rec)
        avail = structured_availability(adapter, out)
        complete = {"answer.json", "memo.md"} <= set(rec.get("output_hashes") or {})
        ctl = rec["outcome_status"]
        review = False
        if avail and (not complete or product_error_result(adapter, out)) and ctl != "timeout":
            outcome, reason = "infrastructure", "availability: " + "; ".join(avail[:3])
        else:
            outcome, reason = GRADER_OUTCOME[ctl], f"controller outcome {ctl}"
            if ctl == "availability_limit":
                review, reason = True, "pattern-only availability label without structured evidence; owner review"
            if avail:
                review, reason = True, reason + "; availability events seen but the run completed"
        slot_json = {"run_id": rid, "task_id": s["task"], "product": s["product"], "repetition": s["repetition"],
                     "outcome": outcome, "replacement": attempt > 0, "slot_order": s["order"], "block": s["block"],
                     "submission": "outputs", "run_record_sha256": _sha(out / "run_record.json")}
        (out / "slot.json").write_text(json.dumps(slot_json, indent=1) + "\n", encoding="utf-8")
        retry = None
        if outcome == "infrastructure" and avail:
            retry = availability_retry(q)
        self.ledger.append("slot_end", **end, controller_outcome=ctl, stop_reason=rec.get("stop_reason"), retry_not_before=retry,
                           elapsed_seconds=rec.get("elapsed_seconds"), grader_outcome=outcome, reason=reason,
                           needs_owner_review=review or bool(drift), availability=avail, quota=q, drift=drift,
                           run_record_sha256=slot_json["run_record_sha256"], failed_at=now() if outcome == "infrastructure" else None)
        qs = "" if not q else f"; quota five-hour {q.get('five_hour')}, weekly {q.get('weekly')}"
        self.say(f"slot {s['order'] + 1}/36 {s['block']} {s['product']}: {outcome} ({rec.get('stop_reason')}, "
                 f"{rec.get('elapsed_seconds')} s){qs}")
        if drift:
            raise WaveStop(f"{s['product']}: version/settings drift in slot {rid}: {drift}; this product stops (never pooled)")
        if (o := overage_signal(q)):
            raise WaveStop(f"{s['product']}: {o}; the $0 budget forbids continuing (ID-43)")
        return rec


def status(wave_dir: Path = WAVE_DIR, bundle_path: Path = BUNDLE) -> dict[str, Any]:
    """Progress without results: counts by grader outcome class are withheld; only resolved/pending and waits."""
    bundle = Bundle.load(bundle_path)
    events = Ledger(Path(wave_dir) / "ledger.jsonl").events()
    st = state(events)
    resolved = sum(1 for s in bundle.slots() if st.get(slot_key(s), SlotState()).resolved)
    infra = sum(1 for s in st.values() for a in s.attempts if a["grader_outcome"] == "infrastructure")
    waits = [e for e in events if e["event"] == "quota_wait"]
    return {"bundle_sha256": bundle.sha256, "slots": len(bundle.slots()), "resolved": resolved, "attempts": sum(len(s.attempts) for s in st.values()),
            "infrastructure_attempts": infra, "owner_review_flags": sum(1 for s in st.values() for a in s.attempts if a.get("needs_owner_review")),
            "last_wait": waits[-1] if waits else None,
            "complete": any(e["event"] == "wave_complete" for e in events)}
