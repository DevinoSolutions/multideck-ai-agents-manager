"""Unit tests for the attention engine (multideck.attention) and the
agent_state store additions it reads (all_states, norm_cwd).

Everything runs against a tmp_path STATE_DIR and a fake clock — no real
time, no platform, no daemon.
"""

from __future__ import annotations

import json
import sys
import types
import urllib.error

import pytest

from multideck import agent_state, attention
from multideck.attention import AttentionEngine, name_map_from_projects


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setattr(agent_state, "STATE_DIR", d)
    return d


def _write_record(
    state_dir, cwd: str, state: str, ts: float, session_id: str | None = None
) -> None:
    key = agent_state._key(cwd)
    payload = {
        "state": state,
        "ts": ts,
        "cwd": agent_state.norm_cwd(cwd),
        "session_id": session_id,
    }
    (state_dir / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")


class TestAllStates:
    def test_reads_every_valid_record(self, state_dir):
        _write_record(state_dir, "/tmp/a", agent_state.WORKING, 100.0)
        _write_record(state_dir, "/tmp/b", agent_state.DONE, 200.0)

        records = agent_state.all_states()

        assert {r["cwd"] for r in records} == {"/tmp/a", "/tmp/b"}

    def test_skips_corrupt_and_non_object_files(self, state_dir):
        _write_record(state_dir, "/tmp/a", agent_state.WORKING, 100.0)
        (state_dir / "corrupt.json").write_text("{not json", encoding="utf-8")
        (state_dir / "list.json").write_text("[1, 2]", encoding="utf-8")

        records = agent_state.all_states()

        assert len(records) == 1
        assert records[0]["cwd"] == "/tmp/a"

    def test_empty_store_returns_empty(self, state_dir):
        assert agent_state.all_states() == []

    def test_missing_store_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_state, "STATE_DIR", tmp_path / "nope")
        assert agent_state.all_states() == []


class TestNormCwd:
    def test_matches_the_store_writer(self):
        # write_state keys records by _norm(cwd); norm_cwd must be the same
        # canonicalization or the engine's name map misses every project.
        assert agent_state.norm_cwd("/tmp/a/") == agent_state._norm("/tmp/a/")
        assert agent_state.norm_cwd("C:\\proj\\x") == agent_state._norm("C:\\proj\\x")


class TestNameMap:
    def test_maps_normalized_paths_to_names(self):
        m = name_map_from_projects([("api", "/home/dev/api/"), ("web", "")])
        assert m == {agent_state.norm_cwd("/home/dev/api/"): "api"}


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestEnginePoll:
    def test_names_resolve_via_map_with_leaf_fallback(self, state_dir):
        _write_record(state_dir, "/home/dev/api", agent_state.WORKING, 990.0)
        _write_record(state_dir, "/home/dev/mystery", agent_state.DONE, 990.0)
        engine = AttentionEngine(
            name_map_from_projects([("API Project", "/home/dev/api")]),
            now=FakeClock(1000.0),
        )

        views = engine.poll()

        by_cwd = {v.cwd: v for v in views}
        assert by_cwd["/home/dev/api"].name == "API Project"
        assert by_cwd["/home/dev/mystery"].name == "mystery"

    def test_sorts_most_urgent_first(self, state_dir):
        _write_record(state_dir, "/w", agent_state.WORKING, 995.0)
        _write_record(state_dir, "/n", agent_state.NEEDS_INPUT, 990.0)
        _write_record(state_dir, "/d", agent_state.DONE, 992.0)
        _write_record(state_dir, "/e", agent_state.ERROR, 991.0)
        engine = AttentionEngine(now=FakeClock(1000.0))

        states = [v.state for v in engine.poll()]

        assert states == [
            agent_state.NEEDS_INPUT,
            agent_state.ERROR,
            agent_state.DONE,
            agent_state.WORKING,
        ]

    def test_stale_working_degrades_to_idle(self, state_dir):
        _write_record(state_dir, "/w", agent_state.WORKING, 1000.0)
        clock = FakeClock(1000.0 + attention.STALENESS_S[agent_state.WORKING] + 1)
        engine = AttentionEngine(now=clock)

        views = engine.poll()

        assert views[0].state == agent_state.IDLE

    def test_stale_needs_input_degrades_to_idle(self, state_dir):
        _write_record(state_dir, "/n", agent_state.NEEDS_INPUT, 1000.0)
        clock = FakeClock(1000.0 + attention.STALENESS_S[agent_state.NEEDS_INPUT] + 1)
        engine = AttentionEngine(now=clock)

        assert engine.poll()[0].state == agent_state.IDLE

    def test_fresh_states_survive(self, state_dir):
        _write_record(state_dir, "/n", agent_state.NEEDS_INPUT, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))

        v = engine.poll()[0]

        assert v.state == agent_state.NEEDS_INPUT
        assert v.age_s == pytest.approx(1.0)

    def test_malformed_records_are_skipped(self, state_dir):
        (state_dir / "weird.json").write_text(
            json.dumps({"state": 42, "cwd": "/x", "ts": 1.0}), encoding="utf-8"
        )
        _write_record(state_dir, "/ok", agent_state.DONE, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))

        views = engine.poll()

        assert [v.cwd for v in views] == ["/ok"]


