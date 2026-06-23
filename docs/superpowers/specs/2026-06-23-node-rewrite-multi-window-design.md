# Multideck Node.js Rewrite + Multi-Window Session Resume

**Date:** 2026-06-23
**Status:** Approved
**Scope:** Full rewrite from PowerShell to TypeScript/Node.js, add multi-window session resume, cross-platform support (Windows/macOS/Linux), npm publishing, comprehensive CI/CD.

---

## 1. Overview

Rewrite multideck as a TypeScript CLI tool published on npm. Port all existing functionality (config-driven terminal launching, per-monitor DPI-aware tiling, SSH/remote support) and add a new `windows` config field that opens the same project in multiple named windows, each resuming a different conversation by recency.

## 2. Project Structure

```
multideck/
├── src/
│   ├── cli.ts                  # Entry point, commander-based CLI
│   ├── config.ts               # Config loading, validation, defaults
│   ├── launch.ts               # Orchestrator — discover sessions, launch, tile
│   ├── grid.ts                 # Grid computation — monitors × rows × cols → tile slots
│   ├── terminals.ts            # Terminal emulator detection + adapter registry
│   ├── init.ts                 # Folder scanning + config generation (--init)
│   ├── sessions/
│   │   ├── index.ts            # Session discovery dispatcher (by tool name)
│   │   ├── claude.ts           # Claude session discovery
│   │   └── codex.ts            # Codex session discovery
│   └── platform/
│       ├── index.ts            # Platform detection + interface
│       ├── windows.ts          # Win32 via koffi
│       ├── macos.ts            # CoreGraphics + AppleScript
│       └── linux.ts            # xrandr + xdotool/wmctrl
├── tests/
│   ├── unit/                   # Pure logic tests (all OS)
│   │   ├── config.test.ts
│   │   ├── grid.test.ts
│   │   ├── sessions.test.ts
│   │   ├── titles.test.ts
│   │   └── commands.test.ts
│   ├── platform/               # Real OS calls (per-OS)
│   │   ├── monitors.test.ts
│   │   ├── windows.test.ts
│   │   └── terminals.test.ts
│   ├── e2e/                    # Full pipeline (per-OS)
│   │   ├── launch.test.ts
│   │   ├── multi-window.test.ts
│   │   ├── ssh.test.ts
│   │   ├── idempotency.test.ts
│   │   └── cli-flags.test.ts
│   ├── fixtures/
│   │   ├── claude-sessions/    # Fake .jsonl files with controlled mtimes
│   │   └── codex-sessions/     # Fake .jsonl files with CWD metadata
│   └── helpers/
│       ├── virtual-display.ts  # Setup/teardown virtual monitors in CI
│       ├── ssh-server.ts       # Setup/teardown local SSH server
│       └── poll.ts             # Retry-with-timeout for async window discovery
├── .github/
│   └── workflows/
│       └── ci.yml              # Matrix: windows/macos/ubuntu × unit/platform/e2e
├── package.json
├── tsconfig.json
└── vitest.config.ts
```

## 3. Config Schema

Backward-compatible with the existing JSON format. One new field: `windows`.

```typescript
interface MultideckConfig {
  baseDir?: string;
  layout?: { columns?: number; rows?: number };
  settings?: {
    defaultTool?: string;          // default: "claude"
    settleSeconds?: number;        // default: 3
    launchDelayMs?: number;        // default: 400
    ssh?: { shell?: string };      // default: "bash -lc"
    tools?: Record<string, string>;
  };
  projects: ProjectConfig[];
}

interface ProjectConfig {
  path: string;                    // required — relative to baseDir or absolute
  group?: string;
  color?: string;                  // optional — terminal default if omitted
  tool?: string;                   // defaults to settings.defaultTool
  title?: string;
  enabled?: boolean;               // defaults to true
  host?: string;                   // SSH remote target
  remotePath?: string;
  windows?: number | string[];     // NEW
}
```

