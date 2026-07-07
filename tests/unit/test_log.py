"""Unit tests for multideck.log -- rotating file logging + liveness heartbeats.

Cross-platform (stdlib only) -- must run clean on the Linux/macOS/Windows CI
legs, not just Windows.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import time
from pathlib import Path

from multideck import log


class TestGetLogger:
    def test_idempotent_same_instance(self):
        a = log.get_logger("upload")
        b = log.get_logger("upload")
        assert a is b
        assert len(a.handlers) == 1  # repeat calls never stack handlers

    def test_handler_is_rotating_file_handler_with_expected_config(self):
        logger = log.get_logger("upload")
        handler = logger.handlers[0]
        assert isinstance(handler, logging.handlers.RotatingFileHandler)
        assert handler.maxBytes == 1_000_000
        assert handler.backupCount == 3

    def test_logged_line_lands_in_named_log_file(self):
        logger = log.get_logger("upload")
        logger.info("hello from test")
        log_file = log.LOG_DIR / "upload.log"
        assert log_file.exists()
        assert "hello from test" in log_file.read_text(encoding="utf-8")

    def test_mkdir_failure_falls_back_to_null_handler(self, monkeypatch):
        def _raise(*a, **k):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(Path, "mkdir", _raise)

        logger = log.get_logger("upload")
        assert isinstance(logger.handlers[0], logging.NullHandler)
        logger.info("must not raise")  # best-effort: still usable


class TestHeartbeat:
    def test_write_then_fresh(self):
        log.write_heartbeat("hotkey")
        age = log.heartbeat_age("hotkey")
        assert age is not None
        assert age < 1.0
        assert log.heartbeat_fresh("hotkey") is True

    def test_missing_heartbeat_is_none_and_not_fresh(self):
        assert log.heartbeat_age("nonexistent") is None
        assert log.heartbeat_fresh("nonexistent") is False

    def test_stale_heartbeat_is_not_fresh(self):
        log.write_heartbeat("hotkey")
        path = log._heartbeat_path("hotkey")
        old = time.time() - 120
        os.utime(path, (old, old))
        assert log.heartbeat_fresh("hotkey", max_age=30) is False