class TestEngineTransitions:
    def test_first_sighting_is_a_transition_from_none(self, state_dir):
        _write_record(state_dir, "/a", agent_state.WORKING, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))

        trans = engine.transitions(engine.poll())

        assert len(trans) == 1
        assert trans[0].prev_state is None
        assert trans[0].view.state == agent_state.WORKING

    def test_state_change_reports_prev(self, state_dir):
        _write_record(state_dir, "/a", agent_state.WORKING, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))
        engine.transitions(engine.poll())

        _write_record(state_dir, "/a", agent_state.NEEDS_INPUT, 999.5)
        trans = engine.transitions(engine.poll())

        assert len(trans) == 1
        assert trans[0].prev_state == agent_state.WORKING
        assert trans[0].view.state == agent_state.NEEDS_INPUT

    def test_no_change_reports_nothing(self, state_dir):
        _write_record(state_dir, "/a", agent_state.WORKING, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))
        engine.transitions(engine.poll())

        assert engine.transitions(engine.poll()) == []

    def test_vanished_session_reappears_as_fresh_transition(self, state_dir):
        _write_record(state_dir, "/a", agent_state.DONE, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))
        engine.transitions(engine.poll())

        agent_state.clear_state("/a")
        assert engine.transitions(engine.poll()) == []

        _write_record(state_dir, "/a", agent_state.DONE, 999.9)
        trans = engine.transitions(engine.poll())
        assert len(trans) == 1
        assert trans[0].prev_state is None


class TestDebounce:
    def test_first_fire_allowed_repeat_suppressed(self):
        clock = FakeClock(1000.0)
        engine = AttentionEngine(now=clock)

        assert engine.should_fire("/a", "needs-input") is True
        assert engine.should_fire("/a", "needs-input") is False

    def test_fire_allowed_again_after_window(self):
        clock = FakeClock(1000.0)
        engine = AttentionEngine(now=clock)
        engine.should_fire("/a", "needs-input")

        clock.t += attention.DEBOUNCE_S + 1
        assert engine.should_fire("/a", "needs-input") is True

    def test_debounce_is_per_session_and_state(self):
        engine = AttentionEngine(now=FakeClock(1000.0))
        engine.should_fire("/a", "needs-input")

        assert engine.should_fire("/b", "needs-input") is True
        assert engine.should_fire("/a", "error") is True


# --- Renderers ----------------------------------------------------------------


def _view(name: str, cwd: str, state: str) -> attention.SessionView:
    return attention.SessionView(name=name, cwd=cwd, state=state, ts=999.0, age_s=1.0)


def _trans(view: attention.SessionView, prev: str | None) -> attention.Transition:
    return attention.Transition(view=view, prev_state=prev)


