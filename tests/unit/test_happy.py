from multideck.launch import _wrap_happy, HAPPY_AGENTS


class TestWrapHappy:
    def test_wraps_claude(self):
        assert _wrap_happy("claude", "claude --continue") == "happy claude"

    def test_wraps_codex(self):
        assert _wrap_happy("codex", "codex") == "happy codex"

    def test_passthrough_unsupported_tool(self):
        assert _wrap_happy("agy", "agy") == "agy"

    def test_passthrough_cursor_agent(self):
        assert _wrap_happy("cursor-agent", "cursor-agent") == "cursor-agent"

    def test_happy_agents_contains_expected(self):
        assert "claude" in HAPPY_AGENTS
        assert "codex" in HAPPY_AGENTS
