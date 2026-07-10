"""REAL upload server on the wire: `python -m multideck serve` as a separate
OS process bound to a real loopback socket, exercised with real HTTP requests
from ``http.client`` -- the exact experience a phone (or the Alt+V listener)
gets, including the P4-02 drain-before-error behavior shipped in PR #44.

What each test proves (no fakes inside multideck, no monkeypatching):

* healthy path (needs psmux): `multideck up` creates a REAL detached psmux
  session for the configured project; a real multipart POST /upload then lands
  a real file under the (redirected) ``~/.multideck/uploads`` and injects the
  path into that live session (``injected: true``);
* a body larger than MAX_UPLOAD_BYTES with an honest Content-Length receives a
  REAL ``413`` + ``{"ok": false, ...}`` JSON envelope on the same connection --
  the drained-not-reset behavior P4-02 exists to guarantee on Windows;
* a garbage (unparseable) Content-Length receives the real ``400`` envelope.

Isolation: the serve/up child processes run with HOME/USERPROFILE redirected
into tmp_path (pid file, uploads dir, logs -- all land there); the config is a
tmp file; the psmux session name is uuid-unique and every psmux interaction
(create, verify, kill) runs with the same redirected env so cleanup targets
exactly the session this test created. The server binds 127.0.0.1 only.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import pytest

from multideck.psmux import find_psmux

pytestmark = pytest.mark.e2e


def _child_env(home) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.upper().startswith("MULTIDECK_")
    }
    home_s = str(home)
    drive, tail = os.path.splitdrive(home_s)
    env["USERPROFILE"] = home_s
    env["HOMEDRIVE"] = drive
    env["HOMEPATH"] = tail or "\\"
    env["HOME"] = home_s
    return env


def _wait_until(check, timeout: float, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _health_ok(port: int) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/health")
            resp = conn.getresponse()
            body = resp.read()
            return resp.status == 200 and json.loads(body).get("ok") is True
        finally:
            conn.close()
    except (OSError, ValueError):
        return False


class _Serve:
    """One real `multideck serve` process plus everything needed to talk to
    it and to clean it (and only it) up afterwards."""

    def __init__(self, tmp_path):
        self.unique = uuid.uuid4().hex[:10]
        self.title = f"mdrl-up-{self.unique}"  # also the psmux session name
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.proj = tmp_path / f"proj-{self.unique}"
        self.proj.mkdir()
        self.env = _child_env(self.home)
        self.port = _free_port()
        self.cfg = tmp_path / "multideck.config.json"
        self.cfg.write_text(
            json.dumps(
                {
                    "version": 3,
                    "projects": [
                        {"path": str(self.proj), "title": self.title, "tool": "probe"}
                    ],
                    "settings": {
                        "defaultTool": "probe",
                        "tools": {"probe": f"rem mdrl-upload-{self.unique}"},
                        "uploadServer": False,
                        "attention": {
                            "badge": False,
                            "flash": False,
                            "toast": False,
                            "ntfy": False,
                        },
                    },
                }
            )
        )
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "multideck",
                "--config",
                str(self.cfg),
                "serve",
                "-p",
                str(self.port),
                "--host",
                "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )

    def wait_ready(self) -> None:
        if not _wait_until(lambda: _health_ok(self.port), timeout=30):
            self.proc.kill()
            stdout, stderr = self.proc.communicate(timeout=30)
            pytest.fail(
                f"serve never became healthy on 127.0.0.1:{self.port}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )

    def connect(self, timeout: float = 60) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)

    def psmux_run(self, *args: str) -> subprocess.CompletedProcess:
        """Run a psmux command under the SAME redirected env as the server, so
        both sides resolve the same session namespace."""
        binary = find_psmux()
        assert binary, "caller must guard on psmux presence"
        return subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=self.env,
        )

    def teardown(self) -> list[str]:
        """Kill exactly what this test created; return anything left alive."""
        leftovers: list[str] = []
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            leftovers.append(f"serve process pid={self.proc.pid} did not exit")
        if find_psmux():
            self.psmux_run("-L", self.title, "kill-server")
            if self.psmux_run("-L", self.title, "has-session").returncode == 0:
                leftovers.append(f"psmux session {self.title}")
        # The real socket must actually be gone, not just the process object.
        _wait_until(lambda: not _health_ok(self.port), timeout=10)
        if _health_ok(self.port):
            leftovers.append(f"port {self.port} still serving")
        return leftovers


@pytest.fixture
def serve(tmp_path):
    srv = _Serve(tmp_path)
    srv.wait_ready()
    yield srv
    leftovers = srv.teardown()
    assert not leftovers, f"cleanup left real resources behind: {leftovers}"


def _multipart(fields: dict[str, str], filename: str, payload: bytes):
    boundary = f"mdrlboundary{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            f"\r\n\r\n{value}\r\n"
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    )
    body = "".join(parts).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def test_healthy_upload_lands_real_file_and_injects_into_live_session(serve):
    if find_psmux() is None:
        pytest.skip("psmux not installed")

    # Bring the project's psmux session up the real user way: `multideck up`.
    r = subprocess.run(
        [sys.executable, "-m", "multideck", "--config", str(serve.cfg), "up"],
        capture_output=True,
        text=True,
        timeout=120,
        env=serve.env,
    )
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert _wait_until(
        lambda: serve.psmux_run("-L", serve.title, "has-session").returncode == 0,
        timeout=15,
    ), f"psmux session {serve.title!r} never came up after `multideck up`"

    payload = b"multideck-real-e2e \x00\x01\x02 " + serve.unique.encode()
    body, content_type = _multipart(
        {"project": serve.title, "inject": "1"},
        filename="mdrl_probe_upload",  # extensionless: injected path is inert text
        payload=payload,
    )
    conn = serve.connect()
    try:
        conn.request(
            "POST",
            "/upload",
            body=body,
            headers={"Content-Type": content_type},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read())
    finally:
        conn.close()

    assert resp.status == 200
    assert data["ok"] is True
    assert data["injected"] is True, "path was not injected into the live session"
    dest = data["path"]
    uploads_dir = (serve.home / ".multideck" / "uploads").resolve()
    assert str(uploads_dir).casefold() in str(dest).casefold(), (
        f"file landed outside the redirected uploads dir: {dest}"
    )
    with open(dest, "rb") as f:
        assert f.read() == payload, "uploaded bytes differ on disk"


def test_oversized_body_gets_real_413_envelope_not_a_reset(serve):
    from multideck.upload_server import MAX_UPLOAD_BYTES

    body = b"x" * (MAX_UPLOAD_BYTES + 1)  # honest Content-Length, really sent
    conn = serve.connect(timeout=120)
    try:
        conn.request(
            "POST",
            "/upload",
            body=body,
            headers={"Content-Type": "application/octet-stream"},
        )
        # P4-02's promise: the server drains the body and the JSON envelope
        # arrives on this same connection -- not a TCP reset.
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()

    assert resp.status == 413
    assert json.loads(raw) == {"ok": False, "error": "File too large"}


def test_garbage_content_length_gets_real_400_envelope(serve):
    conn = serve.connect(timeout=60)
    try:
        conn.putrequest("POST", "/upload")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", "not-a-number")
        conn.endheaders()
        conn.send(b"some junk bytes")
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()

    assert resp.status == 400
    assert json.loads(raw) == {"ok": False, "error": "Bad Content-Length"}
