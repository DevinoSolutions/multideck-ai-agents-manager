import pytest

from multideck.platform import Platform


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
