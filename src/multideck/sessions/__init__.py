from __future__ import annotations

import re


def build_resume_command(tool: str, base_cmd: str, session_id: str | None) -> str:
    if tool == "claude":
        stripped = re.sub(r"--continue\s*", "", base_cmd)
        stripped = re.sub(r"--resume\s+\S+", "", stripped).strip()
        if session_id:
            return f"{stripped} --resume {session_id}"
        return stripped

    if tool == "codex":
        parts = base_cmd.split(None, 1)
        binary = parts[0]
        if session_id:
            return f"{binary} resume {session_id}"
        return base_cmd

    return base_cmd