### `windows` field behavior

- **Omitted or `1`**: current behavior, single window, tool command as-is.
- **`windows: N`** (number > 1): opens N windows. Titles auto-generated: `"api"`, `"api-2"`, `"api-3"`, ... where `"api"` is the base title (from `title` field or folder name).
- **`windows: ["feat", "bugs", "review"]`** (string array): opens one window per entry with the given custom title. Count inferred from array length.
- **Resume order**: window 1 gets the most recent session, window 2 the second most recent, etc. Windows beyond available sessions start fresh (no resume flag).
- **Ignored for**: `tool: "code"` (VS Code has no session resume), remote/SSH projects (no access to remote session storage).

### Example configs

```json
{
  "baseDir": "C:/Users/you/code",
  "layout": { "columns": 2, "rows": 1 },
  "settings": {
    "defaultTool": "claude",
    "settleSeconds": 3,
    "launchDelayMs": 400,
    "ssh": { "shell": "bash -lc" },
    "tools": {
      "claude": "claude --continue",
      "codex": "codex"
    }
  },
  "projects": [
    { "path": "internal/api", "group": "internal", "windows": 3 },
    { "path": "internal/web", "group": "internal", "windows": ["web-feat", "web-debug"] },
    { "path": "infra/terraform", "group": "infra", "tool": "codex" },
    { "path": "docs", "tool": "code" },
    { "host": "deploy@10.0.0.5", "path": "/srv/api", "group": "remote", "tool": "claude" }
  ]
}
```

## 4. Session Discovery

### 4.1 Claude (`src/sessions/claude.ts`)

Claude stores sessions at `~/.claude/projects/<encoded-path>/<uuid>.jsonl`.

**Path encoding**: replace every character matching `[^a-zA-Z0-9._-]` with `-`. No collapsing of consecutive dashes.

Example:
```
C:\Users\amind\OneDrive\Desktop\Projects\CUSTOM MCPs & PRODUCTIVITY\multideck-ai-agent
→ C--Users-amind-OneDrive-Desktop-Projects-CUSTOM-MCPs---PRODUCTIVITY-multideck-ai-agent
```

**Discovery logic**:
1. Compute encoded path from the project's absolute directory.
2. List `~/.claude/projects/<encoded>/*.jsonl`.
3. Sort by file modification time, descending (most recent first).
4. Return the first N filenames (minus `.jsonl` extension) as session UUIDs.

```typescript
function getClaudeSessionIds(projectDir: string, count: number): string[]
```

### 4.2 Codex (`src/sessions/codex.ts`)

Codex stores sessions at `~/.codex/sessions/YYYY/MM/DD/<name>-<timestamp>-<uuid>.jsonl`. Sessions are organized by date, not project. The first line of each `.jsonl` is a `session_meta` JSON object containing `payload.cwd`.

**Discovery logic**:
1. Recursively list `~/.codex/sessions/**/*.jsonl`.
2. Sort by file modification time, descending.
3. For each file (most recent first), read the first line, parse JSON, extract `payload.cwd`.
4. If `payload.cwd` matches the project directory (case-insensitive on Windows), collect `payload.id`.
5. Stop after collecting N matches.

```typescript
function getCodexSessionIds(projectDir: string, count: number): string[]
```

**Performance**: reads only the first line of each file and stops early. Even with hundreds of sessions, this is sub-second.

### 4.3 Resume Command Construction

When `windows > 1`, the configured tool command's resume flags are stripped and replaced per-window:

```typescript
function buildResumeCommand(tool: string, baseCmd: string, sessionId: string | null): string
```

| Tool | Session found | No session |
|---|---|---|
| claude | Strip `--continue`/`--resume` from baseCmd, append `--resume <id>` | Strip `--continue`/`--resume` from baseCmd (fresh start) |
| codex | `codex resume <id>` | Strip resume-related args from baseCmd (fresh start) |

