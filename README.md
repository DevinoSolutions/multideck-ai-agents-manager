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
- ♻️ **Idempotent** — re-running only opens what's missing; `-RetileAll` re-snaps everything.
- 👀 **`-DryRun`** — preview the whole plan before anything launches.
- 🔒 **Your config stays local** — `multideck.config.json` is git-ignored; only the example ships.

## Requirements

- **Windows 10 (1703+) or 11**
- **[Windows Terminal](https://aka.ms/terminal)** (`wt`) — for terminal-based tools
- **Windows PowerShell 5.1** (built in) or PowerShell 7+
- Whatever you launch: the **[Claude Code](https://www.anthropic.com/claude-code)** CLI, **Codex**, **[VS Code](https://code.visualstudio.com/)** (`code` on PATH), etc.

## Quick start

```powershell
git clone https://github.com/DevinoSolutions/multideck-ai-agent.git
cd multideck-ai-agent

# 1. create your personal config from the example
copy multideck.config.example.json multideck.config.json

# 2. edit it — set baseDir and list your projects
notepad multideck.config.json

# 3. preview, then go
.\multideck.bat -DryRun
.\multideck.bat
```

> 💡 Pin `multideck.bat` (launch + tile new) and `multideck-retile.bat` (re-tile everything) to your taskbar or drop shortcuts on your desktop — both are double-click friendly.

## Commands

| Command | What it does |
| --- | --- |
| `multideck.bat` | Launch any projects that aren't open yet, then tile the **new** windows. |
| `multideck.bat -RetileAll` | Re-tile **every** matching window — already-open ones too. |
| `multideck-retile.bat` | Shortcut for `-RetileAll`. Re-snap the whole grid after plugging/unplugging a monitor. |
| `multideck.bat -DryRun` | Print the launch + tiling plan and exit. Touches nothing. |
| `multideck.bat -Config path\to\other.json` | Use a different config (e.g. a "frontend only" layout). |

Flags combine: `multideck.bat -RetileAll -DryRun` previews a full re-tile.

## Configuration

Everything lives in `multideck.config.json` (copy it from `multideck.config.example.json`):

```jsonc
{
  "baseDir": "C:\\Users\\you\\code",       // root that relative project paths join onto

  "layout": {
    "columns": 2,                            // tiles across each screen
    "rows": 1                                // tiles down each screen
  },

  "settings": {
    "defaultTool": "claude",                 // tool used when a project omits "tool"
    "settleSeconds": 3,                      // wait for new windows to appear before moving them
    "launchDelayMs": 400,                    // pause between launches
    "tools": {                               // command run inside Windows Terminal, per tool
      "claude": "claude --continue",
      "codex":  "codex --yolo"
    }
  },

  "projects": [
    { "path": "api",                   "color": "#3b82f6" },
    { "path": "web",                   "color": "#22c55e" },
    { "path": "infra",                 "color": "#f59e0b", "tool": "codex" },
    { "path": "docs",                  "color": "#a855f7", "tool": "code"  },
    { "path": "experiments\\spike",    "color": "#ef4444", "enabled": false },
    { "path": "C:\\work\\ops-scripts", "title": "ops" }
  ]
}
```

### Fields

| Key | Where | Default | Meaning |
| --- | --- | --- | --- |
| `baseDir` | top level | script folder | Root that **relative** project `path`s are joined onto. Supports `%ENV%` and `~`. |
| `layout.columns` / `layout.rows` | top level | `2` / `1` | Tiles per screen. `2×1` = left/right halves; `2×2` = quadrants; `3×1` = thirds. |
| `settings.defaultTool` | settings | `claude` | Tool for projects that don't set their own `tool`. |
| `settings.settleSeconds` | settings | `3` | Seconds to wait after launching before tiling (only when something launched). |
| `settings.launchDelayMs` | settings | `400` | Delay between launches so windows register in order. |
| `settings.tools` | settings | claude, codex | Map of tool name → command run inside Windows Terminal. |
| `path` | project | — *(required)* | Absolute, or relative to `baseDir`. The folder the tool opens in. |
| `tool` | project | `defaultTool` | Which tool to launch. Use `"code"` to open in VS Code instead of a terminal. |
| `color` | project | none | Windows Terminal tab color (`#rrggbb`). |
| `title` | project | folder name | Window title and the key used to find the window for tiling. Keep titles unique. |
| `enabled` | project | `true` | Set `false` to skip a project without deleting it. |

## Layout examples

```jsonc
"layout": { "columns": 2, "rows": 1 }   // two columns per screen  (the default)
"layout": { "columns": 3, "rows": 1 }   // three columns per screen
"layout": { "columns": 2, "rows": 2 }   // four quadrants per screen
"layout": { "columns": 1, "rows": 1 }   // one maximized window per screen
```

Windows fill slots in list order, left-to-right then top-to-bottom, cycling across screens. If you list more projects than slots, later windows stack on top of earlier ones on the same slot — exactly like opening more than fit.

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

## How the DPI handling works

Naïve window tilers read monitor sizes and call `MoveWindow` from a **DPI-unaware** process. Windows then hands back a *virtualized* 96-DPI coordinate space, so a 4K monitor at 250% reports as `1536×864` and a 1080p screen at 175% reports as `1097×617`. The half-screen math is computed in that fake space, and on any monitor whose scale differs from the primary the rectangle gets mis-scaled — windows land too small, with gaps.

`multideck` flips the launcher to **Per-Monitor-DPI-Aware (V2)** *before* it reads any screen, so `Screen.AllScreens` and `MoveWindow` work in **true physical pixels per monitor**:

| Monitor | DPI-unaware (wrong) | Per-Monitor V2 (multideck) |
| --- | --- | --- |
| 4K @ 250% | `1536 × 864` | `3840 × 2160` |
| 1080p @ 175% | `1097 × 617` | `1920 × 1080` |

The grid is then computed in real pixels and is correct on every screen regardless of its scale.

## Troubleshooting

- **`No config found`** — copy `multideck.config.example.json` to `multideck.config.json` first.
- **`Not found: <name>` when tiling** — the window title didn't match. Titles must be unique; if a tool overrides its own title, set a `title` and keep the tab open long enough (raise `settleSeconds`).
- **A project is skipped** — its folder doesn't exist under `baseDir` (the path is printed), or `enabled` is `false`.
- **`wt` not recognized** — install [Windows Terminal](https://aka.ms/terminal).
- **Nothing tiles on re-run** — by design, plain `multideck.bat` only positions windows it just opened. Use `multideck-retile.bat` to re-snap windows that were already open.
- **Scripts blocked** — the `.bat` files already pass `-ExecutionPolicy Bypass`; run those rather than the `.ps1` directly.

## License

MIT © [Devino Solutions](https://devino.ca)
