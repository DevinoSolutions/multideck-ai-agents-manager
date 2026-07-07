# multideck — Design Record

This document records how multideck is built and *why it is shaped the way it
is*, for an AI agent picking up this codebase cold. It is a design record,
not a wishlist: it describes what the code on disk actually does. Where the
shape looks wrong at first glance, that is usually because it was
adjudicated on purpose during a formal multi-stage audit (2026-07) — this
document exists so that adjudication is not re-litigated by a future agent
who wasn't there. Aspirational changes live only in the Known Debt section.
Audit IDs in parentheses (`R9`, `ADJ-S2-4`, `NF-S3-003`, ...) are provenance
tags from that audit; the substance of every decision is stated here in
full, so nothing in this file requires the (untracked) audit artifacts to
understand.

Decision lens used throughout the audit that produced this record:
maintainability > operability > performance, optimized for a cold agent's
legibility, with sub-lenses of modularity, deduplication, clarity, and
convention-following.

## 1. Module map

### Dependency direction

```
pure leaves:  grid · paths · style · titles · log · terminals · agent_state · config
                          ^
subsystems:   tiling · platform/ · sessions/ · discover · init_config · launch · upload_server · hotkey
                          ^
cli/ command modules:  app · config_io · ui · spawns · config_editor · menu · attach · docs · daemons · session_picker · status
                          ^
cli/__init__.py  (registration hub)
```

Arrows point from dependent to dependency (imports flow upward in this
list). Each layer only imports from layers below it, with one documented
exception (the `app.py` cycle-break, below) and one documented sibling edge
(`menu.py` imports `config_editor.py` directly, one-directional — the config
editor never imports the menu back; the rationale is written in `menu.py`'s
own docstring).

### The registration hub and the cycle it breaks

`cli/__init__.py` is a 24-line registration hub and nothing else: it imports
`app.main`, then imports every other command module (`attach`, `config_editor`,
`config_io`, `daemons`, `docs`, `menu`, `session_picker`, `spawns`, `status`,
`ui`) purely so their `@main.command` decorators fire at import time, then
re-exports the ~16 underscore-prefixed names that tests and other call sites
still reach via `multideck.cli.<name>`. It never imports `paths` or `style`
directly — those are top-level modules, not part of the `cli` package.

`main` (the click group) lives **alone** in `cli/app.py`, importing nothing
from sibling command modules at its own top level. This is deliberate: since
the hub eagerly imports every command module (to register it), and every
command module needs to `from multideck.cli.app import main` to attach its
own commands, any command module importing back from `app.py` at top level
would be a real import cycle. `app.py`'s no-subcommand interactive path (the
menu, `--edit`, `--init`, attach-flow dispatch) needs several sibling
handlers — `_attach_flow`, `_menu_down`, `_menu_status`, `_menu_up`,
`_run_discovery`, `_run_sessions_picker`, `_show_menu` — so `main`'s body
imports them from `multideck.cli` (the hub) **inside the function**, after
all registration has already completed. This in-body import is the
documented cycle-break, not an oversight.

### Pure leaves

None of these imports any other `multideck` module (`style.py` imports
`click`; the rest are stdlib-only):

- **`grid.py`** — `Rect`/`MonitorRect`/`TileSlot` dataclasses + `compute_grid`,
  the DPI-aware tiling-slot math (caps columns/rows per monitor so no tile
  falls below Windows Terminal's minimum shrink size — `MIN_TILE_W`/
  `MIN_TILE_H` with the measured rationale in the comment above them).
- **`paths.py`** — config-file location only, stdlib-only. Its own docstring
  records *why* it must live at the top level and not as `cli/paths.py`:
  `upload_server.py` needs `find_config` without depending on the `cli`
  *package* (the hub imports every command module for registration; if the
  config-path leaf lived inside `cli`, `upload_server` would depend back on
  the very package that transitively pulls it in) — this is the structural
  fix for what used to be a latent `cli`↔`upload_server` load cycle (LS-A-001).
- **`style.py`** — `style = click.style`, a one-line shared shortcut. It used
  to be independently defined twice (once in the old monolithic `cli.py`,
  once in `launch.py`); both call sites now import `style` from here
  (LS-A-003). A transitional `S` alias existed during the multi-PR migration
  and has since been deleted repo-wide — every call site uses `style` directly.
- **`titles.py`** — owns `MD_TITLE_PREFIX = "md:"` plus `generate_titles`/
  `get_leaf_name` (LS-B-006). This is the single source of truth for the
  `md:`-prefixed window-title convention: `cli/attach.py` builds titles from
  it (the only two build sites), `hotkey.py` strips it to recover the
  project name.
- **`log.py`** — rotating file logging (`get_logger`, one logger + one log
  file per named concern under `~/.multideck/logs/`) and cross-platform
  liveness heartbeats (`write_heartbeat`/`heartbeat_fresh`). Heartbeats live
  here rather than in `hotkey.py` specifically so platform-agnostic callers
  (`status`, Linux CI) can check daemon liveness without importing the
  Windows-only hotkey module. Logging setup is best-effort by design — a
  failure falls back to `NullHandler` rather than raising, because the
  daemons that call it run detached with no console to crash to.