When `windows` is omitted (single window), the tool command is used exactly as configured — no modification.

## 5. Platform Interface

```typescript
interface Rect { x: number; y: number; w: number; h: number }
type WindowHandle = unknown;  // platform-specific opaque handle

interface Platform {
  setDpiAware(): void;
  listMonitors(): MonitorRect[];
  findWindow(title: string, mode: 'exact' | 'contains'): WindowHandle | null;
  moveWindow(handle: WindowHandle, rect: Rect): void;
  launchTerminal(opts: TerminalLaunchOpts): void;
  launchVSCode(opts: VSCodeLaunchOpts): void;
}

interface MonitorRect extends Rect {
  isPrimary: boolean;
  scaleFactor: number;          // 1.0 = 96 DPI, 1.5 = 144 DPI, etc.
}

interface TerminalLaunchOpts {
  title: string;
  cwd: string;
  command: string;
  color?: string;
  ssh?: { host: string; remoteDir: string; shell: string };
}

interface VSCodeLaunchOpts {
  dir: string;
  sshHost?: string;             // triggers --remote ssh-remote+<host>
}
```

### 5.1 Windows (`platform/windows.ts`)

Uses `koffi` for Win32 FFI. No native compilation, no node-gyp.

| Operation | Win32 API |
|---|---|
| DPI awareness | `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)` with fallbacks to `SetProcessDpiAwareness(2)` and `SetProcessDPIAware()` |
| Monitor enumeration | `EnumDisplayMonitors` + `GetMonitorInfoW` for working areas |
| DPI per monitor | `GetDpiForMonitor` (shcore.dll) |
| Window finding | `EnumWindows` + `GetWindowText` + `IsWindowVisible` |
| Window moving | `MoveWindow` called twice (cross-DPI correction) |
| Terminal launch | `child_process.spawn('wt', [...args])` |
| VS Code launch | `child_process.spawn('cmd', ['/c', 'code', dir])` |

**Dual-MoveWindow for DPI**: when a window moves from monitor A to monitor B with a different scale factor, Windows fires `WM_DPICHANGED` and the window rescales itself mid-move. The first `MoveWindow` gets the window onto the target monitor; the second applies the correct size now that the window lives at the target DPI. Same-scale moves make the second call a no-op.

### 5.2 macOS (`platform/macos.ts`)

| Operation | Implementation |
|---|---|
| DPI awareness | No-op (Retina handled by OS) |
| Monitor enumeration | Run Swift snippet via `child_process`: `NSScreen.screens` → JSON with `frame` and `visibleFrame` (working area) and `backingScaleFactor` |
| Window finding | `osascript`: `tell application "System Events" to get name of every window of every process whose visible is true` |
| Window moving | `osascript`: `tell application "System Events" to tell process <P> to set position of window <W> to {x, y}` + `set size of window <W> to {w, h}` |
| Terminal launch | Detect installed terminal in priority order: iTerm2, Kitty, Warp, Terminal.app. Each adapter knows its CLI flags for title, cwd, and command execution. |
| VS Code launch | `child_process.spawn('code', [dir])` or `code --remote ssh-remote+<host> <dir>` |

**Terminal adapters (macOS)**:
- **iTerm2**: `osascript` to create new window with profile, set title, send command.
- **Kitty**: `kitty --title <t> --directory <d> <cmd>`
- **Warp**: `open -a Warp` + AppleScript for title/dir.
- **Terminal.app** (fallback): `osascript` to open new window, set cwd, run command.

### 5.3 Linux (`platform/linux.ts`)

Requires X11 (Wayland support deferred — most CI and tiling use cases are X11). Dependencies: `xdotool`, `wmctrl`, `xrandr` (standard on most desktops; installed in CI).

