"""Tiny upload server for mobile image transfer to psmux sessions."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from multideck.platform import find_psmux


def _pid_path(port: int) -> Path:
    return Path.home() / ".multideck" / f"upload_server-{port}.pid"


def server_pid(port: int) -> int | None:
    """Return the PID of the upload server recorded for this port, if any."""
    p = _pid_path(port)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def stop_server(port: int) -> bool:
    """Stop the upload server running on the given port. Returns True if stopped."""
    pid = server_pid(port)
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, 15)
    except OSError:
        return False
    try:
        _pid_path(port).unlink()
    except OSError:
        pass
    return True


_UPLOAD_DIR = Path.home() / ".multideck" / "uploads"

# In-session upload feedback: a paste's progress shows in the SAME md:<project>
# window it landed in, via the psmux (tmux) status line -- never drawn into the
# agent pane. tmux 3.3 renders these UTF-8 glyphs intact.
_FB_UP = "↑"    # up arrow   -- uploading
_FB_OK = "✓"    # check mark -- uploaded
_FB_NO = "✗"    # ballot x   -- failed

# Color the flash so state reads at a glance: green while uploading AND on
# success, red on failure. This Cygwin tmux 3.3.6 does NOT expand inline #[...]
# style directives inside display-message (it prints them verbatim), so we tint
# the whole message bar via message-style instead -- set just before the flash,
# scoped to that project's own socket. It's overwritten on the next flash and
# only styles the transient message line, never the agent pane.
_MSG_GREEN = "bg=green,fg=black,bold"
_MSG_RED = "bg=red,fg=white,bold"

# How long each status-line flash lingers (ms). "uploading" is given a generous
# ceiling so it stays put until the result overwrites it; if something stalls
# without raising, it still clears on its own.
_FLASH_UP_MS = 20000
_FLASH_OK_MS = 2500
_FLASH_NO_MS = 3000

# Per-project count of pastes currently in flight, so several at once read as
# "uploading (2)" / "uploaded (1 more)" instead of stomping each other.
_inflight: dict[str, int] = {}
_inflight_lock = threading.Lock()


def _inflight_inc(project: str) -> int:
    with _inflight_lock:
        n = _inflight.get(project, 0) + 1
        _inflight[project] = n
        return n


def _inflight_dec(project: str) -> int:
    with _inflight_lock:
        n = max(0, _inflight.get(project, 1) - 1)
        if n:
            _inflight[project] = n
        else:
            _inflight.pop(project, None)
        return n


def _flash(psmux: str | None, project: str, message: str, duration_ms: int,
           style: str | None = None) -> None:
    """Best-effort: flash a transient message in the session's psmux status line.

    Non-disruptive -- ``display-message`` repaints the status bar, not the agent
    pane. ``style`` (a tmux message-style spec) tints the bar; it's set in the
    same psmux invocation, just before the message, via tmux's ``;`` command
    chaining. Never raises and never blocks the upload for long.
    """
    if not psmux:
        return
    cmd = [psmux, "-L", project]
    if style:
        cmd += ["set", "-g", "message-style", style, ";"]
    cmd += ["display-message", "-d", str(duration_ms), message]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>md upload</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#1e1e2e">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="md upload">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="icon" type="image/png" href="/icon-192.png">
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
.install{display:none;margin-top:14px;padding:10px 12px;border:1px solid #313244;
  border-radius:10px;background:#181825;font-size:.72rem;color:#9399b2;line-height:1.5}
.install.show{display:block}
.install b{color:#a6e3a1;font-weight:600}
.install button{margin-top:8px;width:100%;padding:8px;border:none;border-radius:8px;
  background:#a6e3a1;color:#1e1e2e;font-weight:700;font-size:.78rem;cursor:pointer}
.install .x{float:right;color:#585b70;cursor:pointer;font-size:.9rem;line-height:1}
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

<div class="install" id="install">
  <span class="x" id="install-x">&times;</span>
  <span id="install-text"></span>
  <button id="install-btn" style="display:none">Install app</button>
</div>

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

// Deep link: ?project=<name> (e.g. from a notification) pre-selects that
// project's pill on open, so a tap lands you straight on the right session.
(function () {
  const want = new URLSearchParams(location.search).get('project');
  if (!want) return;
  const pill = [...pills].find(p => p.dataset.name === want);
  if (pill) { pill.click(); pill.scrollIntoView({block: 'center'}); }
})();

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

<script>
// Register the service worker only where it's allowed (HTTPS/localhost); over
// plain HTTP this is simply skipped, no errors.
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// Add-to-home-screen helper. Hidden once installed. On Android/HTTPS the
// beforeinstallprompt event gives a one-tap Install button; otherwise we show
// the platform's manual steps.
(function () {
  const box = document.getElementById('install');
  const text = document.getElementById('install-text');
  const btn = document.getElementById('install-btn');
  const standalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
  if (standalone || localStorage.getItem('md-install-hide')) return;

  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (ios) {
    // One-tap: install the Web Clip profile (drops the icon straight on the
    // Home Screen). Must be Safari; offer the manual route as a fallback.
    text.innerHTML = "Tap to install the app icon, then <b>Install</b> the profile. "
      + "(If it doesn't open, use this page in <b>Safari</b>, or Share &rsaquo; Add to Home Screen.)";
    btn.textContent = 'Install to Home Screen';
    btn.style.display = 'block';
    btn.addEventListener('click', () => { location.href = '/install.mobileconfig'; });
  } else {
    text.innerHTML = "Install: open the browser <b>menu</b> then <b>Add to Home screen</b> (or <b>Install app</b>).";
    let deferred = null;
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      deferred = e;
      text.innerHTML = "Install <b>md upload</b> to your home screen for one-tap access.";
      btn.style.display = 'block';
    });
    btn.addEventListener('click', async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      box.classList.remove('show');
    });
  }
  box.classList.add('show');
  document.getElementById('install-x').addEventListener('click', () => {
    box.classList.remove('show');
    localStorage.setItem('md-install-hide', '1');
  });
})();
</script>
</body>
</html>"""


