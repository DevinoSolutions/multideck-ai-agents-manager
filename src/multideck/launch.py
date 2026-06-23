from __future__ import annotations

from dataclasses import dataclass

from multideck.config import MultideckConfig


@dataclass
class RunOpts:
    retile_all: bool = False
    dry_run: bool = False
    group: str | None = None
    config_path: str = ""


def run_multideck(config: MultideckConfig, opts: RunOpts) -> None:
    pass
