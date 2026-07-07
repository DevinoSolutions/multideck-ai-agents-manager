"""Unit tests for the AGENT_TOOLS registry (R8, F-CT-001): the registry's
shape, HAPPY_AGENTS' derivation from it, and the "adding a tool is one dict
entry" proof that is the whole point of the refactor.
"""

from __future__ import annotations

from multideck.launch import HAPPY_AGENTS
from multideck.sessions import AGENT_TOOLS, AgentTool, build_resume_command


class TestRegistryShape:
    def test_registered_tools(self):
        assert set(AGENT_TOOLS) == {"claude", "codex"}

    def test_all_entries_are_happy(self):
        assert all(caps.happy is True for caps in AGENT_TOOLS.values())

    def test_all_entries_are_multi_window(self):
        assert all(caps.multi_window is True for caps in AGENT_TOOLS.values())

    def test_happy_agents_derived_from_registry(self):
        assert {t for t, c in AGENT_TOOLS.items() if c.happy} == HAPPY_AGENTS


class TestOneEditExtensionProof:
    def test_adding_a_tool_is_one_dict_entry(self, monkeypatch):
        """Adding tool support is one new AGENT_TOOLS entry -- the dispatcher
        (build_resume_command) needs no code change to pick it up."""
        extended = dict(
            AGENT_TOOLS,
            mytool=AgentTool(
                resume_command=lambda base, session: f"{base} R {session}",
            ),
        )
        monkeypatch.setattr("multideck.sessions.AGENT_TOOLS", extended)

        assert (
            build_resume_command("mytool", "mytool run", "id-1") == "mytool run R id-1"
        )

    def test_new_entry_defaults_are_unset(self):
        """A minimal AgentTool (no session_ids/happy) is a valid, inert entry --
        confirms the dataclass's defaults, not just the fields this repo's two
        tools happen to fill in."""
        minimal = AgentTool()
        assert minimal.session_ids is None
        assert minimal.resume_command is None
        assert minimal.happy is False
        assert minimal.multi_window is False
