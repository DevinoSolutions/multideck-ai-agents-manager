from multideck.grid import compute_grid, TileSlot, Rect, MonitorRect


def _mon(x, y, w, h, primary=False, scale=1.0):
    return MonitorRect(x=x, y=y, w=w, h=h, is_primary=primary, scale_factor=scale)


class TestComputeGrid:
    def test_single_monitor_2x1(self):
        monitors = [_mon(0, 0, 1920, 1080, primary=True)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 2
        assert slots[0] == TileSlot(x=0, y=0, w=960, h=1080, monitor_index=0, label="r1c1")
        assert slots[1] == TileSlot(x=960, y=0, w=960, h=1080, monitor_index=0, label="r1c2")

    def test_single_monitor_2x2(self):
        monitors = [_mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=2, rows=2)
        assert len(slots) == 4
        assert slots[0] == TileSlot(x=0, y=0, w=960, h=540, monitor_index=0, label="r1c1")
        assert slots[1] == TileSlot(x=960, y=0, w=960, h=540, monitor_index=0, label="r1c2")
        assert slots[2] == TileSlot(x=0, y=540, w=960, h=540, monitor_index=0, label="r2c1")
        assert slots[3] == TileSlot(x=960, y=540, w=960, h=540, monitor_index=0, label="r2c2")

    def test_two_monitors_different_sizes(self):
        monitors = [_mon(0, 0, 1920, 1080), _mon(1920, 0, 2560, 1440)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 4
        assert slots[0].x == 0
        assert slots[0].w == 960
        assert slots[1].x == 960
        assert slots[1].w == 960
        assert slots[2].x == 1920
        assert slots[2].w == 1280
        assert slots[3].x == 1920 + 1280
        assert slots[3].w == 1280

    def test_monitors_sorted_by_x(self):
        monitors = [_mon(1920, 0, 1920, 1080), _mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=1, rows=1)
        assert slots[0].x == 0
        assert slots[0].monitor_index == 0
        assert slots[1].x == 1920
        assert slots[1].monitor_index == 1

    def test_taskbar_offset(self):
        monitors = [_mon(0, 40, 1920, 1040)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert slots[0].y == 40
        assert slots[0].h == 1040

    def test_three_monitors_mixed_res(self):
        monitors = [
            _mon(0, 0, 1920, 1080),
            _mon(1920, 0, 2560, 1440),
            _mon(4480, 0, 3840, 2160),
        ]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 6

    def test_1x1_grid(self):
        monitors = [_mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=1, rows=1)
        assert len(slots) == 1
        assert slots[0] == TileSlot(x=0, y=0, w=1920, h=1080, monitor_index=0, label="r1c1")
