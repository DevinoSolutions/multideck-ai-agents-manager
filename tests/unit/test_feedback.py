import importlib

import pytest

from multideck import feedback


class TestStages:
    def test_each_stage_has_glyph_color_title(self):
        for stage in ("start", "ok", "fail"):
            glyph, color, title = feedback._STAGES[stage]
            assert glyph and title
            assert color.isdigit()

    def test_stages_have_distinct_titles(self):
        titles = {feedback._STAGES[s][2] for s in ("start", "ok", "fail")}
        assert len(titles) == 3


class TestNotifySpec:
    def test_macos_uses_osascript_with_env(self):
        argv, env = feedback._notify_spec("ok", "eBay", "darwin")
        assert argv[0] == "osascript"
        assert env["MD_MSG"] == "eBay"
        assert env["MD_TITLE"]

    def test_windows_uses_powershell_with_env(self):
        argv, env = feedback._notify_spec("fail", "App Releasing Sessions", "win32")
        assert argv[0] == "powershell"
        assert env["MD_MSG"] == "App Releasing Sessions"   # spaces safe via env
        assert env["MD_ICON"] == "error"

    def test_linux_uses_notify_send_argv(self):
        argv, env = feedback._notify_spec("ok", "eBay", "linux")
        assert argv[0] == "notify-send"
        assert "eBay" in argv          # passed as argv, no shell -> quoting-safe
        assert env == {}

    def test_unknown_platform_returns_none(self):
        assert feedback._notify_spec("ok", "x", "sunos5") is None

    def test_project_with_quotes_never_reaches_a_shell(self):
        # macOS/Windows carry the value in env, Linux in argv -- never interpolated
        # into a shell string, so quotes/semicolons can't break or inject.
        nasty = 'a"; rm -rf ~ #'
        for plat in ("darwin", "win32"):
            argv, env = feedback._notify_spec("ok", nasty, plat)
            assert env["MD_MSG"] == nasty
            assert not any(nasty in a for a in argv)


class TestEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MULTIDECK_NO_FEEDBACK", raising=False)
        assert feedback.enabled() is True

    @pytest.mark.parametrize("val", ["1", "true", "yes", "anything"])
    def test_disabled_when_set(self, monkeypatch, val):
        monkeypatch.setenv("MULTIDECK_NO_FEEDBACK", val)
        assert feedback.enabled() is False


class TestSafeApi:
    def test_begin_finish_noop_when_disabled(self, monkeypatch):
        monkeypatch.setenv("MULTIDECK_NO_FEEDBACK", "1")
        h = feedback.begin("proj")
        assert h is None
        feedback.finish(h, "proj", True)
        feedback.finish(h, "proj", False)

    def test_play_tone_never_raises(self):
        for stage in ("start", "ok", "fail", "bogus"):
            feedback.play_tone(stage)

    def test_console_handles_ascii_fallback(self, capsys):
        feedback._console("ok", "eBay")
        out = capsys.readouterr().out
        assert "eBay" in out

    def test_module_imports_on_any_platform(self):
        importlib.reload(feedback)
