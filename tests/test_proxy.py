"""The egress allowlist proxy (runners/proxy.py): host rules, the TLS server-name check and tunnel accounting."""

from __future__ import annotations

import json
import socket
import ssl
import threading
from pathlib import Path

import pytest

from runners import proxy as px


def client_hello(server_hostname: str | None) -> bytes:
    """A real ClientHello from the local TLS library (with post-quantum key shares where supported, about 1.5 KB)."""
    ctx = ssl.create_default_context()
    if server_hostname is None:
        ctx.check_hostname = False
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ctx.wrap_bio(incoming, outgoing, server_hostname=server_hostname)
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()
    return outgoing.read()


def body(hello: bytes) -> bytes:
    """The ClientHello message body inside a single-record hello."""
    return hello[5 + 4:]


@pytest.mark.parametrize("host, port, allowed", [
    ("api.anthropic.com", 443, True), ("API.Anthropic.com.", 443, True), ("api.anthropic.com", 80, False),
    ("evil-api.anthropic.com", 443, False), ("x.oaiusercontent.com", 443, True), ("oaiusercontent.com", 443, True),
    ("oaiusercontent.com.evil.net", 443, False),
])
def test_host_allowed(host: str, port: int, allowed: bool):
    assert px.host_allowed(host, port, ["api.anthropic.com", "*.oaiusercontent.com"]) is allowed


def test_server_name_of_real_client_hellos():
    assert px.server_name(body(client_hello("api.anthropic.com"))) == ("api.anthropic.com", False)
    assert px.server_name(body(client_hello(None))) == (None, False)


def test_server_name_rejects_a_truncated_hello():
    with pytest.raises(px.HelloError):
        px.server_name(body(client_hello("api.anthropic.com"))[:60])


def test_read_client_hello_across_small_segments_keeps_every_byte():
    hello = client_hello("api.anthropic.com")
    a, b = socket.socketpair()
    with a, b:
        for i in range(0, len(hello), 100):
            a.sendall(hello[i:i + 100])
        a.sendall(b"early data")
        data, message = px.read_client_hello(b, b"")
    assert data.startswith(hello) and message == body(hello)


def test_read_client_hello_refuses_other_protocols_and_early_close():
    a, b = socket.socketpair()
    with a, b:
        a.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        with pytest.raises(px.HelloError, match="not a TLS handshake record"):
            px.read_client_hello(b)
    a, b = socket.socketpair()
    with a, b:
        a.sendall(client_hello("api.anthropic.com")[:200])
        a.shutdown(socket.SHUT_WR)
        with pytest.raises(px.HelloError, match="closed before a complete ClientHello"):
            px.read_client_hello(b)
    a, b = socket.socketpair()
    with a, b:
        a.shutdown(socket.SHUT_WR)
        with pytest.raises(ConnectionAbortedError):
            px.read_client_hello(b)


# ------------------------------------------------------------------------------------------- live proxy runs --

class Upstream:
    """A local stand-in for an inference host: reads the client's first `expect` bytes, answers PONG and closes."""

    def __init__(self, expect: int):
        self.expect, self.received, self.connections = expect, b"", 0
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.05)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.connections += 1
            with conn:
                conn.settimeout(3)
                while len(self.received) < self.expect:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    self.received += chunk
                conn.sendall(b"PONG")
            return

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        self.sock.close()


@pytest.fixture
def live(tmp_path: Path, monkeypatch):
    """A running proxy that also allows localhost on the upstream stand-in's port (the real rule allows only 443)."""
    def start(expect: int):
        upstream = Upstream(expect)
        real = px.host_allowed
        monkeypatch.setattr(px, "host_allowed", lambda h, p, allow: (h == "localhost" and p == upstream.port) or real(h, p, allow))
        log = tmp_path / "egress.jsonl"
        proxy = px.AllowlistProxy(["api.anthropic.com"], log)
        proxy.__enter__()
        started.append((proxy, upstream))
        return proxy, upstream, log
    started: list = []
    yield start
    for proxy, upstream in started:
        proxy.__exit__(None, None, None)
        upstream.close()