- **`terminals.py`** — `detect_terminal()` + per-OS terminal-priority lists.
  Note for a cold agent: no `src/` module currently calls it —
  `platform/linux.py` and `platform/macos.py` each hard-code their own
  `shutil.which(...)` terminal-priority chain inline instead of calling this
  leaf. It is exercised only by tests. This wasn't raised as a finding in
  the audit that produced this document; flagged here for whoever looks next.
- **`agent_state.py`** — file-per-session lifecycle store (`working`/`done`/
  `needs-input`/`error`/`idle`), keyed by a hash of the session's normalized
  cwd. Stdlib-only by design (its own docstring: it's imported from hook
  handlers on the hot path of every agent turn, so it must stay
  dependency-light). Has zero tests today (see Known Debt).
- **`config.py`** — grouped with subsystems below for its behavioral role,
  but structurally a leaf (no `multideck`-internal imports).

### Subsystems

- **`config.py`** — one dataclass schema (`MultideckConfig`/`Settings`/
  `ProjectConfig`/`LayoutConfig`/`SSHConfig`), one envelope factory
  (`default_config`), one pair of serializers (`layout_to_dict`/
  `settings_to_dict`) that every config generator delegates through, a pure
  `load_config` reader, and `migrate_config_file` as the single disk-writing
  function in the module. `DEFAULT_TOOLS` is the one dict of built-in
  tool commands (`claude`, `codex`, `cursor-agent`, `agy`); `Settings.tools`'
  default factory and `_parse_settings`'s fallback both copy it
  (`dict(DEFAULT_TOOLS)`) rather than sharing one mutable dict (LS-B-002).
- **`tiling.py`** — the *one* window resolve-and-place loop, shared by
  `launch.run_multideck`'s post-launch tiling and `cli/attach.py`'s
  `_tile_titles` (R13). Before this module existed the two call sites each
  hand-rolled their own snapshot/retry loop with independently-drifted magic
  numbers. Its retry constants are named and centralized:
  `RETRY_SECS_CONTAINS` (20s — `contains`-mode matches like VS Code windows
  are slow to appear), `RETRY_SECS_EXACT` (6s), `POLL_INTERVAL_S` (1.0s).
  `place_windows` takes one snapshot, places everything already visible, then
  polls only the still-missing set up to the slower of the two deadlines,
  logging a WARNING via `get_logger("launch")` for anything still missing
  before invoking the caller's `on_missing` callback.
- **`platform/` (ABC + per-OS backends)** — `Platform` declares the
  cross-platform contract via `@abstractmethod` (`set_dpi_aware`,
  `list_monitors`, `find_window`, `move_window`, `launch_terminal`,
  `launch_vscode`) plus concrete-with-safe-default methods any backend may
  leave unoverridden: `snapshot_windows` (default `{}`),
  `launch_psmux_session`/`attach_psmux` (default `raise
  NotImplementedError("psmux is only supported on Windows")`), and the
  capability probes `supports_psmux()`/`supports_hotkey()` (both default
  `False`). All three backends implement the six abstract methods;
  **only `WindowsPlatform`** overrides the psmux methods and capability
  probes — `LinuxPlatform`/`MacOSPlatform` inherit those ABC defaults as-is.
  `find_window`'s `mode` parameter is typed `Literal["exact", "contains"]`
  on the ABC and all three implementations, and each implementation raises
  `ValueError` on an unrecognized mode string before any OS dispatch, so a
  bogus mode fails fast instead of reaching a live `osascript`/`xdotool`
  call (LS-B-005). `get_platform()` picks the concrete backend by
  `sys.platform` and imports it lazily, so importing `multideck.platform`
  never pulls in Windows- or macOS-specific code on the wrong OS.
- **`sessions/`** — `AGENT_TOOLS: dict[str, AgentTool]` is the registry of
  per-tool resumability (`claude`, `codex` today). `AgentTool` is a frozen
  dataclass: `session_ids` (a `(project_dir, count) -> list[str|None]`
  callable), `resume_command`, and `happy` (whether the tool can be wrapped
  with the `happy` mobile/web relay); `multi_window` is a derived property
  (`session_ids is not None`). `build_resume_command` is the one dispatcher;
  an unregistered tool falls back to its own base command unchanged.
  `sessions/claude.py` and `sessions/codex.py` each implement the same two
  free functions (`get_<tool>_session_ids`, `build_<tool>_resume`) against
  that tool's own on-disk session format — the registry is what lets
  `launch.py` and `cli/` treat every registered tool identically (F-CT-001).
- **`discover.py`** — finds candidate projects from Claude/Codex/VS Code
  history and merges them by path. `_merge_candidate` keeps whichever
  candidate has the strictly greatest `last_active` seen so far, ties going
  to the first offered — the fix for a bug where a two-way pairwise merge
  could silently prefer a strictly older source (R9). Depends on `config`
  (for `default_config`/`_random_tab_color`) and `sessions.claude` (for its
  path-encoding helper).
- **`init_config.py`** — the `--init --base-dir` folder-scan generator
  (`scan_for_projects`/`generate_config`/`write_config`); delegates to
  `config.default_config`/`_random_tab_color` so its output can't drift from
  `discover.py`'s (F-D5-003).
