import io
import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import pytest

from multideck.upload_server import (
    UploadHandler,
    _build_html,
    _parse_multipart,
    run_server,
    _UPLOAD_DIR,
)


class TestBuildHtml:
    def test_renders_sessions(self):
        sessions = [
            {"name": "marka", "path": "INTERNAL/marka"},
            {"name": "upup", "path": "INTERNAL/upup"},
        ]
        html = _build_html(sessions)
        assert "marka" in html
        assert "upup" in html
        assert "pill" in html

    def test_no_sessions_shows_message(self):
        html = _build_html([])
        assert "no active sessions" in html

    def test_html_escapes_names(self):
        sessions = [{"name": "<b>bad</b>", "path": "x&y"}]
        html = _build_html(sessions)
        assert "<b>bad</b>" not in html
        assert "&lt;b&gt;bad&lt;/b&gt;" in html


class TestParseMultipart:
    def _make_handler(self, body: bytes, boundary: str):
        class FakeHandler:
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            }
            rfile = io.BytesIO(body)
        return FakeHandler()

    def test_parses_field_and_file(self):
        boundary = "----TestBoundary"
        body = (
            f"------TestBoundary\r\n"
            f'Content-Disposition: form-data; name="project"\r\n'
            f"\r\n"
            f"marka\r\n"
            f"------TestBoundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="test.png"\r\n'
            f"Content-Type: image/png\r\n"
            f"\r\n"
            f"PNGDATA\r\n"
            f"------TestBoundary--\r\n"
        ).encode()

        handler = self._make_handler(body, "----TestBoundary")
        fields, files = _parse_multipart(handler)

        assert fields["project"] == "marka"
        assert "file" in files
        assert files["file"][0] == "test.png"
        assert files["file"][1] == b"PNGDATA"


class TestUploadServerIntegration:
    @pytest.fixture(autouse=True)
    def _server(self, tmp_path, monkeypatch):
        import multideck.upload_server as mod
        monkeypatch.setattr(mod, "_UPLOAD_DIR", tmp_path / "uploads")
        self.upload_dir = tmp_path / "uploads"

        UploadHandler.config_path = None
        UploadHandler.cached_sessions = [
            {"name": "marka", "path": "INTERNAL/marka"},
            {"name": "upup", "path": "INTERNAL/upup"},
        ]
        UploadHandler.sessions_ts = time.time() + 9999

        from http.server import HTTPServer
        self.server = HTTPServer(("127.0.0.1", 0), UploadHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        yield
        self.server.shutdown()

    def _conn(self):
        return HTTPConnection("127.0.0.1", self.port, timeout=5)

    def test_get_index(self):
        conn = self._conn()
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode()
        assert "marka" in body
        assert "upup" in body

    def test_get_api_sessions(self):
        conn = self._conn()
        conn.request("GET", "/api/sessions")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert len(data) == 2
        assert data[0]["name"] == "marka"

    def test_upload_saves_file(self):
        boundary = "----WebKitFormBoundary"
        body = (
            f"------WebKitFormBoundary\r\n"
            f'Content-Disposition: form-data; name="project"\r\n'
            f"\r\n"
            f"marka\r\n"
            f"------WebKitFormBoundary\r\n"
            f'Content-Disposition: form-data; name="inject"\r\n'
            f"\r\n"
            f"0\r\n"
            f"------WebKitFormBoundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="screenshot.png"\r\n'
            f"Content-Type: image/png\r\n"
            f"\r\n"
            f"FAKEPNG\r\n"
            f"------WebKitFormBoundary--\r\n"
        ).encode()

        conn = self._conn()
        conn.request("POST", "/upload", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())

        assert data["ok"] is True
        assert "screenshot.png" in data["path"]
        assert not data["injected"]
        saved = Path(data["path"])
        assert saved.exists()
        assert saved.read_bytes() == b"FAKEPNG"

    def test_upload_missing_project(self):
        boundary = "----Boundary"
        body = (
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="x.png"\r\n'
            f"\r\n"
            f"data\r\n"
            f"------Boundary--\r\n"
        ).encode()

        conn = self._conn()
        conn.request("POST", "/upload", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary=----Boundary",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert data["ok"] is False

    def test_upload_rejects_unknown_project(self):
        boundary = "----Boundary"
        body = (
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="project"\r\n'
            f"\r\n"
            f"evil-project\r\n"
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="x.png"\r\n'
            f"\r\n"
            f"data\r\n"
            f"------Boundary--\r\n"
        ).encode()

        conn = self._conn()
        conn.request("POST", "/upload", body=body, headers={
            "Content-Type": "multipart/form-data; boundary=----Boundary",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert data["ok"] is False
        assert "Unknown project" in data["error"]

    def test_upload_strips_path_traversal(self):
        boundary = "----Boundary"
        body = (
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="project"\r\n'
            f"\r\n"
            f"marka\r\n"
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="inject"\r\n'
            f"\r\n"
            f"0\r\n"
            f"------Boundary\r\n"
            f'Content-Disposition: form-data; name="file"; filename="../../etc/passwd"\r\n'
            f"\r\n"
            f"malicious\r\n"
            f"------Boundary--\r\n"
        ).encode()

        conn = self._conn()
        conn.request("POST", "/upload", body=body, headers={
            "Content-Type": "multipart/form-data; boundary=----Boundary",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        data = json.loads(resp.read())
        assert data["ok"] is True
        saved = Path(data["path"])
        assert saved.parent == self.upload_dir
        assert ".." not in saved.name

    def test_404(self):
        conn = self._conn()
        conn.request("GET", "/nonexistent")
        resp = conn.getresponse()
        assert resp.status == 404
