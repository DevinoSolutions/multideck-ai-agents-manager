# multideck — SSH / Remote support

**Status:** Approved design — 2026-06-17
**Branch:** `feat/ssh-remote-support`
**Scope:** Add optional remote execution so a project can run its agent (Claude Code / Codex / any CLI) or open in VS Code **on a remote machine over SSH**, while local projects and all tiling behavior stay exactly as today.

## Summary

multideck currently launches each enabled project in its own Windows Terminal window (or VS Code), `cd`'d into a local folder, then tiles the windows across monitors by title. This feature adds an optional `host` to a project. When present, multideck connects to that host over SSH instead of running locally:

- **CLI agents** (claude, codex, any `settings.tools` entry): open a Windows Terminal that runs `ssh -t <host> "<login-shell> 'cd <remoteDir> && <toolcmd>'"`.
- **VS Code** (`tool: "code"`): open VS Code Remote-SSH auto-connected to the remote folder via `code --remote ssh-remote+<host> "<remoteDir>"`.

The same `host` serves all three — the user chooses claude, codex, or VS Code per project via `tool`. The tiler is untouched: it still finds and snaps windows by title, regardless of what runs inside them.

## Goals

- A single project targets a remote host with one extra field (`host`).
- The same `host` works for claude, codex, and VS Code; the user picks per project via `tool`.
- Reuse `path` as the remote directory; allow `remotePath` only when the remote dir differs.
- Remote tools resolve on PATH reliably (login-shell wrap by default).
- Zero change to local-project behavior, tiling, DPI handling, groups, menu, and `-Init`.

## Non-goals (out of scope for v1)

- Scanning `~/.ssh/config` to auto-generate entries — hosts are typed into the config.
- VS Code **Remote Tunnels** (`code tunnel`, account-brokered). We use **Remote-SSH** only.
- Password automation. Auth relies on the user's existing SSH keys / agent. Interactive password prompts still work — they appear in the terminal and pause for input.
- Remote-side installation of the agents. claude/codex/VS Code Server must already exist on the remote.

## Config schema

### New project fields

| Key | Type | Required | Meaning |
|---|---|---|---|
| `host` | string | no | SSH target passed verbatim to `ssh` / Remote-SSH: `user@ip`, `user@hostname`, or an ssh alias. **Presence makes the project remote.** |
| `remotePath` | string | no | Remote working directory, **only when it differs from `path`**. Resolution: `remoteDir = remotePath ?? path`. For `tool:"code"` it should be an absolute remote path. |

