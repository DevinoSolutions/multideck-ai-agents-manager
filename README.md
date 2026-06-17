# multideck-ai-agent

**Open every project in its own terminal — running Claude Code, Codex, or any CLI agent — and auto-tile them into a grid across all your monitors. One config file. DPI-correct on mixed-scale setups.**

![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D6?logo=windows)
![shell](https://img.shields.io/badge/PowerShell-5.1%2B-5391FE?logo=powershell&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green)

```
        Monitor 1  (4K @ 250%)         Monitor 2  (4K @ 250%)        Monitor 3 (1080p @ 175%)
     ┌────────────┬────────────┐    ┌────────────┬────────────┐    ┌─────────┬─────────┐
     │   api      │   web      │    │   infra    │   docs     │    │  ops    │   …     │
     │  [claude]  │  [claude]  │    │  [codex]   │  [code]    │    │ [claude]│         │
     └────────────┴────────────┘    └────────────┴────────────┘    └─────────┴─────────┘
                       columns × rows per screen · true physical pixels on every monitor
```

You run one command. Each project opens in its own titled, color-tabbed terminal, already `cd`'d into the right folder with your agent running — then every window snaps into a clean grid spanning all your screens.

---

## Why

If you juggle a fleet of repos with terminal AI agents (Claude Code, Codex, aider, …), you waste minutes every morning opening terminals, `cd`-ing around, starting the agent, and dragging windows into place. `multideck` makes that a single double-click — and unlike manual snapping or most tilers, it gets the geometry **right on monitors that run different display scales** (the usual reason auto-tiling drifts or leaves gaps).

## Features

- 🗂 **One window per project**, titled and color-tabbed, opened directly in its folder.
- 🤖 **Any CLI agent** — Claude Code and Codex out of the box; add your own in one line.
- 🪟 **VS Code support** — projects can open in VS Code instead of a terminal.
- 🧮 **Configurable grid** — `columns × rows` per screen, spanning every monitor.
- 📐 **DPI-correct** — per-monitor-aware, so a 175% laptop screen next to 250% 4K monitors tiles perfectly (see [How DPI works](#how-the-dpi-handling-works)).
- ✨ **Zero-typing setup** — point `-Init` at a folder and it scans your git repos and writes the config for you, with groups and colors filled in.
- 🏷 **Groups** — tag projects and launch just one set: `multideck -Group lead-gen`.
- 🧭 **Interactive menu** — run with no arguments for a friendly menu; no flags to memorize.
- ♻️ **Idempotent** — re-running only opens what's missing; `-RetileAll` re-snaps everything.
- 👀 **`-DryRun`** — preview the whole plan before anything launches.
- 🔒 **Your config stays local** — `multideck.config.json` is git-ignored; only the example ships.

## Requirements

- **Windows 10 (1703+) or 11**
- **[Windows Terminal](https://aka.ms/terminal)** (`wt`) — for terminal-based tools
- **Windows PowerShell 5.1** (built in) or PowerShell 7+
- Whatever you launch: the **[Claude Code](https://www.anthropic.com/claude-code)** CLI, **Codex**, **[VS Code](https://code.visualstudio.com/)** (`code` on PATH), etc.
- For **remote projects**: the **OpenSSH client** (`ssh` on PATH — built into Windows 10/11, enable via *Settings → System → Optional features*), key-based auth set up for the host, and for remote VS Code the **[Remote-SSH extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh)**.

## Install

```powershell
git clone https://github.com/DevinoSolutions/multideck-ai-agent.git
cd multideck-ai-agent
```

**Option A — run from anywhere (recommended):** double-click **`install.bat`** (or run `.\scripts\install.ps1`). It adds the folder to your user PATH and drops **Desktop + Start-Menu shortcuts**, so you can type `multideck` in any terminal or double-click an icon. Reversible any time with `uninstall.bat`. *(Open a new terminal afterwards so PATH refreshes.)*

**Option B — run in place:** skip the installer and just call `.\multideck.bat` from the repo folder.

> The examples below use `multideck`; if you didn't install, use `.\multideck.bat` instead.

## First run — build your config

**Let it scan for you** (no JSON by hand):

```powershell
multideck -Init -BaseDir C:\code     # scans C:\code for git repos, writes multideck.config.json
multideck -DryRun                    # preview, then:
multideck
```

`-Init` walks the folder, finds git repositories (a few levels deep), and writes a config with **groups derived from the top folder** (`internal/api` → group `internal`), auto-assigned tab colors, and unique titles. Just run with no `-BaseDir` and it'll ask which folder to scan — in fact, the very first time you run `multideck` with no config, it offers to do this for you.

**Or edit by hand:** copy `multideck.config.example.json` to `multideck.config.json` and tweak it.

## Everyday use

Run **`multideck`** with no arguments for the menu:

```
  multideck
  =========
   1) Launch missing + tile new windows   (default)
   2) Re-tile ALL open windows
   3) Launch a group   (internal, infra, lead-gen)
   4) Dry run (preview, change nothing)
   5) Re-generate config from a folder scan
   Q) Quit
```

Or skip the menu with flags:

| Command | What it does |
| --- | --- |
| `multideck` | Interactive menu (press **Enter** for the default: launch + tile new). |
| `multideck -Go` | Launch any projects that aren't open, then tile the **new** windows — no menu. |
| `multideck -RetileAll` | Re-tile **every** matching window — already-open ones too. (`multideck-retile.bat`) |
| `multideck -Group <name>` | Launch only the projects in that group. |
| `multideck -DryRun` | Print the launch + tiling plan and exit. Touches nothing. |
| `multideck -Init -BaseDir <folder>` | Generate `multideck.config.json` by scanning a folder. |
| `multideck -Config <path>` | Use a different config file. |

Flags combine, e.g. `multideck -Group infra -DryRun` or `multideck -Init -BaseDir C:\code -DryRun`.

## Configuration

Everything lives in `multideck.config.json` (generate it with `-Init`, or copy `multideck.config.example.json`):

```jsonc
{
  "baseDir": "C:/Users/you/code",            // root that relative project paths join onto

  "layout": { "columns": 2, "rows": 1 },     // tiles per screen

  "settings": {
    "defaultTool": "claude",                  // tool used when a project omits "tool"
    "settleSeconds": 3,                       // wait for new windows before moving them
    "launchDelayMs": 400,                     // pause between launches
    "tools": {                                // command run inside Windows Terminal, per tool
      "claude": "claude --continue",
      "codex":  "codex --yolo"
    }
  },

  "projects": [
    { "path": "internal/api",  "group": "internal", "color": "#3b82f6" },
    { "path": "internal/web",  "group": "internal", "color": "#22c55e" },
    { "path": "infra/tf",      "group": "infra",    "color": "#f59e0b", "tool": "codex" },
    { "path": "docs",          "group": "internal", "color": "#a855f7", "tool": "code"  },
    { "path": "labs/spike",    "group": "labs",     "color": "#ef4444", "enabled": false },
    { "path": "C:/work/ops",   "title": "ops" }
  ]
}
```

> Paths accept **forward slashes** (`internal/api`) — no `\\` escaping needed. `%ENV%` vars and `~` work too.

### Fields

| Key | Where | Default | Meaning |
| --- | --- | --- | --- |
| `baseDir` | top level | repo root | Root that **relative** project `path`s join onto. |
| `layout.columns` / `layout.rows` | top level | `2` / `1` | Tiles per screen. `2×1` = halves; `2×2` = quadrants; `3×1` = thirds; `1×1` = maximized. |
| `settings.defaultTool` | settings | `claude` | Tool for projects that don't set their own `tool`. |
| `settings.settleSeconds` | settings | `3` | Seconds to wait after launching before tiling (only when something launched). |
| `settings.launchDelayMs` | settings | `400` | Delay between launches so windows register in order. |
| `settings.tools` | settings | claude, codex | Map of tool name → command run inside Windows Terminal. |
| `settings.ssh.shell` | settings | `bash -lc` | Login shell that wraps remote agent commands so the remote `PATH` is sourced. Set `""` to run unwrapped, or e.g. `sh -lc` / `zsh -lc`. |
| `path` | project | — *(required)* | Absolute, or relative to `baseDir`. Forward slashes OK. |
| `group` | project | none | Tag for `-Group` subset launches. |
| `tool` | project | `defaultTool` | Which tool to launch. Use `"code"` to open in VS Code instead of a terminal. |
| `color` | project | none | Windows Terminal tab color (`#rrggbb`). |
| `title` | project | folder name | Window title + the key used to find the window for tiling. Keep titles unique. |
| `enabled` | project | `true` | Set `false` to skip a project without deleting it. |
| `host` | project | none | SSH target (`user@ip`, `user@host`, or an ssh-config alias). When set, the project runs **remotely** — the agent starts over `ssh`, or VS Code opens via Remote-SSH. |
| `remotePath` | project | `path` | Remote working directory, only needed when it differs from `path`. For `tool:"code"`, use an absolute remote path. |

## Layout examples

```jsonc
"layout": { "columns": 2, "rows": 1 }   // two columns per screen  (the default)
"layout": { "columns": 3, "rows": 1 }   // three columns per screen
"layout": { "columns": 2, "rows": 2 }   // four quadrants per screen
"layout": { "columns": 1, "rows": 1 }   // one maximized window per screen
```

Windows fill slots in list order, left-to-right then top-to-bottom, cycling across screens. List more projects than slots and later windows stack on the same slot — just like opening more than fit.

## Groups

Tag related projects and launch them as a set:

```jsonc
{ "path": "lead-gen/upwork",   "group": "lead-gen" },
{ "path": "lead-gen/wellfound","group": "lead-gen" }
```

```powershell
multideck -Group lead-gen     # opens + tiles just that group
```

`-Init` fills `group` in for you from the top folder of each repo, so a `lead-gen/…` layout is grouped automatically. Menu option **3** lists your groups to pick from.

## Adding your own agent / tool

Anything that runs in a terminal works — add a line to `settings.tools`, then reference it per project:

```jsonc
"settings": {
  "tools": {
    "claude": "claude --continue",
    "codex":  "codex --yolo",
    "aider":  "aider --model sonnet",
    "shell":  "powershell"
  }
},
"projects": [
  { "path": "ml-service", "tool": "aider" },
  { "path": "scratch",    "tool": "shell" }
]
```

The command runs via `cmd /k <command>` inside a fresh Windows Terminal tab opened in the project folder. The special tool name `code` is handled separately — it launches VS Code in its own window and matches that window by title.

## Remote projects over SSH

Any project can run on a remote machine instead of locally — just add a `host`. The same host works for Claude Code, Codex, or VS Code; pick per project with `tool`:

```jsonc
"projects": [
  { "host": "deploy@10.0.0.5", "path": "/srv/api", "tool": "claude" },          // claude over ssh
  { "host": "deploy@10.0.0.5", "path": "/srv/web", "tool": "codex"  },          // codex over ssh
  { "host": "ubuntu@vm-2", "path": "api", "remotePath": "/home/ubuntu/work/api", "tool": "code" } // VS Code Remote-SSH
]
```

- **`host`** is whatever you'd type after `ssh` — `user@ip`, `user@hostname`, or a `~/.ssh/config` alias. Auth uses your existing SSH keys / agent (multideck never handles passwords; a password prompt simply appears in the terminal).
- **CLI agents** open a Windows Terminal running `ssh -t <host> "bash -lc 'cd <dir> && <tool command>'"`. The login-shell wrap (`settings.ssh.shell`, default `bash -lc`) ensures tools installed via nvm/asdf/Homebrew are found; set it to `""` to disable, or to `sh -lc` / `zsh -lc` for other shells. If SSH drops or the agent exits, the window stays open at a local prompt so the tile isn't lost.
- **VS Code** opens already connected via Remote-SSH: `code --remote ssh-remote+<host> <remoteDir>`. Requires the [Remote-SSH extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh). Use an **absolute** `remotePath` for `code`.
- **`remotePath`** overrides the remote directory when it differs from `path`; otherwise `path` is used as the remote directory.
- Remote windows tile exactly like local ones (by title). Remote `code` connects asynchronously — raise `settleSeconds` if it tiles before the window is ready.

Remote and local projects mix freely in one config, and `-Group remote` launches just your remote set.

## How the DPI handling works

Naïve window tilers read monitor sizes and call `MoveWindow` from a **DPI-unaware** process. Windows then hands back a *virtualized* 96-DPI coordinate space, so a 4K monitor at 250% reports as `1536×864` and a 1080p screen at 175% reports as `1097×617`. The half-screen math is computed in that fake space, and on any monitor whose scale differs from the primary the rectangle gets mis-scaled — windows land too small, with gaps.

`multideck` flips the launcher to **Per-Monitor-DPI-Aware (V2)** *before* it reads any screen, so `Screen.AllScreens` and `MoveWindow` work in **true physical pixels per monitor**:

| Monitor | DPI-unaware (wrong) | Per-Monitor V2 (multideck) |
| --- | --- | --- |
| 4K @ 250% | `1536 × 864` | `3840 × 2160` |
| 1080p @ 175% | `1097 × 617` | `1920 × 1080` |

The grid is then computed in real pixels and is correct on every screen regardless of its scale.

## Troubleshooting

- **`No config found`** — run `multideck -Init -BaseDir <folder>`, or copy `multideck.config.example.json` to `multideck.config.json`.
- **`multideck` not recognized after install** — open a **new** terminal so the updated PATH loads.
- **`Not found: <name>` when tiling** — the window title didn't match. Titles must be unique (`-Init` auto-disambiguates duplicates); if a tool overrides its own title, set a `title` and raise `settleSeconds`.
- **A project is skipped** — its folder doesn't exist under `baseDir` (the path is printed), or `enabled` is `false`.
- **`wt` not recognized** — install [Windows Terminal](https://aka.ms/terminal).
- **Remote window opens then closes / agent "not found"** — the remote tool isn't on the non-login `PATH`. Keep the default `settings.ssh.shell` of `bash -lc` (login-shell wrap), or set it to your remote shell. The window stays at a local prompt so you can read the error.
- **`ssh` not recognized** — enable the Windows OpenSSH client (*Settings → System → Optional features → Add → OpenSSH Client*).
- **Remote VS Code doesn't connect** — install the Remote-SSH extension and confirm `ssh <host>` works from a normal terminal first; use an absolute `remotePath`.
- **Nothing tiles on re-run** — by design, a plain run only positions windows it just opened. Use `-RetileAll` (or `multideck-retile.bat`) to re-snap windows that were already open.
- **Scripts blocked** — the `.bat` files already pass `-ExecutionPolicy Bypass`; run those rather than the `.ps1` directly.

## License

MIT © [Devino Solutions](https://devino.ca)