| Operation | Implementation |
|---|---|
| DPI awareness | Read `Xft.dpi` via `xrdb -query` or `GDK_SCALE` env var. Compute scale factor. |
| Monitor enumeration | Parse `xrandr --query` for connected outputs: resolution, offset, physical size (mm) → compute DPI per monitor. Also support `xrandr --listmonitors` for virtual monitor setups. |
| Window finding | `xdotool search --name <title>` (exact) or `wmctrl -l` + string matching (contains) |
| Window moving | `wmctrl -i -r <handle> -e 0,x,y,w,h` |
| Terminal launch | Detect installed terminal in priority order: kitty, alacritty, gnome-terminal, konsole, xterm. Each adapter knows its CLI flags. |
| VS Code launch | `child_process.spawn('code', [dir])` |

**Terminal adapters (Linux)**:
- **kitty**: `kitty --title <t> --directory <d> <cmd>`
- **alacritty**: `alacritty --title <t> --working-directory <d> -e <cmd>`
- **gnome-terminal**: `gnome-terminal --title <t> --working-directory <d> -- <cmd>`
- **konsole**: `konsole --title <t> --workdir <d> -e <cmd>`
- **xterm** (fallback): `xterm -T <t> -e "cd <d> && <cmd>"`

### 5.4 Terminal Detection

Shared logic across macOS and Linux. Checks for terminal emulators in a priority-ordered list, returns the first found:

```typescript
interface TerminalAdapter {
  name: string;
  detect(): boolean;              // is the binary on PATH?
  buildLaunchArgs(opts: TerminalLaunchOpts): { bin: string; args: string[] };
}
```

Windows always uses Windows Terminal (`wt`). macOS and Linux use the adapter registry. The detection result is cached for the duration of a run.

## 6. Grid Computation (`src/grid.ts`)

Pure function, no platform dependency. Takes monitor list + layout config, returns tile slots.

```typescript
interface TileSlot extends Rect {
  monitorIndex: number;
  label: string;                  // "r1c1", "r1c2", etc.
}

function computeGrid(monitors: MonitorRect[], cols: number, rows: number): TileSlot[]
```

Logic:
1. Sort monitors by `x` position (left to right).
2. For each monitor, divide its working area into `cols × rows` cells.
3. Return all cells as `TileSlot` objects.
4. Windows wrap around to slot 0 when there are more windows than slots.

## 7. Launch Orchestrator (`src/launch.ts`)

Central function that ties everything together:

```typescript
async function runMultideck(config: MultideckConfig, opts: RunOpts): Promise<void>
```

**Flow**:
1. Detect platform, call `setDpiAware()`.
2. Call `listMonitors()`, compute grid via `computeGrid()`.
3. Iterate projects (filtered by group/enabled):
   a. Resolve project path (relative to baseDir, env vars, `~`).
   b. Determine window count from `windows` field (default 1).
   c. If multi-window and tool is `claude`/`codex`: discover session IDs via `sessions/`.
   d. For each window instance:
      - Compute title (auto or custom).
      - Build tool command (with `--resume <id>` or fresh).
      - Check if window already exists via `findWindow()`.
      - If not found and not dry-run: call `launchTerminal()` or `launchVSCode()`.
      - Add to tile queue.
4. Wait `settleSeconds` for new windows to appear.
5. Tile: for each window in the tile queue, call `findWindow()` (with retry/polling) then `moveWindow()`.

**Idempotency**: windows already open (found by title) are skipped for launch but included in the tile queue when `--retile-all` is set.

## 8. CLI (`src/cli.ts`)

Same flags as the PowerShell version, implemented with `commander`:

```
Usage: multideck [options]

Options:
  --go                    Skip interactive menu, launch + tile
  --retile-all            Re-tile every matching window
  --dry-run               Preview plan without launching or moving
  --group, -g <name>      Launch only projects in this group
  --init                  Generate config by scanning a folder
  --base-dir <path>       Folder to scan with --init
  --config <path>         Path to config file (default: ./multideck.config.json)
  --force                 With --init, overwrite existing config
  --version, -v           Print version
  --help, -h              Show help
```

