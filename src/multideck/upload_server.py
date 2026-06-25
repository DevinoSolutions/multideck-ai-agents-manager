"""Tiny upload server for mobile image transfer to psmux sessions."""
from __future__ import annotations

import html
import json
import re
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from multideck.platform import find_psmux


_UPLOAD_DIR = Path.home() / ".multideck" / "uploads"

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>md</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,system-ui,sans-serif;background:#1e1e2e;color:#cdd6f4;
  padding:12px;-webkit-tap-highlight-color:transparent}
.head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.head h1{font-size:.85rem;color:#a6e3a1;font-weight:700;letter-spacing:.5px}
.head span{color:#45475a;font-size:.7rem}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
.pill{background:#313244;border:1.5px solid #45475a;border-radius:20px;
  padding:6px 14px;font-size:.8rem;color:#bac2de;cursor:pointer;
  transition:all .12s;white-space:nowrap;-webkit-user-select:none;user-select:none}
.pill:active{transform:scale(.96)}
.pill.on{border-color:#89b4fa;background:#1e3a5f;color:#89b4fa;font-weight:600}
.drop{border:1.5px dashed #45475a;border-radius:10px;padding:18px 12px;
  text-align:center;color:#585b70;font-size:.8rem;position:relative;
  transition:all .15s;margin-bottom:8px}
.drop.ready{border-color:#89b4fa;color:#89b4fa;border-style:solid}
.drop.busy{border-color:#f9e2af;color:#f9e2af}
.drop.ok{border-color:#a6e3a1;color:#a6e3a1}
.drop.err{border-color:#f38ba8;color:#f38ba8}
.drop input{position:absolute;inset:0;opacity:0;cursor:pointer;font-size:0}
.toast{font-size:.75rem;color:#6c7086;text-align:center;min-height:1.1em;
  transition:color .2s}
.toast.ok{color:#a6e3a1}
.toast.err{color:#f38ba8}
.none{color:#f38ba8;font-size:.8rem;padding:12px 0}
</style>
</head>
<body>
<div class="head">
  <h1>MD</h1>
  <span>tap project &rsaquo; tap file &rsaquo; done</span>
</div>

<div class="pills" id="pills">PROJECTS_PLACEHOLDER</div>

<div class="drop" id="drop">
  <span id="drop-label">select a project first</span>
  <input type="file" id="file" accept="image/*,video/*,.pdf,.txt,.json,.csv,.log" disabled>
</div>
<div class="toast" id="toast">&nbsp;</div>

<script>
let proj = null;
const pills = document.querySelectorAll('.pill');
const drop = document.getElementById('drop');
const label = document.getElementById('drop-label');
const input = document.getElementById('file');
const toast = document.getElementById('toast');

pills.forEach(p => p.addEventListener('click', () => {
  pills.forEach(b => b.classList.remove('on'));
  p.classList.add('on');
  proj = p.dataset.name;
  input.disabled = false;
  drop.className = 'drop ready';
  label.textContent = 'tap to select file';
  toast.textContent = ' ';
  toast.className = 'toast';
}));

input.addEventListener('change', async () => {
  if (!input.files.length || !proj) return;
  const file = input.files[0];
  drop.className = 'drop busy';
  label.textContent = file.name;

  const form = new FormData();
  form.append('file', file);
  form.append('project', proj);
  form.append('inject', '1');

  try {
    const r = await fetch('/upload', {method:'POST', body:form});
    const d = await r.json();
    if (d.ok) {
      drop.className = 'drop ok';
      label.textContent = d.injected ? 'pasted into ' + proj : file.name;
      toast.textContent = file.name + ' sent';
      toast.className = 'toast ok';
    } else {
      drop.className = 'drop err';
      label.textContent = d.error || 'failed';
      toast.className = 'toast err';
    }
  } catch(e) {
    drop.className = 'drop err';
    label.textContent = 'network error';
    toast.className = 'toast err';
  }
  input.value = '';
  setTimeout(() => {
    if (drop.classList.contains('ok') || drop.classList.contains('err')) {
      drop.className = 'drop ready';
      label.textContent = 'tap to select file';
    }
  }, 2000);
});
</script>
</body>
</html>"""


def _discover_sessions(config_path: str | None) -> list[dict]:
    """Find active psmux sessions from config."""
    from multideck.cli import _find_config
    from multideck.launch import _psmux_session_name

    config_file = _find_config(config_path)
    if not config_file.exists():
        return []

    data = json.loads(config_file.read_text(encoding="utf-8"))
    psmux = find_psmux()
    if not psmux:
        return []

    sessions = []
    for p in data.get("projects", []):
        if not p.get("enabled", True):
            continue
        tool = p.get("tool", data.get("settings", {}).get("defaultTool", "claude"))
        if tool in ("code", "vscode", "cursor"):
            continue
        proj_name = p.get("title") or Path(p["path"]).name
        sock = _psmux_session_name(proj_name)
        result = subprocess.run([psmux, "-L", sock, "has-session"],
                                capture_output=True)
        if result.returncode == 0:
            sessions.append({"name": sock, "path": p["path"]})
    return sessions


def _build_html(sessions: list[dict]) -> str:
    pills = []
    for s in sessions:
        name_esc = html.escape(s["name"])
        pills.append(f'<div class="pill" data-name="{name_esc}">{name_esc}</div>')
    placeholder = "\n".join(pills) if pills else '<p class="none">no active sessions</p>'
    return _HTML_TEMPLATE.replace("PROJECTS_PLACEHOLDER", placeholder)


def _parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """Minimal multipart/form-data parser. Returns (fields, files)."""
    content_type = handler.headers.get("Content-Type", "")
    if "boundary=" not in content_type:
        return {}, {}

    boundary = content_type.split("boundary=")[1].strip()
    if boundary.startswith('"') and boundary.endswith('"'):
        boundary = boundary[1:-1]

    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length)

    boundary_bytes = f"--{boundary}".encode()
    parts = body.split(boundary_bytes)

    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}

    for part in parts:
        if not part or part == b"--\r\n" or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_data, file_data = part.split(b"\r\n\r\n", 1)
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]

        header_str = header_data.decode("utf-8", errors="replace")
        name = ""
        filename = ""
        for line in header_str.split("\r\n"):
            if "Content-Disposition:" in line:
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token.split("=", 1)[1].strip('"')
                    elif token.startswith("filename="):
                        filename = token.split("=", 1)[1].strip('"')

        if filename:
            files[name] = (filename, file_data)
        elif name:
            fields[name] = file_data.decode("utf-8", errors="replace")

    return fields, files


class UploadHandler(BaseHTTPRequestHandler):
    config_path: str | None = None
    cached_sessions: list[dict] = []
    sessions_ts: float = 0

    def _sessions(self) -> list[dict]:
        now = time.time()
        if now - UploadHandler.sessions_ts > 10:
            UploadHandler.cached_sessions = _discover_sessions(UploadHandler.config_path)
            UploadHandler.sessions_ts = now
        return UploadHandler.cached_sessions

    def do_GET(self):
        if self.path == "/" or self.path == "":
            page = _build_html(self._sessions()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif self.path == "/api/sessions":
            body = json.dumps(self._sessions()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/upload":
            self.send_error(404)
            return

        fields, files = _parse_multipart(self)
        project = fields.get("project", "")
        inject = fields.get("inject", "1") == "1"

        if "file" not in files or not project:
            self._json_response({"ok": False, "error": "Missing file or project"}, 400)
            return

        valid_names = {s["name"] for s in self._sessions()}
        if project not in valid_names:
            self._json_response({"ok": False, "error": "Unknown project"}, 400)
            return

        filename, data = files["file"]
        basename = Path(filename).name.replace(" ", "_")
        basename = re.sub(r"[^\w.\-]", "_", basename)
        if not basename or basename.startswith("."):
            basename = "upload"
        safe_name = f"{int(time.time())}_{basename}"

        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = (_UPLOAD_DIR / safe_name).resolve()
        if not dest.is_relative_to(_UPLOAD_DIR.resolve()):
            self._json_response({"ok": False, "error": "Invalid filename"}, 400)
            return
        dest.write_bytes(data)

        injected = False
        if inject:
            psmux = find_psmux()
            if psmux:
                result = subprocess.run(
                    [psmux, "-L", project, "send-keys", "-t", project,
                     "--", str(dest)],
                    capture_output=True,
                )
                injected = result.returncode == 0

        UploadHandler.cached_sessions = _discover_sessions(UploadHandler.config_path)
        UploadHandler.sessions_ts = time.time()

        self._json_response({
            "ok": True,
            "path": str(dest),
            "injected": injected,
        })

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def run_server(port: int = 8080, config_path: str | None = None) -> None:
    UploadHandler.config_path = config_path
    server = HTTPServer(("0.0.0.0", port), UploadHandler)
    server.serve_forever()
