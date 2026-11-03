"""Allowlist egress proxy for contestant runs (design 6.2 item 5: only model authentication/inference endpoints).

The contestant sandbox may open network connections ONLY to this proxy on 127.0.0.1. The proxy accepts HTTPS CONNECT
requests to allow-listed host:443 pairs (exact host or a '*.domain' suffix rule); everything else (other hosts, other
ports, plain HTTP requests) is refused with 403 and logged. DNS is resolved by the proxy, never by the contestant.

After an accepted CONNECT, the first bytes in the tunnel must be a TLS ClientHello whose server name (SNI) is the
CONNECT host. Otherwise a tunnel to an allowed host could carry a handshake for another site served by the same CDN or
load balancer. A ClientHello without a server name, or with an encrypted ClientHello extension (ECH, which hides the
real server name), is refused too. The proxy does not decrypt traffic: a CDN that honoured an HTTP Host header that
differs from the SNI ("domain fronting") is outside what it can check.

Every request, allowed or denied, is appended to the run's egress log, which becomes part of the run record
(external_access_attempts). Each tunnel also logs its byte counts when it closes.
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

MAX_HEAD = 16 * 1024                 # CONNECT request head
MAX_HELLO = 64 * 1024                # bytes read while waiting for a complete ClientHello
TLS_HANDSHAKE, CLIENT_HELLO = 22, 1
EXT_SERVER_NAME, EXT_ECH = 0x0000, 0xFE0D


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


class HelloError(ValueError):
    """The tunnel did not start with a complete, well-formed TLS ClientHello."""


def read_client_hello(conn: socket.socket, data: bytes = b"") -> tuple[bytes, bytes]:
    """Read from `conn` (after any bytes already in `data`) until a complete ClientHello has arrived. Returns (every byte
    read so far, to be forwarded unchanged; the ClientHello message body). The message may span several records and
    TCP segments."""
    handshake, pos = b"", 0
    while True:
        while len(data) - pos >= 5:
            if data[pos] != TLS_HANDSHAKE or data[pos + 1] != 3:
                raise HelloError("not a TLS handshake record")
            length = int.from_bytes(data[pos + 3:pos + 5], "big")
            if len(data) - pos - 5 < length:
                break
            handshake += data[pos + 5:pos + 5 + length]
            pos += 5 + length
            if len(handshake) >= 4:
                if handshake[0] != CLIENT_HELLO:
                    raise HelloError("the first handshake message is not a ClientHello")
                end = 4 + int.from_bytes(handshake[1:4], "big")
                if len(handshake) >= end:
                    return data, handshake[4:end]
        if len(data) > MAX_HELLO:
            raise HelloError(f"no complete ClientHello within {MAX_HELLO} bytes")
        chunk = conn.recv(16384)
        if not chunk:
            if not data:
                raise ConnectionAbortedError("the tunnel closed before TLS started")
            raise HelloError("the connection closed before a complete ClientHello")
        data += chunk


def server_name(hello: bytes) -> tuple[str | None, bool]:
    """(the ClientHello's SNI host name or None, whether it carries an encrypted ClientHello extension)."""
    def take(n: int) -> bytes:
        nonlocal p
        if p + n > len(hello):
            raise HelloError("truncated ClientHello")
        out, p = hello[p:p + n], p + n
        return out

    p = 0
    take(2 + 32)                                                    # legacy_version, random
    take(take(1)[0])                                                # legacy_session_id
    take(int.from_bytes(take(2), "big"))                            # cipher_suites
    take(take(1)[0])                                                # legacy_compression_methods
    if p == len(hello):
        return None, False                                          # no extensions at all
    extensions = take(int.from_bytes(take(2), "big"))
    name, ech, seen = None, False, set()
    q = 0
    while q < len(extensions):
        if q + 4 > len(extensions):
            raise HelloError("truncated extension header")
        etype, elen = int.from_bytes(extensions[q:q + 2], "big"), int.from_bytes(extensions[q + 2:q + 4], "big")
        body = extensions[q + 4:q + 4 + elen]
        if len(body) != elen or etype in seen:
            raise HelloError("truncated or repeated extension")
        seen.add(etype)
        if etype == EXT_ECH:
            ech = True
        elif etype == EXT_SERVER_NAME:
            r = 2                                                   # server_name_list length
            while r + 3 <= len(body):
                kind, nlen = body[r], int.from_bytes(body[r + 1:r + 3], "big")
                if kind == 0:                                       # host_name
                    try:
                        name = body[r + 3:r + 3 + nlen].decode("ascii")
                    except UnicodeDecodeError as exc:
                        raise HelloError("server name is not ASCII") from exc
                    break
                r += 3 + nlen
        q += 4 + elen
    return name, ech


def _same_host(a: str, b: str) -> bool:
    return a.lower().rstrip(".") == b.lower().rstrip(".")


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: "AllowlistProxy" = self.server.owner          # type: ignore[attr-defined]
        conn = self.request
        conn.settimeout(30)
        upstream: socket.socket | None = None
        target, up, down = "", 0, 0
        try:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < MAX_HEAD:
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
            if b"\r\n\r\n" not in head:
                srv.log("denied", target[:200], reason=f"CONNECT request head incomplete or longer than {MAX_HEAD} bytes")
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 0
            if not host_allowed(host, port, srv.allow):
                srv.log("denied", target, reason="host not on the allowlist")
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            try:
                data, hello = read_client_hello(conn, head.split(b"\r\n\r\n", 1)[1])
                sni, ech = server_name(hello)
            except HelloError as exc:
                srv.log("denied", target, reason=f"tunnel did not start with a valid TLS ClientHello: {exc}")
                return
            if ech:
                srv.log("denied", target, reason="encrypted ClientHello (ECH) hides the server name", sni=sni)
                return
            if sni is None or not _same_host(sni, host):
                srv.log("denied", target, reason="TLS server name (SNI) does not match the CONNECT host", sni=sni)
                return
            upstream = socket.create_connection((host, port), timeout=30)
            srv.log("allowed", target, sni=sni)
            upstream.sendall(data)
            up += len(data)
            conn.settimeout(None)
            upstream.settimeout(None)
            socks = [conn, upstream]
            while True:
                r, _, x = select.select(socks, [], socks, 300)
                if x or not r:
                    break
                for s in r:
                    chunk = s.recv(65536)
                    if not chunk:
                        return
                    if s is conn:
                        upstream.sendall(chunk)
                        up += len(chunk)
                    else:
                        conn.sendall(chunk)
                        down += len(chunk)
        except (OSError, ValueError) as exc:
            srv.log("error", str(exc)[:200], **({"connect_target": target} if target else {}))
        finally:
            if upstream is not None:
                srv.log("closed", target, bytes_up=up, bytes_down=down)
                try:
                    upstream.close()
                except OSError:
                    pass
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
    closed = [r for r in rows if r["decision"] == "closed"]
    return {"allowed": sorted({r["target"] for r in rows if r["decision"] == "allowed"}),
            "denied": [r for r in rows if r["decision"] == "denied"], "errors": sum(r["decision"] == "error" for r in rows),
            "bytes_up": sum(r.get("bytes_up", 0) for r in closed), "bytes_down": sum(r.get("bytes_down", 0) for r in closed)}