Interactive menu when run with no flags (same choices as current PowerShell version). Uses `readline` for input in TTY mode.

## 9. npm Packaging

```json
{
  "name": "multideck",
  "bin": { "multideck": "./dist/cli.js" },
  "engines": { "node": ">=18" },
  "files": ["dist"],
  "dependencies": {
    "commander": "^13.0.0",
    "koffi": "^2.9.0"
  },
  "devDependencies": {
    "vitest": "^3.0.0",
    "typescript": "^5.7.0",
    "node-pty": "^1.0.0"
  }
}
```

`koffi` is a runtime dependency but only loaded on Windows (dynamic import). macOS and Linux have zero native dependencies — they shell out to OS tools.

Install and run:
```
npm install -g multideck
multideck --go

# or without global install:
npx multideck --go
```

## 10. CI/CD Pipeline

### 10.1 GitHub Actions Matrix

```yaml
name: CI
on: [push, pull_request]

jobs:
  unit:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci
      - run: npm run test:unit

  platform:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci
      - name: Setup virtual displays
        uses: ./.github/actions/setup-virtual-displays
      - name: Install terminal emulators
        uses: ./.github/actions/install-terminals
      - run: npm run test:platform

  e2e:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci
      - name: Setup virtual displays
        uses: ./.github/actions/setup-virtual-displays
      - name: Setup SSH server
        uses: ./.github/actions/setup-ssh-server
      - name: Install terminal emulators
        uses: ./.github/actions/install-terminals
      - run: npm run test:e2e

  packaging:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci && npm run build
      - run: npm pack
      - run: npm install -g ./multideck-*.tgz
      - run: multideck --help
      - run: multideck --version
```

### 10.2 CI Setup Actions

**`.github/actions/setup-virtual-displays`** — creates multi-monitor + multi-DPI environments:

- **Linux**: Start `Xvfb :99 -screen 0 5760x2160x24`, then use `xrandr --setmonitor` to carve out virtual monitors at different physical sizes (simulating different DPIs). Install `wmctrl`, `xdotool`. Export `DISPLAY=:99`.
- **Windows**: Install a virtual display driver (IddCx-based or `virtual-display-rs`) to create a second virtual monitor. Set per-monitor DPI via registry under `HKCU\Control Panel\Desktop\PerMonitorSettings`.
- **macOS**: Use `CGVirtualDisplay` or system preferences scripting to configure a second virtual display. Query `NSScreen` to verify.

**`.github/actions/setup-ssh-server`** — starts a local SSH server:

- **Linux**: `apt-get install openssh-server`, generate ed25519 key, add to `authorized_keys`, start `sshd` on a non-standard port. Export `MULTIDECK_TEST_SSH_PORT`.
- **Windows**: Enable OpenSSH Server optional feature, configure and start `sshd`.
- **macOS**: `sudo systemsetup -setremotelogin on`, generate key, add to `authorized_keys`.

**`.github/actions/install-terminals`** — installs multiple terminal emulators:

- **Linux**: `apt-get install xterm gnome-terminal kitty`
- **macOS**: `brew install --cask iterm2 kitty`
- **Windows**: Windows Terminal is pre-installed; no action needed.

### 10.3 Complete Test Matrix

#### Unit Tests (all 3 OS, no special setup)