`path` stays required (it is the project's identity and the source of the default title/label). For a remote project, `path` is **not** checked against the local filesystem.

### New setting

| Key | Default | Meaning |
|---|---|---|
| `settings.ssh.shell` | `"bash -lc"` | Login-shell wrapper for remote CLI commands so the remote profile (PATH for nvm/asdf/Homebrew/`~/.local/bin`) is sourced. Set to `"sh -lc"`, `"zsh -lc"`, etc., or `""` to disable wrapping and run the command directly. |

### Example

```jsonc
{
  "baseDir": "C:/Users/you/code",
  "layout": { "columns": 2, "rows": 1 },
  "settings": {
    "defaultTool": "claude",
    "settleSeconds": 3,
    "launchDelayMs": 400,
    "ssh": { "shell": "bash -lc" },
    "tools": { "claude": "claude --continue", "codex": "codex --yolo" }
  },
  "projects": [
    { "path": "internal/api", "color": "#3b82f6" },                                       // local claude
    { "host": "deploy@10.0.0.5", "path": "/srv/api", "tool": "codex", "color": "#22c55e" }, // remote codex
    { "host": "ubuntu@vm-2", "path": "api", "remotePath": "/home/ubuntu/work/api", "tool": "code" } // remote VS Code
  ]
}
```

## Behavior

### Dispatch

For each enabled project with a `path`:

```
name      = title ?? basename(path)
tool      = tool ?? defaultTool
isRemote  = host is set

if isRemote:
    remoteDir = remotePath ?? path
    if tool == "code":  -> VS Code Remote-SSH   (match: title-contains basename(remoteDir))
    else:               -> ssh terminal         (match: exact title == name)
    # local filesystem existence check is SKIPPED
else:
    # unchanged: resolve local dir under baseDir, Test-Path, then code/terminal branch
```

### CLI agents over SSH

Window command:

```
wt -w new --title "<name>" [--tabColor "<color>"] --suppressApplicationTitle -- cmd /k ssh -t <host> "<remote>"
```

where `<remote>` is, with `settings.ssh.shell = "bash -lc"`:

```
bash -lc 'cd <remoteDir> && <toolcmd>'
```

or, with `settings.ssh.shell = ""`:

```
cd <remoteDir> && <toolcmd>
```

- `ssh -t` allocates a TTY so the interactive agent renders correctly.
- The outer `cmd /k` keeps the **window open** if SSH drops or the agent exits, so the tile is not lost and the session can be restarted — the same persistence the local `cmd /k` already provides.
- No `-d` flag (that is for local directories).

### VS Code over Remote-SSH

Launched as an argument array (avoids nested quoting):

```
cmd /c code --remote ssh-remote+<host> "<remoteDir>"
```

- Auto-connects to `<host>` and opens `<remoteDir>` (absolute) — "open VS Code already connected to the project."
- Requires the **Remote-SSH** extension and that VS Code can resolve `<host>` (it accepts `user@ip` as well as ssh-config aliases).
- Tiling matches by the remote folder basename contained in the window title (VS Code shows `<folder> [SSH: <host>]`), the same contains-match used for local VS Code today.

### Local projects

Completely unchanged.

### Window persistence & failure

- Remote terminal windows survive disconnects / agent-exit via `cmd /k` (land back at a local prompt; reconnect by re-running the ssh line).
- A failed SSH (bad host/key) prints the error in the kept-open window; the window still tiles, so failures are visible rather than vanishing.

### Tiling

No changes. Slots, DPI handling, `-RetileAll`, and the multi-monitor grid all operate on window handles by title as today. Remote `code` may connect slowly; `settleSeconds` already governs the wait before tiling and can be raised.

### Dry-run

`-DryRun` annotates remote targets and launches nothing:

```
NEW: api   [codex @ deploy@10.0.0.5:/srv/api]
NEW: api   [code  @ ssh-remote+ubuntu@vm-2:/home/ubuntu/work/api]
```

Tiling preview lines are unchanged.

## Edge cases & validation

- **No `ssh` client:** soft-check `Get-Command ssh` once when any remote project exists; warn. (Windows 10+ ships the OpenSSH client; the user may need to enable it.)
- **`remotePath` for `code`:** should be absolute; a relative remote path may not resolve under Remote-SSH. Documented, not hard-enforced.
- **Quoting:** the remote dir/command are embedded in `"…"` (ssh) and `'…'` (login shell). Paths containing single quotes are unsupported in v1 (documented). Command construction is isolated in a pure helper for testing.
- **VS Code basename collisions:** two remote `code` projects whose remote folders share a basename (e.g. `/srv/app` on two servers) both match the same title needle, so tiling may grab the wrong one — the same limitation as duplicate local `code` folders today. Workaround: distinct folder leaves. Terminal tools are unaffected (exact title match).
- **Unknown tool + host:** falls through to the existing "unknown tool" skip.

## Testing

- **Unit (Pester):** extract command construction into pure functions (e.g. `Build-MdSshPayload`, `Build-MdCodeArgs`) that return strings/arrays and launch nothing. Cover:
  - `remoteDir` = `remotePath` when set, else `path`.
  - login-shell wrap applied when `settings.ssh.shell` is set; raw when empty.
  - correct `ssh -t <host>` and embedded command.
  - VS Code arg array = `code --remote ssh-remote+<host> <remoteDir>`.
  - local path construction unchanged (regression).
- **Manual smoke test:** add a project targeting a reachable host (e.g. `ssh localhost` or a VM) for each of claude / codex / code; verify the window opens, connects, runs the agent, and tiles. Record steps in the PR.

## Files touched

- `scripts/multideck.ps1` — schema parse, dispatch branch, command builders, dry-run annotation, soft ssh check. (`$repoRoot` is already available in the script after the recent `scripts/` move.)
- `multideck.config.example.json` — `settings.ssh.shell` + one remote example project.
- `README.md` — `host` / `remotePath` / `settings.ssh.shell` docs, VS Code Remote-SSH behavior, requirements (OpenSSH client, Remote-SSH extension), troubleshooting entries.
- `tests/multideck.Tests.ps1` *(new)* — Pester tests for the pure command builders.
