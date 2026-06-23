import os
import pytest
from multideck.sessions.claude import encode_claude_project_path, get_claude_session_ids


class TestEncodeClaudeProjectPath:
    def test_windows_path(self):
        result = encode_claude_project_path(
            r"C:\Users\amind\OneDrive\Desktop\Projects\CUSTOM MCPs & PRODUCTIVITY\multideck-ai-agent"
        )
        assert result == "C--Users-amind-OneDrive-Desktop-Projects-CUSTOM-MCPs---PRODUCTIVITY-multideck-ai-agent"

    def test_unix_path(self):
        result = encode_claude_project_path("/home/user/code/my-project")
        assert result == "-home-user-code-my-project"

    def test_preserves_dots_and_dashes(self):
        result = encode_claude_project_path("my-project.v2")
        assert result == "my-project.v2"

    def test_spaces_become_dashes(self):
        result = encode_claude_project_path("my project")
        assert result == "my-project"

    def test_consecutive_special_chars_not_collapsed(self):
        result = encode_claude_project_path("a&&b")
        assert result == "a--b"


class TestGetClaudeSessionIds:
    def test_returns_ids_sorted_by_mtime(self, fake_claude_sessions):
        home = getattr(fake_claude_sessions, "__wrapped_tmp")
        encoded = "test-project"
        fake_claude_sessions(encoded, [
            ("uuid-oldest", 1000.0),
            ("uuid-newest", 3000.0),
            ("uuid-middle", 2000.0),
        ])
        ids = get_claude_session_ids("test-project", 3, home_override=home)
        assert ids == ["uuid-newest", "uuid-middle", "uuid-oldest"]

    def test_returns_fewer_than_requested(self, fake_claude_sessions):
        home = getattr(fake_claude_sessions, "__wrapped_tmp")
        encoded = "test-project"
        fake_claude_sessions(encoded, [("uuid-1", 1000.0), ("uuid-2", 2000.0)])
        ids = get_claude_session_ids("test-project", 5, home_override=home)
        assert ids == ["uuid-2", "uuid-1", None, None, None]

    def test_empty_dir(self, fake_claude_sessions):
        home = getattr(fake_claude_sessions, "__wrapped_tmp")
        fake_claude_sessions("test-project", [])
        ids = get_claude_session_ids("test-project", 3, home_override=home)
        assert ids == [None, None, None]

    def test_no_dir_exists(self, tmp_path):
        ids = get_claude_session_ids("nonexistent", 2, home_override=tmp_path)
        assert ids == [None, None]

    def test_count_one(self, fake_claude_sessions):
        home = getattr(fake_claude_sessions, "__wrapped_tmp")
        encoded = "test-project"
        fake_claude_sessions(encoded, [("uuid-1", 1000.0), ("uuid-2", 2000.0)])
        ids = get_claude_session_ids("test-project", 1, home_override=home)
        assert ids == ["uuid-2"]