- **`launch.py`** — the widest-importing subsystem: `config`, `grid`, `log`,
  `platform`, `sessions`, `style`, `tiling`, `titles`. `run_multideck` is now
  a 5-phase composition shell — radon A(4), down from F(83) pre-audit —
  (`_prepare_grid` → `_select_projects` → `_launch_projects` →
  `_start_psmux_and_upload` → `_tile_targets`), each phase returning data or
  `None`; the shell alone owns the command's exit code and the
  no-monitors/empty-group echoes. `_launch_projects` further splits its
  per-project dispatch along the IDE/CLI-agent seam into
  `_dispatch_ide_project` and `_dispatch_cli_agent_project` (the latter is,
  at radon D(27), the most complex function remaining in the module — known
  and measured, not hidden). `_tile_targets` is a thin delegate to
  `tiling.place_windows`; no resolve/retry logic is re-implemented in
  `launch.py`. The psmux bring-up-and-spawn-upload-server phase is named
  **`_start_psmux_and_upload`** rather than `_bring_up_psmux`, specifically
  to avoid colliding one-underscore-apart with the already-existing public
  `bring_up_psmux` (the attach-path's headless detached-session creator,
  used by `up_cmd`/`_menu_up`/`_attach_flow`) — those are two different
  operations, and giving them near-identical names would have been its own
  clarity defect.
- **`upload_server.py`** — imports `launch._psmux_session_name`,
  `log.get_logger`, `paths.find_config`, and `platform.find_psmux` at the
  top level, and **never** imports the `cli` package (that is the actual
  invariant LS-A-001 established — not "depends on nothing but `paths`,"
  which was an earlier, imprecise description this document deliberately
  does not repeat). `run_server` binds one `ThreadingHTTPServer` per address
  returned by `_bind_addresses` (see Key Decisions).
- **`hotkey.py`** — the Windows-only Alt+V clipboard-image listener.
  `if sys.platform != "win32": raise ImportError(...)` fires at import time,
  by design — every call site imports it lazily, behind a `supports_hotkey()`
  gate, with a `# ImportError off-Windows (hotkey.py guards); must stay lazy`
  comment at the import. Imports only `log` and `titles` from `multideck`.

### `cli/` command modules

Each imports `main` from `cli/app.py` (to attach its own commands) plus
whatever subsystems and sibling `cli/` leaves it needs. "Heavy" subsystem
imports (`launch`, `upload_server`, `discover`, `agent_state`, the platform
backends via `get_platform()`, and the lazy `hotkey` import) are placed
**inside function bodies**, each with a one-line why-comment (`# heavy
subsystem: in-body per policy`, or the hotkey-specific ImportError comment)
— see Key Decisions for why this is a deliberate policy, not scattered
laziness.