class TestBadgeRenderer:
    def _fake(self, windows):
        from tests.conftest import FakePlatform

        return FakePlatform(windows=windows, supports_attention=True)

    def test_badges_attention_states_and_leaves_foreign_windows(self):
        fp = self._fake({"md:api": 1, "Notepad": 2})
        r = attention.BadgeRenderer(fp)

        r.render([_view("api", "/a", "needs-input")], [])

        assert fp.titles_set == [(1, "md:[!] api")]

    def test_idempotent_when_title_already_correct(self):
        fp = self._fake({"md:[!] api": 1})
        r = attention.BadgeRenderer(fp)

        r.render([_view("api", "/a", "needs-input")], [])
        r.render([_view("api", "/a", "needs-input")], [])

        assert fp.titles_set == []

    def test_unbadges_when_state_goes_quiet(self):
        fp = self._fake({"md:[!] api": 1})
        r = attention.BadgeRenderer(fp)

        r.render([_view("api", "/a", "working")], [])

        assert fp.titles_set == [(1, "md:api")]

    def test_ignores_md_windows_with_no_session(self):
        fp = self._fake({"md:api-2": 5})
        r = attention.BadgeRenderer(fp)

        r.render([_view("api", "/a", "error")], [])

        assert fp.titles_set == []


class TestFlashRenderer:
    def _fake(self, windows):
        from tests.conftest import FakePlatform

        return FakePlatform(windows=windows, supports_attention=True)

    def test_flashes_on_needs_input_transition(self):
        fp = self._fake({"md:api": 1})
        r = attention.FlashRenderer(fp)
        v = _view("api", "/a", "needs-input")

        r.render([v], [_trans(v, "working")])

        assert fp.flashed == [1]

    def test_no_flash_without_transition(self):
        fp = self._fake({"md:api": 1})
        r = attention.FlashRenderer(fp)

        r.render([_view("api", "/a", "needs-input")], [])

        assert fp.flashed == []

    def test_no_flash_for_quiet_transitions(self):
        fp = self._fake({"md:api": 1})
        r = attention.FlashRenderer(fp)
        v = _view("api", "/a", "done")

        r.render([v], [_trans(v, "working")])

        assert fp.flashed == []


class TestToastRenderer:
    def test_missing_winotify_logs_tip_once(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "winotify", None)  # import -> ImportError
        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.ToastRenderer(engine)
        v = _view("api", "/a", "needs-input")

        import logging

        with caplog.at_level(logging.WARNING, logger="multideck.attention"):
            r.render([v], [_trans(v, "working")])
            r.render([v], [_trans(v, "working")])

        assert caplog.text.count("winotify") == 1
        assert "multideck[toast]" in caplog.text

    def test_fires_toast_via_fake_winotify(self, monkeypatch):
        calls: list[dict] = []

        class _FakeNotification:
            def __init__(self, app_id, title, msg):
                calls.append({"app_id": app_id, "title": title, "msg": msg})

            def show(self):
                calls[-1]["shown"] = True

        fake_mod = types.ModuleType("winotify")
        fake_mod.Notification = _FakeNotification
        monkeypatch.setitem(sys.modules, "winotify", fake_mod)

        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.ToastRenderer(engine)
        v = _view("api", "/a", "needs-input")

        r.render([v], [_trans(v, "working")])

        assert calls == [
            {
                "app_id": "multideck",
                "title": "multideck: api",
                "msg": "needs-input — waiting on you",
                "shown": True,
            }
        ]

    def test_debounced_within_window(self, monkeypatch):
        calls: list[str] = []

        class _FakeNotification:
            def __init__(self, app_id, title, msg):
                calls.append(title)

            def show(self):
                pass

        fake_mod = types.ModuleType("winotify")
        fake_mod.Notification = _FakeNotification
        monkeypatch.setitem(sys.modules, "winotify", fake_mod)

        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.ToastRenderer(engine)
        v = _view("api", "/a", "needs-input")

        r.render([v], [_trans(v, "working")])
        r.render([v], [_trans(v, "working")])

        assert len(calls) == 1

    def test_show_failure_logs_warning_and_survives(self, monkeypatch, caplog):
        # P6-02: a winotify .show() fault (COM hiccup, Focus Assist, quota) must
        # be caught and logged as a WARNING, not propagate and kill the daemon.
        class _FakeNotification:
            def __init__(self, app_id, title, msg):
                pass

            def show(self):
                raise RuntimeError("COM boom")

        fake_mod = types.ModuleType("winotify")
        fake_mod.Notification = _FakeNotification
        monkeypatch.setitem(sys.modules, "winotify", fake_mod)

        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.ToastRenderer(engine)
        v = _view("api", "/a", "needs-input")

        import logging

        with caplog.at_level(logging.WARNING, logger="multideck.attention"):
            r.render([v], [_trans(v, "working")])  # must not raise

        assert "toast failed" in caplog.text


