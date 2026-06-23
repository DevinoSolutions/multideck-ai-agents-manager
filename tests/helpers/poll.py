from __future__ import annotations

import time
from typing import Any, Callable


def poll_until(fn: Callable[[], Any], timeout: float = 10.0, interval: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None
