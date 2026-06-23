import sys
import pytest

pytestmark = pytest.mark.platform


class TestTerminalDetection:
    def test_detect_returns_string(self):
        from multideck.terminals import detect_terminal
        name = detect_terminal()
        assert isinstance(name, str)
        assert len(name) > 0

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_uses_wt(self):
        from multideck.terminals import detect_terminal
        assert detect_terminal() == "wt"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
    def test_unix_finds_a_terminal(self):
        from multideck.terminals import detect_terminal
        name = detect_terminal()
        assert name in ("kitty", "alacritty", "gnome-terminal", "konsole", "xterm",
                         "iterm2", "warp", "terminal.app")