| Area | Tests |
|---|---|
| Config parsing | Valid JSON, invalid JSON, missing required fields, wrong types, proper error messages |
| Config defaults | Each optional field omitted → correct default applied |
| Path resolution | Relative, absolute, `~`, env vars, forward slashes, backslashes |
| Group filtering | Filter by group name, empty group, non-existent group |
| `enabled: false` | Disabled projects excluded |
| Custom tools | Register tool in settings.tools, verify command resolved |
| `windows: N` | 1, 2, 5 → correct number of launch entries with auto-titles |
| `windows: [...]` | String array → correct titles, count from length |
| `windows` omitted | Single window, backward-compatible |
| `windows` + `tool: "code"` | Ignored, single VS Code window |
| `windows` + remote/SSH | Ignored, single window |
| Grid: 1 monitor, 2×1 | 2 slots, correct coordinates |
| Grid: 1 monitor, 2×2 | 4 slots |
| Grid: 2 monitors, different sizes | Correct per-monitor slot dimensions |
| Grid: 3 monitors, mixed res | 1080p + 1440p + 4K |
| Grid: taskbar offset | WorkingArea ≠ Bounds |
| Grid: more windows than slots | Wraps to slot 0 |
| Claude path encoding | Known paths → expected encoded strings |
| Claude session scan | Fixture dir with N files, controlled mtimes → correct order |
| Codex session scan | Fixtures with mixed CWDs → only matching CWDs returned |
| Session: fewer than requested | Request 5, only 2 → 2 IDs + 3 nulls |
| Session: zero available | Empty dir → all nulls |
| Title gen: auto | "api" → "api", "api-2", "api-3" |
| Title gen: custom | Array titles used verbatim |
| Title gen: from folder name | No `title` field → leaf of path |
| Title gen: duplicate leaves | Detected during --init, unique titles generated |
| Resume cmd: claude, session found | `claude --resume <id>` |
| Resume cmd: claude, fresh | `claude` (no resume flag) |
| Resume cmd: codex, session found | `codex resume <id>` |
| Resume cmd: codex, fresh | `codex` (no resume flag) |
| Resume cmd: strips --continue | Base cmd `claude --continue` → `claude --resume <id>` |
| SSH command construction | Full SSH command string with shell wrapper |
| SSH shell wrapper disabled | Empty string → no wrapper |
| Remote dir resolution | `remotePath` takes precedence over `path` |
| Init: folder scanning | Temp dir with git repos → correct config |
| Init: duplicate leaf names | Unique titles generated |
| Init: no git repos fallback | Falls back to immediate subdirectories |

#### Platform Integration Tests (per-OS, with virtual displays + terminals)

| Area | Tests |
|---|---|
| `listMonitors()` ≥ 1 | At least 1 monitor with valid bounds |
| `listMonitors()` multi-monitor | Virtual monitors → correct count and geometries |
| `listMonitors()` DPI per monitor | Different physical sizes → different scale factors |
| `findWindow()` exact match | Launch window, find by exact title |
| `findWindow()` contains match | Launch with compound title, find by substring |
| `findWindow()` miss | Non-existent title → null |
| `moveWindow()` reposition | Move window, re-query, assert new position |
| `moveWindow()` cross-DPI | Move from 96 DPI to 180 DPI monitor, verify correct final size |
| Terminal launch: primary | Launch with OS default terminal, verify window appears with title |
| Terminal launch: each adapter | Launch with each installed terminal, verify title and cwd |
| Terminal detection | With multiple installed, correct priority order |
| Terminal cwd | Verify terminal opens in correct directory |
| Terminal color | Verify color arg included (where supported) |
| VS Code launch | `code <dir>`, verify window with folder name in title |
| VS Code Remote-SSH | `code --remote ssh-remote+localhost <dir>` via local SSH |
| VS Code title matching | Title contains folder basename |
| VS Code async polling | Launch, poll with timeout, verify found |

#### E2E Tests (per-OS, full pipeline)

