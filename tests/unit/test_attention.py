"""Unit tests for the attention engine (multideck.attention) and the
agent_state store additions it reads (all_states, norm_cwd).

Everything runs against a tmp_path STATE_DIR and a fake clock — no real
time, no platform, no daemon.
"""

from __future__ import annotations

import json

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