def connect(proxy: px.AllowlistProxy, request: bytes) -> tuple[socket.socket, bytes]:
    c = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    c.sendall(request)
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = c.recv(4096)
        if not chunk:
            break
        head += chunk
    return c, head


def read_all(c: socket.socket) -> bytes:
    out = b""
    while True:
        try:
            chunk = c.recv(4096)
        except (ConnectionResetError, TimeoutError):
            break
        if not chunk:
            break
        out += chunk
    return out


def events(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def wait_for(log: Path, decision: str) -> list[dict]:
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = [e for e in events(log) if e["decision"] == decision] if log.exists() else []
        if found:
            return found
        time.sleep(0.02)
    return []


def test_a_tunnel_with_the_matching_server_name_is_relayed_and_counted(live):
    hello = client_hello("localhost")
    proxy, upstream, log = live(len(hello))
    c, head = connect(proxy, f"CONNECT localhost:{upstream.port} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    with c:
        assert head.startswith(b"HTTP/1.1 200")
        c.sendall(hello)
        assert read_all(c) == b"PONG"
    closed = wait_for(log, "closed")
    assert upstream.received == hello
    assert [e["sni"] for e in events(log) if e["decision"] == "allowed"] == ["localhost"]
    assert (closed[0]["bytes_up"], closed[0]["bytes_down"]) == (len(hello), 4)
    summary = px.summarize(log)
    assert summary["allowed"] == [f"localhost:{upstream.port}"] and summary["denied"] == []
    assert (summary["bytes_up"], summary["bytes_down"]) == (len(hello), 4)


@pytest.mark.parametrize("sni, reason", [("evil.example", "does not match the CONNECT host"),
                                         (None, "does not match the CONNECT host")])
def test_a_different_or_missing_server_name_is_refused_before_any_upstream_connection(live, sni, reason):
    proxy, upstream, log = live(1)
    c, head = connect(proxy, f"CONNECT localhost:{upstream.port} HTTP/1.1\r\n\r\n".encode())
    with c:
        assert head.startswith(b"HTTP/1.1 200")
        c.sendall(client_hello(sni))
        assert read_all(c) == b""
    denied = wait_for(log, "denied")
    assert reason in denied[0]["reason"] and denied[0]["sni"] == sni
    assert upstream.connections == 0


def test_non_tls_bytes_in_the_tunnel_are_refused(live):
    proxy, upstream, log = live(1)
    c, _ = connect(proxy, f"CONNECT localhost:{upstream.port} HTTP/1.1\r\n\r\n".encode())
    with c:
        c.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert read_all(c) == b""
    assert "not a TLS handshake record" in wait_for(log, "denied")[0]["reason"]
    assert upstream.connections == 0


@pytest.mark.parametrize("request_line, reason", [
    (b"GET http://example.com/ HTTP/1.1\r\n\r\n", "not a CONNECT request"),
    (b"CONNECT example.com:443 HTTP/1.1\r\n\r\n", "host not on the allowlist"),
    (b"CONNECT api.anthropic.com:80 HTTP/1.1\r\n\r\n", "host not on the allowlist"),
])
def test_requests_outside_the_allowlist_get_403(live, request_line, reason):
    proxy, _, log = live(1)
    c, head = connect(proxy, request_line)
    with c:
        assert head.startswith(b"HTTP/1.1 403")
    assert wait_for(log, "denied")[0]["reason"] == reason


def test_an_overlong_request_head_is_refused_without_an_error(live):
    proxy, upstream, log = live(1)
    head = f"CONNECT localhost:{upstream.port} HTTP/1.1\r\nX-Pad: ".encode()
    head += b"a" * (px.MAX_HEAD - len(head))            # exactly the limit, never terminated: the proxy reads it all
    c = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    with c:
        c.sendall(head)
        assert read_all(c).startswith(b"HTTP/1.1 403")
    denied = wait_for(log, "denied")
    assert "incomplete or longer than" in denied[0]["reason"]
    assert not [e for e in events(log) if e["decision"] == "error"]