def _config_sessions(config_path: str | None) -> list[dict]:
    """Eligible psmux session names from config -- no psmux calls, so it's fast."""
    from multideck.cli import _find_config
    from multideck.launch import _psmux_session_name

    config_file = _find_config(config_path)
    if not config_file.exists():
        return []

    data = json.loads(config_file.read_text(encoding="utf-8"))
    default_tool = data.get("settings", {}).get("defaultTool", "claude")
    out: list[dict] = []
    for p in data.get("projects", []):
        if not p.get("enabled", True):
            continue
        tool = p.get("tool", default_tool)
        if tool in ("code", "vscode", "cursor"):
            continue
        proj_name = p.get("title") or Path(p["path"]).name
        out.append({"name": _psmux_session_name(proj_name), "path": p["path"]})
    return out


def _alive(psmux: str, name: str) -> bool:
    return subprocess.run([psmux, "-L", name, "has-session"], capture_output=True).returncode == 0


def _discover_sessions(config_path: str | None) -> list[dict]:
    """Active psmux sessions from config.

    Checks every candidate socket concurrently -- with a large config a serial
    scan takes several seconds, long enough to time out an Alt+V upload.
    """
    from concurrent.futures import ThreadPoolExecutor

    candidates = _config_sessions(config_path)
    psmux = find_psmux()
    if not candidates or not psmux:
        return []
    with ThreadPoolExecutor(max_workers=16) as pool:
        flags = list(pool.map(lambda c: _alive(psmux, c["name"]), candidates))
    return [c for c, ok in zip(candidates, flags) if ok]


