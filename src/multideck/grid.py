from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class MonitorRect(Rect):
    is_primary: bool = False
    scale_factor: float = 1.0


@dataclass
class TileSlot(Rect):
    monitor_index: int = 0
    label: str = ""


def compute_grid(monitors: list[MonitorRect], cols: int, rows: int) -> list[TileSlot]:
    monitors_sorted = sorted(monitors, key=lambda m: m.x)
    slots: list[TileSlot] = []
    for i, m in enumerate(monitors_sorted):
        cell_w = m.w // cols
        cell_h = m.h // rows
        for r in range(rows):
            for c in range(cols):
                slots.append(TileSlot(
                    x=m.x + c * cell_w,
                    y=m.y + r * cell_h,
                    w=cell_w,
                    h=cell_h,
                    monitor_index=i,
                    label=f"r{r + 1}c{c + 1}",
                ))
    return slots
