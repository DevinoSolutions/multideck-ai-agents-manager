import json
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch, MagicMock

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


class TestProjectFromTitle:
    def test_extracts_name(self):
        from multideck.hotkey import project_from_title, MD_TITLE_PREFIX
        assert project_from_title("md:marka") == "marka"
        assert project_from_title("md:upup") == "upup"

    def test_returns_none_for_non_md(self):
        from multideck.hotkey import project_from_title
        assert project_from_title("Windows Terminal") is None
        assert project_from_title("claude") is None
        assert project_from_title("") is None

    def test_prefix_value(self):
        from multideck.hotkey import MD_TITLE_PREFIX
        assert MD_TITLE_PREFIX == "md:"


class TestUploadImage:
    @pytest.fixture(autouse=True)
    def _server(self):
        self.last_request = {}

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                parent.last_request = {
                    "path": self.path,
                    "body": body,
                    "content_type": self.headers.get("Content-Type", ""),
                }
                resp = json.dumps({"ok": True, "injected": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()

    def test_uploads_image(self):
        from multideck.hotkey import upload_image
        url = f"http://127.0.0.1:{self.port}"
        result = upload_image(url, "marka", b"FAKEBMP")
        assert result is True
        assert self.last_request["path"] == "/upload"
        assert b"marka" in self.last_request["body"]
        assert b"FAKEBMP" in self.last_request["body"]
        assert "multipart/form-data" in self.last_request["content_type"]

    def test_returns_false_on_network_error(self):
        from multideck.hotkey import upload_image
        result = upload_image("http://127.0.0.1:1", "marka", b"data")
        assert result is False


class TestHookStructsAndConstants:
    def test_kbdllhookstruct_size(self):
        from multideck.hotkey import KBDLLHOOKSTRUCT
        import ctypes
        size = ctypes.sizeof(KBDLLHOOKSTRUCT)
        assert size > 0

    def test_constants(self):
        from multideck.hotkey import VK_V, VK_MENU, CF_DIB, WH_KEYBOARD_LL
        assert VK_V == 0x56
        assert VK_MENU == 0x12
        assert CF_DIB == 8
        assert WH_KEYBOARD_LL == 13

    def test_hookproc_type(self):
        from multideck.hotkey import HOOKPROC
        assert HOOKPROC is not None
