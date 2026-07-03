import json
import os
import shutil
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


def _path_without_ssh():
    sep = ";" if sys.platform == "win32" else ":"
    dirs = os.environ.get("PATH", "").split(sep)
    filtered = [d for d in dirs if not (os.path.isfile(os.path.join(d, "ssh")) or os.path.isfile(os.path.join(d, "ssh.exe")))]
    return sep.join(filtered)


@pytest.fixture
def ssh_available():
    port = os.environ.get("MULTIDECK_TEST_SSH_PORT")
    key = os.environ.get("MULTIDECK_TEST_SSH_KEY")
    if not port or not key:
        pytest.skip("SSH test server not configured (set MULTIDECK_TEST_SSH_PORT and MULTIDECK_TEST_SSH_KEY)")
    return {"port": port, "key": key}


class TestSSHLaunch:
    def test_ssh_project_dry_run(self, tmp_path, ssh_available):
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "projects": [{
                "host": "localhost",
                "path": "/tmp",
                "tool": "claude",
                "title": "remote-test",
            }],
            "settings": {
                "tools": {"claude": "echo hello"},
                "ssh": {"shell": "bash -lc"},
            },
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "remote-test" in result.stdout

    def test_ssh_missing_warning(self, tmp_path):
        if shutil.which("ssh") is None:
            pytest.skip("ssh already not on PATH")
        no_ssh_path = _path_without_ssh()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "projects": [{"host": "fake@host", "path": "/tmp"}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
            env={**os.environ, "PATH": no_ssh_path},
        )
        assert result.returncode == 0
