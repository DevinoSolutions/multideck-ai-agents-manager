import importlib
import threading

import pytest

from multideck import feedback


class TestStages:
    def test_each_stage_has_glyph_color_ascii(self):
        for stage in ("start", "ok", "fail"):
            glyph, color, ascii_glyph = feedback._STAGES[stage]
            assert glyph and ascii_glyph
            assert color.isdigit()

    def test_no_popup_or_audio_surface(self):
        # terminal-only: no desktop-notification or sound entry points remain
        for attr in ("play_tone", "_notify", "_notify_spec", "_PS_BALLOON", "_TONES"):
            assert not hasattr(feedback, attr)


class TestEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        assert feedback.enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "yes", "anything"])
    def test_disabled_when_set(self, monkeypatch, val):
        monkeypatch.setenv("MULTIDECK_NO_FEEDBACK", val)
        assert feedback.enabled() is False


class TestLog:
    def test_begin_returns_incrementing_id(self, monkeypatch):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        a = feedback.begin("eBay")
        b = feedback.begin("marka")
        assert isinstance(a, int) and isinstance(b, int)
        assert b > a

    def test_start_line_names_project_and_id(self, monkeypatch, capsys):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        uid = feedback.begin("eBay")
        out = capsys.readouterr().out
        assert "eBay" in out
        assert f"#{uid}" in out
        assert "uploading" in out

    def test_finish_ok_shows_sent_and_timing(self, monkeypatch, capsys):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        uid = feedback.begin("eBay")
        capsys.readouterr()
        feedback.finish(uid, "eBay", True)
        out = capsys.readouterr().out
        assert f"#{uid}" in out
        assert "sent" in out
        assert "s)" in out  # "(0.0s)" timing tail

    def test_finish_fail_shows_failed(self, monkeypatch, capsys):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        uid = feedback.begin("personal-portfolio")
        capsys.readouterr()
        feedback.finish(uid, "personal-portfolio", False)
        out = capsys.readouterr().out
        assert "failed" in out

    def test_concurrent_uploads_keep_distinct_ids(self, monkeypatch, capsys):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        a = feedback.begin("eBay")
        b = feedback.begin("eBay")          # same project, two in flight
        assert a != b
        feedback.finish(b, "eBay", True)
        feedback.finish(a, "eBay", True)
        out = capsys.readouterr().out
        assert f"#{a}" in out and f"#{b}" in out

    def test_disabled_is_silent_noop(self, monkeypatch, capsys):
        monkeypatch.setenv("MULTIDECK_NO_FEEDBACK", "1")
        h = feedback.begin("proj")
        assert h is None
        feedback.finish(h, "proj", True)
        assert capsys.readouterr().out == ""

    def test_thread_safe_under_load(self, monkeypatch):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        with feedback._lock:
            feedback._active.clear()  # ignore dangling entries from other tests

        def worker(name):
            for _ in range(20):
                uid = feedback.begin(name)
                feedback.finish(uid, name, True)

        threads = [threading.Thread(target=worker, args=(f"p{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # no active uploads should be left dangling
        assert feedback._active == {}

    def test_module_imports_on_any_platform(self):
        importlib.reload(feedback)

    def test_init_console_never_raises(self):
        feedback.init_console()
