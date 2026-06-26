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


class TestDibToBmp:
    """Clipboard DIB -> BMP conversion (the all-black image bug)."""

    @staticmethod
    def _header(width, height, bpp, compression):
        import struct
        return struct.pack(
            "<IiiHHIIiiII",
            40,            # biSize (BITMAPINFOHEADER)
            width, height,
            1,             # planes
            bpp,
            compression,
            0, 0, 0, 0, 0,  # sizeImage, x/y ppm, clrUsed, clrImportant
        )

    def test_bitfields_offset_skips_masks(self):
        # 32bpp BI_BITFIELDS (what GDI / .NET / screenshots produce): 3 color
        # masks sit between the 40-byte header and the pixels.
        import struct
        from multideck.hotkey import _dib_to_bmp
        header = self._header(2, 2, 32, 3)
        masks = struct.pack("<III", 0x00FF0000, 0x0000FF00, 0x000000FF)
        pixels = bytes([0, 0, 255, 0] * 4)  # opaque-red BGR with alpha=0
        bmp = _dib_to_bmp(bytearray(header + masks + pixels))

        assert bmp[:2] == b"BM"
        bf_off_bits = struct.unpack_from("<I", bmp, 10)[0]
        assert bf_off_bits == 14 + 40 + 12  # past header AND the 12 mask bytes
        # alpha forced opaque so decoders don't render it transparent/black
        for i in range(bf_off_bits + 3, len(bmp), 4):
            assert bmp[i] == 0xFF

    def test_rgb32_forces_alpha_opaque(self):
        import struct
        from multideck.hotkey import _dib_to_bmp
        header = self._header(2, 2, 32, 0)  # BI_RGB, no masks
        pixels = bytes([10, 20, 30, 0] * 4)  # alpha = 0 (transparent -> black)
        bmp = _dib_to_bmp(bytearray(header + pixels))

        bf_off_bits = struct.unpack_from("<I", bmp, 10)[0]
        assert bf_off_bits == 14 + 40  # no masks for BI_RGB
        for i in range(bf_off_bits + 3, len(bmp), 4):
            assert bmp[i] == 0xFF

    def test_rgb24_untouched(self):
        import struct
        from multideck.hotkey import _dib_to_bmp
        header = self._header(2, 2, 24, 0)
        pixels = bytes([1, 2, 3] * 4)
        bmp = _dib_to_bmp(bytearray(header + pixels))
        bf_off_bits = struct.unpack_from("<I", bmp, 10)[0]
        assert bf_off_bits == 14 + 40
        assert bmp[14 + 40:] == pixels  # 24bpp pixels passed through verbatim

    def test_too_small_returns_none(self):
        from multideck.hotkey import _dib_to_bmp
        assert _dib_to_bmp(bytearray(b"\x00" * 10)) is None


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
