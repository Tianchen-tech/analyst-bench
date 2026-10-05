"""Allowlist egress proxy for contestant runs (design 6.2 item 5: only model authentication/inference endpoints).

The contestant sandbox may open network connections ONLY to this proxy on 127.0.0.1. The proxy accepts HTTPS CONNECT
requests to allow-listed host:443 pairs (exact host or a '*.domain' suffix rule) and tunnels them; everything else
(other hosts, other ports, plain HTTP requests) is refused with 403 and logged. Every request, allowed or denied, is
appended to the run's egress log, which becomes part of the run record (external_access_attempts). DNS is resolved by
the proxy, never by the contestant.
"""

from __future__ import annotations

import json
import select
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Any


def host_allowed(host: str, port: int, allow: list[str]) -> bool:
    host = host.lower().rstrip(".")
    if port != 443:
        return False
    for rule in allow:
        rule = rule.lower()
        if rule.startswith("*.") and (host.endswith(rule[1:]) or host == rule[2:]):
            return True
        if host == rule:
            return True
    return False


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: "AllowlistProxy" = self.server.owner          # type: ignore[attr-defined]
        conn = self.request
        conn.settimeout(30)
        try:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 16384:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            line = head.split(b"\r\n", 1)[0].decode("latin-1")
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                srv.log("denied", line[:200], reason="not a CONNECT request")
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            target = parts[1]
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 0
            if not host_allowed(host, port, srv.allow):
                srv.log("denied", target, reason="host not on the allowlist")
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            upstream = socket.create_connection((host, port), timeout=30)
            srv.log("allowed", target)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            rest = head.split(b"\r\n\r\n", 1)[1]
            if rest:
                upstream.sendall(rest)
            conn.settimeout(None)
            upstream.settimeout(None)
            socks = [conn, upstream]
            while True:
                r, _, x = select.select(socks, [], socks, 300)
                if x or not r:
                    break
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is conn else conn).sendall(data)
        except (OSError, ValueError) as exc:
            srv.log("error", str(exc)[:200])
        finally:
            try:
                conn.close()
            except OSError:
                pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class AllowlistProxy:
    def __init__(self, allow: list[str], log_path: Path):
        self.allow, self.log_path = list(allow), Path(log_path)
        self._lock = threading.Lock()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.owner = self                           # type: ignore[attr-defined]
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def log(self, decision: str, target: str, **extra: Any) -> None:
        with self._lock, open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "decision": decision, "target": target, **extra}) + "\n")

    def __enter__(self) -> "AllowlistProxy":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()


def summarize(log_path: Path) -> dict[str, Any]:
    rows = [json.loads(l) for l in Path(log_path).read_text().splitlines()] if Path(log_path).exists() else []
    return {"allowed": sorted({r["target"] for r in rows if r["decision"] == "allowed"}),
            "denied": [r for r in rows if r["decision"] == "denied"], "errors": sum(r["decision"] == "error" for r in rows)}
