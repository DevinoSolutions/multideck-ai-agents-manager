import subprocess
import sys
import time
import pytest

pytestmark = pytest.mark.platform


@pytest.fixture
def platform():
    from multideck.platform import get_platform
    return get_platform()


class TestFindWindow:
    @pytest.fixture
    def notepad_window(self):
        if sys.platform == "win32":
            proc = subprocess.Popen(["notepad.exe"])
            time.sleep(1)
            yield "Untitled - Notepad"
            proc.kill()
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'tell application "TextEdit" to make new document'], check=True)
            time.sleep(1)
            yield "Untitled"
            subprocess.run(["osascript", "-e", 'tell application "TextEdit" to quit'], check=False)
        else:
            proc = subprocess.Popen(["xterm", "-T", "test-multideck-find", "-e", "sleep 30"])
            time.sleep(1)
            yield "test-multideck-find"
            proc.kill()

    def test_find_existing_window(self, platform, notepad_window):
        handle = platform.find_window(notepad_window, mode="contains")
        assert handle is not None

    def test_find_nonexistent_window(self, platform):
        handle = platform.find_window("__nonexistent_window_title_99999__")
        assert handle is None