| Area | Tests |
|---|---|
| Basic launch | Config with 2 projects → 2 windows with correct titles |
| `windows: 3` | 3 windows spawned: "api", "api-2", "api-3" |
| `windows: ["a","b"]` | 2 windows with custom titles |
| Session resume | Plant 3 fixture sessions, verify each window got correct `--resume <id>` |
| Excess windows fresh | 3 windows, 1 session → 1 resume + 2 fresh |
| Tiling positions | Windows placed at expected grid coordinates |
| Multi-monitor tiling | Windows distributed across virtual monitors |
| Idempotent re-run | Run twice → no duplicate windows |
| `--go` flag | Launches without interactive menu |
| `--group` flag | Only matching group launched |
| `--dry-run` | Zero windows spawned, plan output printed |
| `--retile-all` | Already-open windows repositioned |
| `--init` | Scans temp folder, writes valid config |
| `--config <path>` | Uses alternate config file |
| `--force` with `--init` | Overwrites existing config |
| Interactive menu | Use `node-pty` to simulate TTY + keypress sequences |
| No config found | Error message + prompt |
| SSH launch | Real SSH to localhost, terminal opens with remote command |
| SSH `cmd /k` persistence (Windows) | Window stays open after SSH session ends |
| SSH missing warning | Remove SSH from PATH, assert warning |
| Mixed tools | Config with claude + codex + code → each launched correctly |
| Empty config | No projects → graceful message |
| Invalid config | Malformed JSON → clear error |
| Unknown tool | Warning, project skipped |

#### Packaging Tests (ubuntu)

| Area | Tests |
|---|---|
| `npm pack` | Produces tarball without error |
| Install from tarball | `npm install -g ./multideck-*.tgz` succeeds |
| `multideck --help` | Exits 0, shows usage text |
| `multideck --version` | Prints version string |
| bin resolves | `which multideck` points to installed binary |

## 11. Migration from PowerShell

The Node.js version reads the same `multideck.config.json` format. Existing configs work without modification. The `windows` field is optional and additive.

Users replace:
```
.\multideck.bat           →  npx multideck
.\multideck.bat -Go       →  npx multideck --go
.\multideck.bat -Group x  →  npx multideck -g x
```

The PowerShell scripts (`scripts/multideck.ps1`, `scripts/multideck.lib.ps1`) and batch launcher (`multideck.bat`) remain in the repo but are deprecated. They can be removed in a future release.

## 12. Dependencies

| Package | Purpose | Platform |
|---|---|---|
| `commander` | CLI parsing | all |
| `koffi` | Win32 FFI (dynamic import) | Windows only |
| `vitest` (dev) | Test framework | all |
| `node-pty` (dev) | Interactive menu testing | all |
| `typescript` (dev) | Build | all |

macOS and Linux have zero native runtime dependencies — they use `child_process.execSync/spawn` to call OS tools (`osascript`, `xrandr`, `wmctrl`, `xdotool`, `code`, terminal CLIs).

## 13. Decisions & Trade-offs

| Decision | Rationale |
|---|---|
| `koffi` over `ffi-napi` | No node-gyp, no build tools needed on install |
| `commander` over `yargs` | Lighter, sufficient for this CLI's complexity |
| `vitest` over `jest` | Faster, native TypeScript, built-in mocking |
| Dynamic import for `koffi` | Avoids crash on macOS/Linux where koffi isn't needed |
| `xdotool`/`wmctrl` over X11 bindings | Simpler, no native deps, sufficient for tiling |
| AppleScript over Accessibility API | No native addon needed, works for window find/move |
| File scanning over CLI introspection | Neither Claude nor Codex has a non-interactive session list command |
| Resume all windows with `--resume <id>` | Consistent ordering controlled by our scan, avoids `--continue` mismatch |
| X11 only (no Wayland) for v1 | Most tiling use cases and CI environments use X11; Wayland tiling is WM-dependent |

## 14. Future Work (out of scope for this implementation)

- Wayland support (Linux) — requires compositor-specific protocols (sway IPC, KWin scripting).
- Multi-window for remote/SSH projects — would need SSH tunnel to scan remote session files.
- Session naming / pinning — let users pin a specific session ID to a window slot.
- Auto-color assignment — assign colors from a palette when `color` is omitted.
- Config hot-reload — watch config file, re-tile on change.
