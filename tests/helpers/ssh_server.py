from __future__ import annotations

import os


def get_ssh_config() -> dict | None:
    port = os.environ.get("MDTEST_SSH_PORT")
    key = os.environ.get("MDTEST_SSH_KEY")
    if not port or not key:
        return None
    return {"port": int(port), "key": key, "host": "localhost"}
