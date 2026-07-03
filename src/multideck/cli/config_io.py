"""Config-editor JSON I/O: the round-tripping raw-dict path (preserves
unknown/unmodeled keys on every read-modify-write), deliberately kept
separate from multideck.config.load_config (the validated typed path for
runtime consumption). E7 ships no typed *writer* and its loader intentionally
drops unknown keys -- round-tripping an editor save through the dataclass
would silently lose data. This module is that documented two-path contract,
not an oversight (E6.md S2.4 / S0 deviation).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from multideck.style import S


def _load_raw_config(path: Path) -> dict:
    if not path.exists():
        click.echo(f"No config found at: {path}", err=True)
        click.echo(f"Run {S('multideck', bold=True)} to generate one.", err=True)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_raw_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_config_or_exit(config_file: Path):
    from multideck.config import load_config      # heavy subsystem: in-body per policy
    try:
        return load_config(str(config_file))
    except (ValueError, FileNotFoundError) as e:  # ConfigError <: ValueError (E7 S2d) -> caught
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
