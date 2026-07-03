"""Pure presentation leaf: banner/menu chrome and the config-editor's
printing helpers. No config or subprocess state of its own beyond the two
platform-guarded helpers (_force_utf8_console: win-only ctypes;
_print_qr: optional `qrcode` dep) -- both keep their guard in-body.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from multideck import __version__
from multideck.style import S

LOGO_LINES = [
    r"           _ _   _    _        _   ",
    r" _ __ _  _| | |_(_)__| |___ __| |__",
    r"| '  \ || | |  _| / _` / -_) _| / /",
    r"|_|_|_\_,_|_|\__|_\__,_\___\__|_\_\\",
]


def _banner() -> None:
    click.echo()
    for line in LOGO_LINES:
        click.echo(f"  {S(line, fg='cyan')}")
    click.echo(f"  {S(f'v{__version__}', dim=True)}  {S('auto-tile your AI workspace', dim=True)}")
    click.echo()


def _divider() -> None:
    click.echo(f"  {S('-' * 40, dim=True)}")


def _menu_item(key: str, label: str, key_fg: str = "cyan", extra: str = "") -> None:
    click.echo(f"   {S(key, fg=key_fg, bold=True)}   {label}{extra}")


def _grid_preview(cols: int, rows: int, indent: str = "  ") -> list[str]:
    cell_w = 10
    lines: list[str] = []
    border = "+" + (f"{'-' * cell_w}+") * cols
    for r in range(rows):
        lines.append(f"{indent}{S(border, dim=True)}")
        cells = ""
        for c in range(cols):
            n = r * cols + c + 1
            label = f"win {n}"
            pad = cell_w - len(label)
            left = pad // 2
            right = pad - left
            cells += S("|", dim=True) + " " * left + S(label, fg="cyan") + " " * right
        cells += S("|", dim=True)
        lines.append(f"{indent}{cells}")
    lines.append(f"{indent}{S(border, dim=True)}")
    return lines


def _open_in_editor(path: Path) -> None:
    path_str = str(path)
    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path_str])
    else:
        editor = os.environ.get("EDITOR", "xdg-open")
        subprocess.Popen([editor, path_str])


def _confirm_change(message: str) -> None:
    click.echo(f"\n  {S('+', fg='green', bold=True)} {message}")
    click.echo(f"  {S('Press Enter to continue...', dim=True)}", nl=False)
    click.getchar()
    click.echo()


def _prompt_or_back(label: str, default: str = "", **kwargs) -> str | None:
    hint = S("  (b to go back)", dim=True)
    value = click.prompt(f"  {label}{hint}", default=default, **kwargs).strip()
    if value.lower() == "b":
        return None
    return value


def _force_utf8_console() -> None:
    """Make stdout render UTF-8 (block chars for the QR, box glyphs) on Windows
    consoles that default to a legacy code page. Best-effort, never raises."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # guarded by try/except; reconfigure exists on the real TextIOWrapper
    except Exception:
        pass


def _print_qr(url: str) -> None:
    """Print a scannable QR for the URL if the qrcode lib is available."""
    try:
        import qrcode
    except ImportError:
        click.echo(f"  {S('Tip:', dim=True)} {S('pip install qrcode', bold=True)} "
                   f"{S('to print a scannable QR code here.', dim=True)}")
        return
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def _grouped(entries: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    """Bucket session entries by project group, preserving first-seen order."""
    order: list[str] = []
    buckets: dict[str, list[str]] = {}
    for e in entries:
        g = e.get("group") or "(no group)"
        if g not in buckets:
            buckets[g] = []
            order.append(g)
        buckets[g].append(e["name"])
    return order, buckets


def _print_names(names: list[str], indent: str = "       ", width: int = 66) -> None:
    line = indent
    for nm in names:
        if line.strip() and len(line) + len(nm) + 2 > width:
            click.echo(S(line, dim=True))
            line = indent
        line += nm + "  "
    if line.strip():
        click.echo(S(line, dim=True))


def _print_session_overview(hostname: str, up: list[dict], down: list[dict]) -> list[str]:
    """Render a grouped up/down overview; return the ordered list of pickable groups."""
    dn_order, dn_buckets = _grouped(down)
    up_order, up_buckets = _grouped(up)

    click.echo()
    click.echo(f"  {S('Sessions on', bold=True)} {S(hostname, fg='cyan')}    "
               f"{S(str(len(up)), fg='green', bold=True)} up  {S('/', dim=True)}  "
               f"{S(str(len(down)), fg='yellow', bold=True)} down")
    _divider()

    pickable: list[str] = []
    for g in dn_order:
        names = dn_buckets[g]
        up_n = len(up_buckets.get(g, []))
        total = up_n + len(names)
        if g == "(no group)":
            click.echo(f"     {S(g, dim=True)}  {S(f'{up_n}/{total}', dim=True)}")
        else:
            pickable.append(g)
            num = S(str(len(pickable)), fg="cyan", bold=True)
            click.echo(f"  {num}  {S(g, bold=True)}  {S(f'{up_n}/{total} up', dim=True)}")
        _print_names(names)

    for g in up_order:
        if g not in dn_buckets:
            cnt = len(up_buckets[g])
            click.echo(f"     {S(g, dim=True)}  {S(f'{cnt}/{cnt} ready', fg='green')}")
    _divider()
    return pickable
