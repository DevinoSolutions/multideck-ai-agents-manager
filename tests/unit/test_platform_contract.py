import sys

import pytest

from multideck.platform import Platform
from multideck.platform.linux import LinuxPlatform
from multideck.platform.macos import MacOSPlatform


class _Bare(Platform):
    """Minimal concrete subclass -- exercises only the ABC's own defaults
    (snapshot_windows/launch_psmux_session), not a real platform backend."""

    def set_dpi_aware(self) -> None:
        pass

    def list_monitors(self):
        return []

    def find_window(self, title: str, mode: str = "exact"):
        return None

    def move_window(self, handle, rect) -> None:
        pass

    def launch_terminal(self, opts) -> None:
        pass

    def launch_vscode(self, opts) -> None:
        pass


def test_fake_platform_is_a_platform(fake_platform):
    assert isinstance(fake_platform, Platform)
    monitors = fake_platform.list_monitors()
    assert len(monitors) >= 1
    assert any(m.is_primary for m in monitors)


def test_base_snapshot_windows_default_empty():
    assert _Bare().snapshot_windows() == {}


def test_base_launch_psmux_raises():
    with pytest.raises(NotImplementedError):
        _Bare().launch_psmux_session([])


# --- Capability truth table (R8) --------------------------------------------
# psmux/hotkey are Windows-only today. The ABC's own defaults cover any
# subclass that implements no backend for them (_Bare) as well as the two
# real non-Windows backends -- both import cleanly on any OS (no ctypes/windll
# at import time), unlike WindowsPlatform below.
_DEFAULT_BACKENDS = [_Bare, LinuxPlatform, MacOSPlatform]


@pytest.mark.parametrize("platform_cls", _DEFAULT_BACKENDS)
def test_default_supports_psmux_false(platform_cls):
    assert platform_cls().supports_psmux() is False


@pytest.mark.parametrize("platform_cls", _DEFAULT_BACKENDS)
def test_default_supports_hotkey_false(platform_cls):
    assert platform_cls().supports_hotkey() is False


@pytest.mark.parametrize("platform_cls", _DEFAULT_BACKENDS)
def test_default_attach_psmux_raises(platform_cls):
    with pytest.raises(NotImplementedError, match="psmux"):
        platform_cls().attach_psmux("s", "t")


@pytest.mark.parametrize("platform_cls", [LinuxPlatform, MacOSPlatform])
def test_default_launch_psmux_session_raises(platform_cls):
    with pytest.raises(NotImplementedError):
        platform_cls().launch_psmux_session([])


@pytest.mark.skipif(
    sys.platform != "win32", reason="WindowsPlatform binds windll at import"
)
class TestWindowsCapabilities:
    def test_supports_psmux_true(self):
        from multideck.platform.windows import WindowsPlatform

        assert WindowsPlatform().supports_psmux() is True

    def test_supports_hotkey_true(self):
        from multideck.platform.windows import WindowsPlatform

        assert WindowsPlatform().supports_hotkey() is True


# --- find_window mode contract (LS-B-005) -----------------------------------
# mode is a Literal["exact", "contains"]; a typo'd mode must fail loudly
# instead of silently reporting "not found".


@pytest.mark.parametrize("platform_cls", [LinuxPlatform, MacOSPlatform])
def test_find_window_unknown_mode_raises(platform_cls):
    with pytest.raises(ValueError):
        platform_cls().find_window("t", mode="bogus")  # type: ignore[arg-type]  # reason: invalid mode passed on purpose to prove it raises


@pytest.mark.skipif(
    sys.platform != "win32", reason="WindowsPlatform binds windll at import"
)
def test_find_window_unknown_mode_raises_windows():
    from multideck.platform.windows import WindowsPlatform

    with pytest.raises(ValueError):
        WindowsPlatform().find_window("t", mode="bogus")  # type: ignore[arg-type]  # reason: invalid mode passed on purpose to prove it raises
