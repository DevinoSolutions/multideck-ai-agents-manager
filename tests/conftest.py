import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Write a config dict to a temp JSON file and return the path."""
    def _write(config_dict):
        p = tmp_path / "multideck.config.json"
        p.write_text(json.dumps(config_dict))
        return str(p)
    return _write


@pytest.fixture
def fake_claude_sessions(tmp_path):
    """Create fake Claude session .jsonl files with controlled mtimes."""
    def _create(encoded_path, sessions):
        sess_dir = tmp_path / ".claude" / "projects" / encoded_path
        sess_dir.mkdir(parents=True, exist_ok=True)
        for uuid, mtime in sessions:
            f = sess_dir / f"{uuid}.jsonl"
            f.write_text('{"type":"message"}\n')
            os.utime(f, (mtime, mtime))
        return sess_dir
    _create.__wrapped_tmp = tmp_path
    return _create


@pytest.fixture
def fake_codex_sessions(tmp_path):
    """Create fake Codex session .jsonl files with CWD metadata."""
    def _create(sessions):
        sess_root = tmp_path / ".codex" / "sessions"
        for i, (cwd, uuid, mtime) in enumerate(sessions):
            day_dir = sess_root / "2026" / "06" / str(20 + i)
            day_dir.mkdir(parents=True, exist_ok=True)
            meta = {"timestamp": "2026-06-20T00:00:00Z", "type": "session_meta",
                    "payload": {"id": uuid, "cwd": cwd}}
            f = day_dir / f"session-{i}-{uuid}.jsonl"
            f.write_text(json.dumps(meta) + "\n")
            os.utime(f, (mtime, mtime))
        return sess_root
    _create.__wrapped_tmp = tmp_path
    return _create