- **`app.py`** — `main` alone (see above).
- **`config_io.py`** — the raw-dict config I/O leaf: `_load_raw_config`/
  `_save_raw_config` (round-trips the on-disk JSON as a plain `dict`,
  preserving every key including ones the typed schema doesn't model) plus
  `_load_config_or_exit` (wraps `config.load_config`, the typed path, catching
  `(ValueError, FileNotFoundError)` — `ConfigError` is a `ValueError`
  subclass so it's caught without a separate except clause — and exiting 1
  with a plain `Error: <msg>` on stderr). See Key Decisions for why both
  paths are kept.
- **`ui.py`** — pure presentation (banner/menu chrome, grid preview, session
  listing) plus exactly two platform-guarded helpers, each guarded in-body:
  `_force_utf8_console` (Windows-only ctypes) and `_print_qr` (optional
  `qrcode` import inside a `try/except ImportError` that prints an install
  tip on failure — a deliberate optional dependency, not a latent bug;
  ADJ-S2-5).
- **`spawns.py`** — the runtime-probe/daemon-bootstrap leaf: port/pid
  liveness checks (`_probe_port`, `_pid_alive`, `_running_upload_port`) and
  the detached-process launchers for the upload server and the Alt+V
  listener (`_maybe_start_upload_server`, `_maybe_start_hotkey`). Also owns
  `_tailnet_host` (Tailscale MagicDNS name → Tailscale IP → LAN IP
  fallback, used by `mobile_cmd` in `daemons.py`).
- **`config_editor.py`** — `_config_menu` (the single worst-graded function
  in the repo — see Key Decisions) and the `config` command group (14
  subcommands, including `migrate`). Imports the raw-dict path from
  `config_io` (`_load_raw_config`/`_save_raw_config`), never the typed
  loader — the interactive editor's whole reason for existing is to preserve
  unknown keys the typed schema would drop.
- **`menu.py`** — the interactive main menu (`_show_menu`) and the first-run
  discovery wizard (`_run_discovery`). Imports `config_editor` directly at
  its own top level to reach `_config_menu` — the one documented sibling
  import in the `cli/` package (documented in `menu.py`'s docstring), safe
  because `config_editor.py` never imports back from `menu.py`.
- **`attach.py`** — SSH/attach orchestration: `_attach_flow` (see Key
  Decisions), its no-mux sibling `_attach_nomux`, `_tile_titles` (delegates
  to `tiling.place_windows` with `settle_s=3` and a hard-coded 2×1 grid —
  see Known Debt), and the `up`/`attach`/`hotkey` commands. Imports
  `config.load_config` directly — the one permitted raw-loader call site
  outside `config_io.py` (see Key Decisions).
- **`docs.py`** — the `multideck docs` command: a pure-string Markdown
  generator (~190 content lines) for the full config reference, reading live
  defaults off `config.LayoutConfig`/`config.Settings` for some fields but
  hand-writing others (see Known Debt: NF-S3-003).
- **`daemons.py`** — `serve`/`mobile`/`termius` commands. `serve` carries the
  `--host` escape hatch (see Key Decisions).
- **`session_picker.py`** — live psmux session listing (`sessions_cmd`) and
  the looping attach-and-return picker (`_run_sessions_picker`). Named
  `session_picker`, not `sessions`, to avoid confusion with the top-level
  `multideck.sessions` package (recorded at extraction time).
- **`status.py`** — `_render_status` (shared by the `status` command and the
  menu's `_menu_status`) plus the `down` command. Owns the daemon-health
  probes: `_health_check` (HTTP GET `/health` — proves the upload server is
  actually *serving*, not just that a pid or port looks alive),
  `_upload_state`/`_listener_state`/`_gather_status`/`_is_degraded`, and the
  `status --json`/exit-3-on-degraded contract (exit codes: 0 healthy, 1
  config missing/invalid, 3 degraded; click itself uses 2 for usage errors).

## 2. Key decisions

Each of these looks like it could be "cleaned up." Each was examined and
left as-is on purpose. Do not refactor these without re-reading the
rationale.

**Two-path config contract, by design (ADJ-S2-4).** `config_io.py`'s
`_load_raw_config`/`_save_raw_config` round-trip the on-disk config as a
plain `dict`, deliberately kept separate from `config.load_config` (the
validated, typed path used everywhere else). `config.py` ships no typed
*writer*, and `load_config` intentionally drops/warns-on unknown keys rather
than modeling them. If the interactive config editor (`config_editor.py`)
round-tripped a save through the typed dataclasses instead, any key the
schema doesn't know about would be silently dropped from the user's file.
The two paths are the fix, not the disease. Anyone who "deduplicates" the
editor onto `load_config`/a typed writer will cause silent data loss for any
hand-added or forward-compatible config key.

**`load_config` never writes; `migrate_config_file` is the only writer
(R10).** `load_config` is a pure read: on a schema version below current, it
prints `Warning: config schema v<N> < v<CURRENT>; run: multideck config
migrate` to stderr and returns in-memory data — it never touches the file.
Persisting a migration (or backfilled colors) requires `multideck config
migrate` (or a save through the config editor's raw path). A load that
rewrites the file as a side effect was one of the audited defects; do not
reintroduce it.

**Color backfill is ephemeral until migrated.** `load_config` calls
`_backfill_colors` on every load, assigning a random, session-local color to
any project missing one — in memory only, never written back. Re-running
`multideck` against a colorless project can show a different color each run
until `multideck config migrate` (or a config-editor save) persists one.
This is the accepted cost of keeping `load_config` a pure read; run
`migrate` once per config to pin colors.

**`up_cmd` (`cli/attach.py`) is the one permitted raw `load_config` call
site outside `config_io.py`.** Every other guarded call site in `cli/`
routes through `config_io._load_config_or_exit`, which prints a plain-text
`Error: <msg>` to stderr and exits 1. `up_cmd`'s `--json` mode instead needs
to emit `{"error": "<msg>"}` as JSON **on stdout** on a config error (so a
machine caller reading `--json` output always gets JSON, never a stderr
traceback or plain text) — something `_load_config_or_exit`'s fixed
stderr-text shape cannot do. `up_cmd` therefore calls `config.load_config`
directly and handles the error itself.

**`status --json`'s config-error path keeps the plain-text shape for now,
and that asymmetry is recorded, not missed (NF-S3-005).** Unlike `up_cmd`,
`status_cmd`'s `--json` branch routes a config-load failure through the same
`_load_config_or_exit` as the plain-text path — so a `--json` caller can get
a plain-text stderr error instead of JSON. This was deliberately *not*
unified with `up_cmd`'s JSON-error convention during the refactor that
produced this module: the site used to be an unguarded raw Python traceback,
so today's behavior is a strict improvement, and unifying the shapes is a
real behavior change the relocate-only discipline deferred. Tracked in Known
Debt below; not a bug to silently "fix" in a drive-by edit.

**`_config_menu` (F(48), `cli/config_editor.py`), `main` (E(33),
`cli/app.py`), and `_attach_flow` (D(29), `cli/attach.py`) were relocated,
not decomposed — on purpose.** All three moved out of the former
2,400+-line monolithic `cli.py` into their current modules with their bodies
otherwise untouched, each behind a characterization test that pins its
current behavior. Decomposing any of them is legitimate next-cycle work, but
it must start from that pin, not from a fresh read of the function. High
complexity here is known, measured, and fenced — not an oversight awaiting a
quick fix.

**The Alt+V hook calls `GetWindowTextW` from inside the low-level keyboard
hook, and that's an accepted risk, not a bug (F-D4-003).** `hotkey.py`'s
`get_active_window_title` is called from `_hook_decide` — but only on the
Alt+V chord itself (`kb.vkCode == VK_V and state["alt_held"]`), not on every
keystroke. The risk is accepted because Windows' own `LowLevelHooksTimeout`
bounds how long any single hook invocation can stall the input pipeline, and
the hook callback (`_make_hook_proc`'s wrapper around `_hook_decide`) is
fully exception-wrapped and **always** calls `user32.CallNextHookEx` on both
success and exception paths, so a failure here cannot break systemwide
keyboard input. The minimal future hardening (swap to `SendMessageTimeoutW`)
is recorded in Known Debt, not treated as a live bug.

**The upload server binds loopback + Tailscale, not `0.0.0.0`, and there is
deliberately no auth token (R7 trim).** `upload_server._bind_addresses`
always includes `127.0.0.1` (the local liveness probe and the advertised
`localhost` URL depend on it — its docstring states the constraint) and
appends the machine's Tailscale IPv4 when available; the LAN wildcard is
never chosen automatically, and a warning is logged when Tailscale is
unavailable and the server ends up loopback-only. The bind set *is* the
access control — this is a single-user, opt-in tool, and a shared-secret
token was explicitly triaged out of scope (recorded as open debt, not
forgotten). `serve --host` (including an explicit `0.0.0.0`) is the
documented escape hatch. Non-Tailscale LAN devices losing access to the
uploader is the **intended** behavior of this change, not a regression.

**`hotkey.py` raises `ImportError` at import time off-Windows, by design.**
`if sys.platform != "win32": raise ImportError("hotkey module is
Windows-only")` runs at module import. Every caller (`cli/attach.py`,
`cli/status.py`, `cli/spawns.py`) imports it lazily, inside a function body,
behind a `get_platform().supports_hotkey()` check, each with a `# ImportError
off-Windows (hotkey.py guards); must stay lazy` comment on the import line.
Hoisting any of these imports to module level breaks `import multideck.cli`
on Linux/macOS.

**The in-body "heavy subsystem" import policy in `cli/` exists because the
registration hub is eager.** `cli/__init__.py` imports every command module
at package-import time (to fire its `@main.command` decorators), so any
subsystem a command module imports at its own top level is paid for on
every `multideck` invocation, including `multideck --help`. `launch`,
`upload_server`, `discover`, and `agent_state` are therefore imported
**inside function bodies** in `cli/` command modules, each carrying a
`# heavy subsystem: in-body per policy` comment. Verified at the tree this
document ships with: `import multideck.cli` loads none of
`multideck.launch`/`upload_server`/`discover`/`agent_state`. (The
`multideck.platform` package `__init__` *is* loaded — `cli/attach.py`
imports `tiling`, which needs the `Platform` type — but that module is a
lightweight ABC + lazy factory; the actually-heavy OS backends
(`platform/windows.py`'s ctypes bindings, etc.) import only when
`get_platform()` is called.)

**The ruff ruleset is a curated, expanded pack (`[tool.ruff.lint]`), no
longer just the `E4, E7, E9, F` audited baseline.** The baseline stays first
in the `select` list (pinned explicitly, immune to ruff's floating defaults);
everything after it is the pre-refactor hardening pack, each group carrying a
one-line why in `pyproject.toml`: hygiene (`W`/`I`/`UP`/`B`/`A`),
simplification & return/raise discipline (`C4`/`SIM`/`RET`/`RSE`/`ISC`/`PIE`),
the complexity ceilings (`C90` + `PLR0912`/`PLR0915`, seeded at the Phase-0
measured max and ratcheted **down** only, never up), the loudness pack
(`T20`/`BLE`/`S110`/`S112`/`TRY`/`LOG`/`G`/`DTZ` — nothing fails silently, so
every error stays Sentry-capturable), and drift guards (`ERA`/`TC`/`TID`/`RUF`,
where `RUF100` is the unused-noqa rot guard). The gate lints `src` + `tests` +
`scripts`; the only sanctioned softening is `[tool.ruff.lint.per-file-ignores]`,
one reason-comment per code — nothing from `src/` goes there. Changing the
`select`/`ignore` list requires a written reason in this file, per house rule.
`ANN401` (no `Any` in annotations) is active in the `select` list now, not
deferred — `Any` elimination happens under ty, the sole type checker (mypy
was retired; see Key Decisions).

**Help-snapshot tests normalize one verified Click difference rather than
pinning a Click version.** `tests/unit/test_cli_structure.py::_normalize_help`
rewrites `[OPTIONS] [COMMAND] [ARGS]...` to `[OPTIONS] COMMAND [ARGS]...`
before comparing — Click 8.4 brackets the metavar for
`invoke_without_command=True` groups (this repo's bare `main --help`), Click
8.3 does not, and this machine's two reachable interpreters resolve
different Click versions. The normalization is a single verified substring,
so the snapshots stay byte-sensitive to everything else (a reparented
command, changed help text). Pinning one Click version would only trade an
environment-dependent false failure for flakiness elsewhere.

**`AGENT_TOOLS` covers deep CLI agents only; IDE tool identity is still
string-matched, on purpose for now (F-CT-003).** `sessions.AGENT_TOOLS` only
knows about `claude`/`codex` — the tools that can resume a specific session.
Whether a project's tool is an IDE (`vscode`/`cursor`/`code`) is still
checked with literal membership tests repeated in `launch.py`,
`upload_server.py`, and `cli/session_picker.py`. This is deferred
consolidation debt (an `IDE_TOOLS` registry is the natural sibling to
`AGENT_TOOLS`), listed below because it's real — not an oversight nobody
noticed, and not something to hot-fix in an unrelated PR.

**mypy retired 2026-07-06 (commit `719d17e`); ty is now the sole type
checker.** Running two type checkers meant two suppression dialects for the
same class of finding — a `# type: ignore` here, a `# ty: ignore` there, for
what is conceptually one problem. Consolidating onto `ty==0.0.56` keeps that
surface singular. The accepted risk is depending on a pre-1.0 checker with
known false positives (documented in CLAUDE.md's gotchas); revisit this
decision once ty ships a 1.0 release.

**`platform/windows.py` and `hotkey.py` are excluded from the main ty pass
(win32 ctypes symbols unresolvable under the host-platform view on Linux)
and checked by a dedicated `ty --python-platform win32` step instead (added
2026-07-07) — full type coverage on every host; if ty's platform emulation
regresses pre-1.0, fall back to a scoped 2-file mypy backstop.**

**`tests/` is not yet under ty.** The gate's ty step only checks `src` and
`scripts` (`ty check src scripts ...`) — `tests/` is staged, tracked future
work (spec §6.5), not an oversight; ruff (lint + format) does cover `tests/`
today.

**All multideck windows share one title grammar (2026-07-07, 0-users breaking
change): `md:` + optional `[!]`/`[x]`/`[+]` badge + name.** Before this, only
the attach path emitted `md:` titles and every consumer did its own string
work (hotkey stripped the prefix, tiling matched exact full titles) — which
made in-place title *rewrites* (the attention daemon's state badges)
impossible without breaking resolution. Now `titles.make_title` is the only
producer and `titles.parse_title` the only consumer (hotkey routing, tiling's
`md-name` mode), so a badge in the title is invisible to matching. The badge
sits at the FRONT because taskbars truncate title tails; working/idle
deliberately render unbadged (quiet title = nothing needs you). psmux session
names remain unprefixed — the grammar applies at the window-title boundary
only. Constraint: project names must not start with the `[?] ` shape.

**Dependency scanning is a separate advisory workflow, not a quality-gate
step (added 2026-07-07).** `.github/workflows/dependency-audit.yml` runs a
pinned `pip-audit==2.10.1` over the exported `uv.lock` closure whenever
dependencies change and on a weekly schedule (advisories are published
without commits), and `.github/dependabot.yml` files weekly version-update
PRs (uv, github-actions, npm — each still gated by the required quality
check). It is deliberately NOT wired into `scripts/check.py`: the gate must
stay deterministic and offline-runnable, and advisory-database state is
external — a new CVE should surface loudly on its own schedule, not
retroactively turn an unrelated commit red at pre-push. The same reasoning
keeps the job out of the branch ruleset's required checks initially; promote
it once its flake rate is known.

## 3. Known debt

Ordered roughly by how likely a future change is to collide with it.

**CI multi-monitor emulation is unavailable (R4-05 → documented limitation,
2026-07-07):** hosted GitHub runners do not materialize `xrandr --setmonitor`
VIRTUAL monitors under Xvfb, so the platform/e2e CI legs exercise windowing
against a single screen; `setup-virtual-displays` emits a loud `::warning`
when this happens instead of pretending otherwise. Multi-monitor placement
logic is covered by `FakePlatform` unit tests only. A real multi-monitor CI
story (self-hosted runner or a working RANDR emulation) is next-cycle work.

**Nine findings carried open into the next audit cycle** (deliberately
triaged out of the fix pass that produced this document, not overlooked):

| Item (provenance) | Substance |
|---|---|
| `IDE_TOOLS` consolidation (F-CT-003) | IDE-vs-CLI-agent tool identity is string-matched in several places instead of one registry — see Key Decisions. |
| Upload server per-request logging (F-IC-001) | `UploadHandler.log_message` routes the stdlib HTTP access log to DEBUG level (deliberately quiet at INFO to avoid logging `?project=` query strings) — so per-request errors surface nowhere at the default level; the rotating `upload` log covers lifecycle events only. |
| Upload retry/robustness (F-IC-003) | The hotkey→server upload path is one HTTP attempt; a flaky mobile/Tailscale link just fails once. |
| Same-second upload filename collision (F-D3-003) | `do_POST` names uploads `f"{int(time.time())}_{basename}"` — two different files for the same project in the same wall-clock second collide. |
| Upload retention sweep (F-D3-004) | `~/.multideck/uploads` has no cleanup/retention policy; it grows forever. |
| `init_config.scan_for_projects` scan behavior (F-D5-004) | The "found `.git` dirs, else fall back to flat immediate children" heuristic and the 300-repo cap haven't been re-examined since first written. |
| `init_config` silent `PermissionError` (F-OB-005) | `except PermissionError: continue` skips unreadable directories with no warning that anything was skipped. |
| Hotkey module architecture (F-CT-005) | `hotkey.py` mixes raw ctypes Win32 bindings, hook lifecycle, upload-trigger logic, and pid-file management in one module; a structural split is future work. |
| `agent_state.py` has zero tests (F-IC-007) | No `tests/unit/test_agent_state.py` exists; the module is stdlib-only and eminently testable. |

**Findings recorded during the fix pass, carried in code on purpose**
(each verified still true on disk; do not drive-by fix — each needs its own
small, tested change):

- **NF-S3-001 — `_menu_down` echoes success unconditionally.** In
  `cli/status.py`, `_menu_down` calls `stop_server(...)` and always prints
  "Stopped upload server." regardless of the (truthful) boolean it returns —
  the sibling `down_cmd` in the same file does check it. Fix direction:
  branch on the return value exactly as `down_cmd` does, or route both
  through one shared helper.
- **NF-S3-002 — stdout/stderr convention for JSON tests existed nowhere.**
  Click's `CliRunner` merges stdout and stderr into `result.output`; JSON
  assertions that read `result.output` corrupt when any stderr diagnostic
  (e.g. the config version warning) fires. Three sites were fixed during the
  audit; the convention ("JSON-body assertions read `result.stdout`,
  diagnostics via `result.stderr`") is now codified in CLAUDE.md — the debt
  is that older tests were never swept for latent instances.
- **NF-S3-003 — `_generate_docs` (`cli/docs.py`) hand-rolls a third, drifted
  schema example.** Confirmed on disk: its inline example-config block
  fabricates an `"aider": "aider --model sonnet"` entry that does not exist
  in `config.DEFAULT_TOOLS`, omits half the settings surface, and its
  `## CLI commands` table does not list `multideck config migrate` even
  though that subcommand is live. Same duplicated-schema-truth class the
  config factory fixed for the runtime path; the docs command wasn't brought
  under that umbrella. Fix direction: derive the sample from
  `config.default_config()`/`settings_to_dict` (or embed
  `multideck.config.example.json`) and generate the command table from the
  live registration set.
- **NF-S3-004 — `_attach_nomux` (`cli/attach.py`) hard-codes the fallback
  command.** `cmd = p.get("cmd") or "claude --continue"` echoes the value of
  `DEFAULT_TOOLS["claude"]` as a literal in the raw-dict attach path; if the
  default command ever changes, this site silently drifts. Fix direction:
  derive the fallback from `DEFAULT_TOOLS` (or the project's resolved tool).
- **NF-S3-005 — `status --json` error-shape asymmetry.** See Key Decisions
  ("status --json … recorded, not missed"). Fix direction: teach
  `_load_config_or_exit` an `as_json` flag (or a small wrapper) emitting
  `json.dumps({"error": ...})`, adopt it in `status_cmd`, and fold `up_cmd`'s
  inline guard onto it (dedup).
- **`cli/config_editor.py` (637 lines) awaits a further split.** Extracted
  whole from the old monolith; separating the menu-driven `_config_menu`
  from the 14 scriptable `config` subcommands is legitimate next-cycle work,
  gated on `_config_menu`'s characterization pin.
- **No validation on config-editor save.** `config_io._save_raw_config`
  writes whatever raw `dict` it's given; a bad hand-entry made through the
  interactive editor isn't caught until the *next* typed `load_config`
  elsewhere raises `ConfigError` — not at save time. Fix direction:
  validate-after-save (parse the just-written file through `load_config` and
  surface warnings/errors immediately).

**Duplication residue found and left alone (each small, each real):**

- **Tailscale-IP resolution exists in four independent places:**
  `upload_server._tailscale_ip` (used by `_bind_addresses` and, via import,
  by `serve_cmd`'s display), `launch._get_tailscale_ip`,
  `cli/spawns._tailnet_host` (the most complete: MagicDNS name → Tailscale
  IP → LAN IP), and `cli/daemons.termius_cmd`'s own inline
  `subprocess.run(["tailscale", "ip", "-4"], ...)` block.
- **Two independent pid-liveness checks:** `hotkey._pid_alive` (Windows-only
  ctypes `OpenProcess`/`GetExitCodeProcess`/`STILL_ACTIVE`) and
  `cli/spawns._pid_alive` (same Windows pattern plus a cross-platform
  `os.kill(pid, 0)` branch) — neither calls the other.
- **`launch.py`'s base-dir expansion chain is duplicated:** the exact
  `os.path.expandvars(os.path.expanduser(base_dir)).replace("/", os.sep)`
  sequence appears in `run_multideck`'s body and again in
  `eligible_psmux_projects` — an `_expand_base_dir` helper is the natural
  dedup, not yet extracted.
- **Up/down command/menu twins are close but not shared:** `up_cmd`/`_menu_up`
  and `down_cmd`/`_menu_down` each independently build a
  select-then-act flow around `bring_up_psmux`/`kill_psmux`; the CLI-command
  and menu variants of each have never been unified.

**Tooling and testing gaps:**

- **`tests/` and `scripts/` are now ruff-linted** (resolves the former "tests
  not linted" gap). `scripts/check.py` invokes `ruff check src tests scripts`
  under the expanded ruleset; `[tool.ruff] src = ["src"]` now only declares the
  first-party import root for isort, not the lint scope. Test-specific softening
  lives in `[tool.ruff.lint.per-file-ignores]` `"tests/**"`, one reason per code.
  (Historical note: an audit-era ledger entry called `tests/unit/test_hotkey.py`'s
  `HTTPServer`/`BaseHTTPRequestHandler` imports unused — on the current tree they
  are *used*, by the live-HTTP test harness added later.)
- **The pathlib migration was deliberately trimmed to predicates only
  (LS-A-002 trim).** `os.path.isdir`/`isfile`/`isabs` sites were converted;
  `os.path.expandvars` (no pathlib equivalent) and
  `normpath`/`commonpath`/`relpath` (used in `discover.py`'s merge-key
  normalization and `_find_base_dir`, and `launch.py`'s path resolution)
  were left as `os.path` calls **because converting them can change the
  exact string values other logic keys on**. Converting them for real needs
  semantic-equivalence tests written first, not a mechanical swap.
- **No identity check before force-killing a recorded pid.** Both
  `upload_server.stop_server` and `hotkey.stop_listener` read a pid file and
  kill that pid directly; neither confirms the live process is still the
  *same* process that wrote the file (vs. a recycled pid). A stale file
  after a crash can kill an innocent process.
- **Hook-title read hardening.** The accepted `GetWindowTextW`-in-hook
  design (Key Decisions) names `SendMessageTimeoutW` as the minimal future
  hardening; nobody has done it.
- **`/health` reports service/port/pid/uptime/session-count with no auth** —
  minor information exposure (Low), consistent with the server's
  no-auth-token posture (Key Decisions).
- **`qrcode` has no optional-extras declaration.** It's a graceful
  try/except import with an install tip, so nothing breaks — but
  `pyproject.toml` declares no `[project.optional-dependencies]` extra for
  it. Cosmetic.
- **`cli/attach.py::_tile_titles` continues past "no monitors" and ignores
  the configured grid.** On the attach path, an empty `list_monitors()` logs
  an ERROR and warns the user but the command still exits 0; and it always
  tiles into a hard-coded `compute_grid(monitors, 2, 1)` regardless of the
  config's `layout.columns`/`layout.rows`, unlike the launch path which
  reads the configured grid.

## 4. Change guide

Three archetypes cover most future changes.

**(a) Add an agent tool.** For a *plain command tool* (no session resume —
launched as-is, like `cursor-agent`/`agy`), only step 3 applies: one
`DEFAULT_TOOLS` entry plus the example-file update it forces. For a
*deeply-integrated* tool (session resume / multi-window, like
`claude`/`codex`), do all four steps:
1. Add `sessions/<tool>.py` with the same two-function shape as
   `sessions/claude.py`: `get_<tool>_session_ids(project_dir, count,
   home_override=None) -> list[str | None]` and
   `build_<tool>_resume(base_cmd, session_id) -> str`.
2. Add one entry to `AGENT_TOOLS` in `sessions/__init__.py`, wiring those
   two functions in as `session_ids`/`resume_command`; set `happy=True` if
   the tool should be eligible for the Happy mobile/web wrap.
3. If the tool should ship as a built-in default, also add it to
   `config.DEFAULT_TOOLS` — deliberately separate concerns: `DEFAULT_TOOLS`
   controls what config generators pre-populate; `AGENT_TOOLS` controls
   resume/multi-window capability. Changing `DEFAULT_TOOLS` requires
   updating `multideck.config.example.json`'s `settings.tools` in the same
   change — `tests/unit/test_config_factory.py::TestExampleConfigMatchesFactory`
   pins the example's settings block to `settings_to_dict(Settings())`
   exactly (that anti-drift pin is the point of the example file).
4. Add a test mirroring `tests/unit/test_tool_registry.py::
   TestOneEditExtensionProof::test_adding_a_tool_is_one_dict_entry` — extend
   `AGENT_TOOLS` via `monkeypatch` and assert the dispatcher picks the new
   tool up with no other code change.

**(b) Add a platform capability:**
1. Add the method (or `supports_*` probe) to the `Platform` ABC in
   `platform/__init__.py` with a safe default — `False` for a probe,
   `raise NotImplementedError(...)` for an operation.
2. Override it per-OS in `platform/windows.py` / `macos.py` / `linux.py`
   only where the backend really has the capability; inheriting the ABC
   default is the correct implementation for backends that don't.
3. Extend `tests/unit/test_platform_contract.py`: parametrize over
   `_DEFAULT_BACKENDS` (`_Bare`, `LinuxPlatform`, `MacOSPlatform`) for the
   default behavior, and add a `@pytest.mark.skipif(sys.platform != "win32",
   ...)` case for the `WindowsPlatform` override (it binds `windll` at
   import, so it can only be exercised on Windows).
4. Gate every call site behind the probe (`get_platform().supports_x()`),
   never a raw `sys.platform` check in business logic.

**(c) Add a CLI command:**
1. New module under `cli/`, importing `main` from `multideck.cli.app` (never
   from the package `__init__`) and attaching commands with
   `@main.command(...)`. Follow the import policy: stdlib and leaf imports
   (`config_io`, `ui`, `paths`, `style`, `config` types) at top; heavy
   subsystems (`launch`, `upload_server`, `discover`, `agent_state`,
   `get_platform()`, lazy `hotkey`) in-body with the one-line why-comment.
2. Add the module to the registration import line in `cli/__init__.py` so
   its commands register; add any test-reachable underscore names to that
   file's re-export block/`__all__` only if tests genuinely need them.
3. Expect `tests/unit/test_cli_structure.py`'s `HELP_SNAPSHOTS` matrix to
   change (a new command appears in `--help`); update the snapshots
   deliberately, never by blind regeneration.
4. Add a smoke test invoking the command via the `runner` fixture
   (`runner.invoke(main, [...])`), asserting on `result.exit_code` and a
   stable substring — JSON bodies via `result.stdout` — always against a
   `--config <tmp_path>` config, never real windows/monitors/psmux.

## 5. How this document stays honest

Three mechanisms: **the gate** (`scripts/check.py`: ruff (lint + `format
--check`) + custom lint MD001-MD004 + ty strict + compileall + vulture +
pytest unit tests with a coverage floor, required green before every commit,
so nothing described here as tested or type-checked silently stops being
so); **pins-first discipline** (every relocation described above as "unchanged"
is backed by a characterization test written *before* the change — 
"unchanged" is a checked claim); and the standing rule that **a mismatch
between this document and the code is itself a defect** — fix the document
or flag the code, never silently trust whichever you read first.