class TestNtfyRenderer:
    def test_posts_transition_to_topic(self, monkeypatch):
        seen: list = []

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            seen.append((req.full_url, req.data, req.get_method()))
            return _FakeResp()

        monkeypatch.setattr(attention.urllib.request, "urlopen", fake_urlopen)
        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.NtfyRenderer(engine, "https://ntfy.example.com/topic")
        v = _view("api", "/a", "error")

        r.render([v], [_trans(v, "working")])

        assert seen == [("https://ntfy.example.com/topic", b"api: error", "POST")]

    def test_failure_logs_warning_and_survives(self, monkeypatch, caplog):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("unreachable")

        monkeypatch.setattr(attention.urllib.request, "urlopen", fake_urlopen)
        engine = AttentionEngine(now=FakeClock(1000.0))
        r = attention.NtfyRenderer(engine, "https://ntfy.example.com/topic")
        v = _view("api", "/a", "needs-input")

        import logging

        with caplog.at_level(logging.WARNING, logger="multideck.attention"):
            r.render([v], [_trans(v, "working")])

        assert "ntfy push failed" in caplog.text


class TestRunAttentionLoop:
    def test_ticks_render_heartbeat_and_sleep_between(self, state_dir):
        _write_record(state_dir, "/a", agent_state.WORKING, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))
        rendered: list[int] = []
        ticked: list[int] = []
        slept: list[float] = []

        class _Recorder:
            def render(self, views, transitions):
                rendered.append(len(views))

        attention.run_attention_loop(
            engine,
            [_Recorder()],
            poll_interval=2.0,
            max_ticks=2,
            sleep=slept.append,
            on_tick=lambda views: ticked.append(len(views)),
        )

        assert rendered == [1, 1]
        assert ticked == [1, 1]
        assert slept == [2.0]  # sleeps BETWEEN ticks, not after the last

    def test_logs_each_state_transition(self, state_dir, caplog):
        # WIN: the audit trail -- one INFO line per state change (project +
        # old -> new) in the "attention" log.
        _write_record(state_dir, "/api", agent_state.WORKING, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))

        import logging

        with caplog.at_level(logging.INFO, logger="multideck.attention"):
            attention.run_attention_loop(engine, [], max_ticks=1, sleep=lambda _s: None)

        assert "api" in caplog.text
        assert "new -> working" in caplog.text

    def test_toast_fault_does_not_stop_later_renderers(
        self, monkeypatch, state_dir, caplog
    ):
        # P6-02 at the loop level: a toast that raises must not prevent the
        # renderers after it from running on that same tick.
        class _FakeNotification:
            def __init__(self, app_id, title, msg):
                pass

            def show(self):
                raise RuntimeError("COM boom")

        fake_mod = types.ModuleType("winotify")
        fake_mod.Notification = _FakeNotification
        monkeypatch.setitem(sys.modules, "winotify", fake_mod)

        _write_record(state_dir, "/api", agent_state.NEEDS_INPUT, 999.0)
        engine = AttentionEngine(now=FakeClock(1000.0))
        toast = attention.ToastRenderer(engine)
        rendered: list[int] = []

        class _Recorder:
            def render(self, views, transitions):
                rendered.append(len(views))

        import logging

        with caplog.at_level(logging.WARNING, logger="multideck.attention"):
            attention.run_attention_loop(
                engine, [toast, _Recorder()], max_ticks=1, sleep=lambda _s: None
            )

        assert rendered == [1]  # the recorder ran despite the toast fault
        assert "toast failed" in caplog.text
