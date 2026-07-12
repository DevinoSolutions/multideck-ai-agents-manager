# Changelog

All notable changes to multideck are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-07-12

Initial public release. multideck opens every project in its own terminal, launches
its AI agent, and auto-tiles every window across every monitor — one command, every
tool, every screen.

### Added

- **Launch & tile pipeline** — `multideck` (interactive menu), `multideck --go`
  (skip the menu), `multideck -g <group>` (launch one group), and
  `multideck --retile-all` open each configured project in its own terminal, start
  its agent, and tile every window into a per-screen columns×rows grid with true
  physical-pixel placement and per-monitor DPI awareness on Windows, macOS, and
  Linux.
- **Zero-config bootstrap** — first run scans your Claude, Codex, and VS Code
  history to generate a starter config; `multideck --init [--base-dir <folder>]`
  regenerates it from recent sessions or a folder of git repositories.
- **Session resume for Claude Code and Codex** — deeply integrated CLI agents
  resume the most recent session per window (`claude --continue`, `codex`), and each
  additional window resumes the next-most-recent session. Cursor Agent, VS Code,
  Cursor, and arbitrary custom tools are also supported.
- **Per-window tool & command overrides** — a project's `windows` list opens the
  same project in several windows, each with optional per-window `tool`/`command`
  overrides; the legacy `int` and `["name", …]` window forms still parse and are
  normalized on migration.
- **psmux persistent sessions + SSH attach (Windows)** — with `settings.psmux`,
  each project runs in a named, detached psmux session you can reattach from
  anywhere. `multideck up` ensures a session per project, `multideck sessions`
  lists and attaches them, `multideck attach <host>` brings a host's sessions up
  over SSH and tiles them locally, and `multideck termius` emits an SSH config
  entry that opens the session picker.
- **Attention stack** — `multideck attention -d` runs a daemon that badges window
  titles with each agent's state, flashes the taskbar on needs-input/error, and can
  push toast/ntfy notifications (`settings.attention`); `multideck watch` shows a
  live, most-urgent-first table where a digit key focuses that window. Agent state
  is fed by Claude Code hooks and Codex notify.
- **Mobile image upload over Tailscale** — `multideck serve` runs a small HTTP
  upload server bound only to loopback and your Tailscale IP (never the LAN
  wildcard; `--host` is the escape hatch), `multideck mobile` prints a phone URL and
  QR code for a home-screen web app, and the Alt+V hotkey (Windows) uploads the
  clipboard image into the focused session. There is deliberately no auth token —
  the bind set is the access control.
- **Diagnostics, status & lifecycle** — `multideck doctor [--json]` diagnoses the
  environment (config, env vars, agent tools on PATH, terminal, monitors, writable
  dirs, Tailscale, upload port), `multideck status [--json]` reports session and
  daemon health with actionable exit codes (0 healthy, 1 config error, 3 degraded),
  and `multideck down [--all] [--server]` stops sessions and, optionally, the upload
  server.
- **Config schema v3 + migration** — typed, versioned JSON config with an
  interactive editor, `multideck config` (14 subcommands, including `migrate`), and
  `multideck docs` (generated schema reference). `multideck config migrate`
  normalizes legacy window forms, stamps the current schema version, and persists
  deterministically derived project colors; loading a config never rewrites it.
- **Packaging** — installs as the `multideck` console script with a minimal core
  (`click`, `pydantic-settings`) and optional extras for Sentry error reporting
  (`sentry`), Windows toast notifications (`toast`), and QR rendering (`qr`).

[1.0.0]: https://github.com/DevinoSolutions/multideck-ai-agents-manager/releases/tag/v1.0.0