def _build_html(sessions: list[dict]) -> str:
    pills = []
    for s in sessions:
        name_esc = html.escape(s["name"])
        pills.append(f'<div class="pill" data-name="{name_esc}">{name_esc}</div>')
    placeholder = "\n".join(pills) if pills else '<p class="none">no active sessions</p>'
    return _HTML_TEMPLATE.replace("PROJECTS_PLACEHOLDER", placeholder)


# --- PWA assets -----------------------------------------------------------
# So the uploader installs to the phone home screen as a standalone app: a web
# manifest + icons + a service worker. Icons are rendered in pure Python (an
# upload arrow on the catppuccin background) so there are no binary assets to
# ship and no image library to depend on. The service worker only registers in
# a secure context, so it's a no-op over plain HTTP today and lights up offline
# support automatically if the server is ever fronted with HTTPS.

_BG_RGBA = (30, 30, 46, 255)        # #1e1e2e  catppuccin base
_FG_RGBA = (166, 227, 161, 255)     # #a6e3a1  catppuccin green (upload arrow)
_TRANSPARENT = (0, 0, 0, 0)

_icon_cache: dict[tuple[int, bool], bytes] = {}
_icon_lock = threading.Lock()


def _png(width: int, height: int, rgba: bytes) -> bytes:
    """Encode raw RGBA bytes into a PNG (8-bit, color type 6). No deps."""
    import struct
    import zlib

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none) per scanline
        raw.extend(rgba[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _in_rounded(px: float, py: float, n: int, r: float) -> bool:
    cx = min(max(px, r), n - r)
    cy = min(max(py, r), n - r)
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy <= r * r


def _in_tri(px, py, a, b, c) -> bool:
    def sign(p, q, rr):
        return (px - rr[0]) * (q[1] - rr[1]) - (q[0] - rr[0]) * (py - rr[1])
    d1, d2, d3 = sign(a, a, b), sign(b, b, c), sign(c, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def render_icon(size: int, rounded: bool) -> bytes:
    """An upload arrow (green) on the dark base. ``rounded`` = transparent
    rounded corners (free-standing icon); else full-bleed square (Apple/maskable,
    where the OS applies its own mask)."""
    key = (size, rounded)
    with _icon_lock:
        if key in _icon_cache:
            return _icon_cache[key]
    r = 0.18 * size
    cx = size / 2
    apex_y, base_y, half_w = 0.24 * size, 0.56 * size, 0.26 * size
    stem_half, stem_top, stem_bot = 0.085 * size, 0.50 * size, 0.80 * size
    head = ((cx, apex_y), (cx - half_w, base_y), (cx + half_w, base_y))
    buf = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        in_stem_row = stem_top <= py <= stem_bot
        for x in range(size):
            px = x + 0.5
            i = (y * size + x) * 4
            if rounded and not _in_rounded(px, py, size, r):
                color = _TRANSPARENT
            elif _in_tri(px, py, *head) or (in_stem_row and abs(px - cx) <= stem_half):
                color = _FG_RGBA
            else:
                color = _BG_RGBA
            buf[i:i + 4] = bytes(color)
    png = _png(size, size, bytes(buf))
    with _icon_lock:
        _icon_cache[key] = png
    return png


_MANIFEST = json.dumps({
    "name": "multideck upload",
    "short_name": "md upload",
    "description": "Send images straight into your md: sessions",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#1e1e2e",
    "theme_color": "#1e1e2e",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}).encode("utf-8")

# Cache the shell; never the dynamic session list or the upload endpoint.
_SERVICE_WORKER = b"""\
const C = 'md-v1';
const SHELL = ['/icon-192.png', '/icon-512.png', '/manifest.webmanifest'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).catch(() => {}));
});
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.pathname === '/upload' || u.pathname === '/api/sessions'
      || u.pathname === '/install.mobileconfig') return;
  e.respondWith(
    fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(C).then(c => c.put(e.request, copy)).catch(() => {});
      return r;
    }).catch(() => caches.match(e.request))
  );
});
"""

# Static PWA routes: (content-type, lazy bytes factory). Served with a long
# immutable cache since the icons/manifest/sw rarely change.
_PWA_ROUTES = {
    "/manifest.webmanifest": ("application/manifest+json", lambda: _MANIFEST),
    "/sw.js": ("application/javascript", lambda: _SERVICE_WORKER),
    "/icon-192.png": ("image/png", lambda: render_icon(192, True)),
    "/icon-512.png": ("image/png", lambda: render_icon(512, True)),
    "/icon-maskable-512.png": ("image/png", lambda: render_icon(512, False)),
    "/apple-touch-icon.png": ("image/png", lambda: render_icon(180, False)),
}

# iOS "Web Clip" configuration profile. Tapping a link to this in Safari prompts
# to install a profile that drops a Home Screen icon (our green arrow) opening
# the uploader -- a true one-tap install, no Share-sheet hunt. The target URL is
# built from the request's Host header so it matches whatever the phone typed
# (tailnet name + port). Fixed UUIDs so reinstalling replaces rather than dupes.
_WEBCLIP_UUID = "9D3B7E10-0001-4A00-9000-000000000001"
_PROFILE_UUID = "9D3B7E10-0002-4A00-9000-000000000002"


def _mobileconfig(host: str) -> bytes:
    import base64
    import html as _html
    icon_b64 = base64.b64encode(render_icon(180, False)).decode("ascii")
    url = _html.escape(f"http://{host}/")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>FullScreen</key><true/>
      <key>IgnoreManifestScope</key><true/>
      <key>Icon</key>
      <data>{icon_b64}</data>
      <key>IsRemovable</key><true/>
      <key>Label</key><string>md upload</string>
      <key>PayloadDescription</key><string>Adds the md upload Home Screen icon.</string>
      <key>PayloadDisplayName</key><string>md upload</string>
      <key>PayloadIdentifier</key><string>ca.devino.multideck.webclip</string>
      <key>PayloadType</key><string>com.apple.webClip.managed</string>
      <key>PayloadUUID</key><string>{_WEBCLIP_UUID}</string>
      <key>PayloadVersion</key><integer>1</integer>
      <key>Precomposed</key><true/>
      <key>URL</key><string>{url}</string>
    </dict>
  </array>
  <key>PayloadDescription</key><string>Install the md upload app on your Home Screen.</string>
  <key>PayloadDisplayName</key><string>md upload</string>
  <key>PayloadIdentifier</key><string>ca.devino.multideck</string>
  <key>PayloadRemovalDisallowed</key><false/>
  <key>PayloadType</key><string>Configuration</string>
  <key>PayloadUUID</key><string>{_PROFILE_UUID}</string>
  <key>PayloadVersion</key><integer>1</integer>
</dict>
</plist>
""".encode("utf-8")


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


_FOCUS_TARGET_FILE = Path.home() / ".multideck" / "focus-target"
_PICKER_ATTACHED_FILE = Path.home() / ".multideck" / "picker-attached"


def _request_focus(project: str) -> None:
    """Ask the SSH session picker to switch to <project>: write a focus-target
    file and detach the picker's currently-attached client so its loop wakes,
    consumes the target, and re-attaches to it."""
    _FOCUS_TARGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FOCUS_TARGET_FILE.with_suffix(".tmp")
    tmp.write_text(project, encoding="utf-8")
    os.replace(tmp, _FOCUS_TARGET_FILE)
    psmux = find_psmux()
    try:
        current = _PICKER_ATTACHED_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        current = ""
    if psmux and current:
        try:
            subprocess.run([psmux, "-L", current, "detach-client"],
                           capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass


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

    def _send_bytes(self, data: bytes, content_type: str, cache: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "":
            self._send_bytes(_build_html(self._sessions()).encode("utf-8"),
                             "text/html; charset=utf-8")
        elif path == "/api/sessions":
            self._send_bytes(json.dumps(self._sessions()).encode(), "application/json")
        elif path == "/install.mobileconfig":
            # Built per-request: the Web Clip URL must match the host:port the
            # phone actually used, which only the Host header knows.
            host = self.headers.get("Host", "localhost")
            data = _mobileconfig(host)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-apple-aspen-config")
            self.send_header("Content-Disposition", 'attachment; filename="md-upload.mobileconfig"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/focus":
            project = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            if project in {s["name"] for s in self._sessions()}:
                _request_focus(project)
                safe = html.escape(project)
                body = (
                    "<!doctype html><meta charset=utf-8>"
                    "<meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<body style='margin:0;background:#1e1e2e;color:#cdd6f4;"
                    "font-family:system-ui;display:flex;align-items:center;"
                    "justify-content:center;height:100vh;text-align:center'>"
                    f"<div>Switched to <b style='color:#a6e3a1'>{safe}</b>.<br>"
                    "<span style='color:#6c7086;font-size:.85rem'>Open your terminal "
                    "(multideck sessions) to continue.</span></div></body>"
                ).encode("utf-8")
                self._send_bytes(body, "text/html; charset=utf-8")
            else:
                self.send_error(404)
        elif path in _PWA_ROUTES:
            content_type, factory = _PWA_ROUTES[path]
            self._send_bytes(factory(), content_type, cache=True)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/upload":
            self.send_error(404)
            return

        psmux = find_psmux()
        # Discovery is concurrent (sub-second), so validating against the session
        # cache no longer risks timing out the upload.
        valid_names = {s["name"] for s in self._sessions()}

        # The Alt+V listener passes ?project= so we can flash "uploading" the
        # instant the request lands -- before the image bytes are even read off
        # the socket -- right in that project's md: window. (The mobile web UI
        # doesn't, so it skips straight to the result flash below.)
        flagged = parse_qs(parsed.query).get("project", [""])[0]
        flagged = flagged if flagged in valid_names else ""
        if flagged:
            n = _inflight_inc(flagged)
            tail = f" ({n})" if n > 1 else ""
            _flash(psmux, flagged,
                   f"multideck  {_FB_UP} uploading image{tail}",
                   _FLASH_UP_MS, style=_MSG_GREEN)

        ok = False
        project = flagged
        try:
            fields, files = _parse_multipart(self)
            project = fields.get("project", "") or flagged
            inject = fields.get("inject", "1") == "1"

            if "file" not in files or not project:
                self._json_response({"ok": False, "error": "Missing file or project"}, 400)
                return
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
            if inject and psmux:
                result = subprocess.run(
                    [psmux, "-L", project, "send-keys", "-t", project,
                     "--", str(dest)],
                    capture_output=True,
                )
                injected = result.returncode == 0

            ok = True
            self._json_response({
                "ok": True,
                "path": str(dest),
                "injected": injected,
            })
        finally:
            # Confirm in the same md: status line -- for both the listener (paired
            # with the early "uploading" flash) and mobile uploads.
            remaining = _inflight_dec(flagged) if flagged else 0
            done = project if project in valid_names else flagged
            if done:
                more = f"  ({remaining} more)" if remaining else ""
                if ok:
                    _flash(psmux, done,
                           f"multideck  {_FB_OK} image uploaded{more}",
                           _FLASH_OK_MS, style=_MSG_GREEN)
                else:
                    _flash(psmux, done,
                           f"multideck  {_FB_NO} upload failed{more}",
                           _FLASH_NO_MS, style=_MSG_RED)

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
    server = ThreadingHTTPServer(("0.0.0.0", port), UploadHandler)
    pid_file = _pid_path(port)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    try:
        server.serve_forever()
    finally:
        try:
            pid_file.unlink()
        except OSError:
            pass
