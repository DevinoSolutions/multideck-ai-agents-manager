from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from multideck.sessions.claude import build_claude_resume, get_claude_session_ids
from multideck.sessions.codex import build_codex_resume, get_codex_session_ids

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class AgentTool:
    """Per-tool capabilities of a CLI agent (claude, codex, ...)."""
    session_ids: Callable[[str, int], list[str | None]] | None = None
    resume_command: Callable[[str, str | None], str] | None = None
    happy: bool = False  # can be wrapped with `happy` for mobile access

    @property
    def multi_window(self) -> bool:
        return self.session_ids is not None


AGENT_TOOLS: dict[str, AgentTool] = {
    "claude": AgentTool(session_ids=get_claude_session_ids,
                        resume_command=build_claude_resume, happy=True),
    "codex": AgentTool(session_ids=get_codex_session_ids,
                       resume_command=build_codex_resume, happy=True),
}


def build_resume_command(tool: str, base_cmd: str, session_id: str | None) -> str:
    caps = AGENT_TOOLS.get(tool)
    if caps and caps.resume_command:
        return caps.resume_command(base_cmd, session_id)
    return base_cmd
