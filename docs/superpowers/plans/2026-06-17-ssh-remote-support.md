# SSH / Remote Project Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a multideck project run its agent (Claude Code / Codex / any CLI) over `ssh`, or open in VS Code via Remote-SSH, by adding an optional `host` to the project — with all tiling and local behavior unchanged.

**Architecture:** A project gains optional `host` and `remotePath` fields. When `host` is set, the launch loop branches *before* the local-filesystem check: terminal tools launch `wt … -- cmd /k ssh -t <host> "bash -lc 'cd <remoteDir> && <toolcmd>'"`; VS Code launches `code --remote ssh-remote+<host> <remoteDir>`. The window still gets a title/tab color, so the existing title-based tiler is untouched. All command-string construction lives in a new sibling file `scripts/multideck.lib.ps1` (pure, side-effect-free) so it can be unit-tested without launching anything.

**Tech Stack:** Windows PowerShell 5.1+, Windows Terminal (`wt`), OpenSSH client (`ssh`), VS Code Remote-SSH (`code --remote`). Tests are a zero-dependency PowerShell assertion script (no Pester required, so it runs on stock Windows PowerShell 5.1).

**Spec:** `docs/superpowers/specs/2026-06-17-ssh-remote-support-design.md`

---

## File Structure

- **Create `scripts/multideck.lib.ps1`** — three pure functions: `Get-MdRemoteDir`, `Build-MdSshCommand`, `Build-MdCodeArgs`. No side effects, no screen/window calls. Dot-sourced by `multideck.ps1` and by the test script.
- **Create `tests/Test-MdBuilders.ps1`** — zero-dependency unit tests that dot-source the lib and assert exact output strings. Exit code 1 on any failure.
- **Modify `scripts/multideck.ps1`** — dot-source the lib; parse `settings.ssh.shell` into `$sshShell`; warn once if remote projects exist but `ssh` is missing; insert the remote branch at the top of the launch loop. The local branch is left byte-for-byte unchanged.
- **Modify `multideck.config.example.json`** — add `settings.ssh.shell` and two remote example projects.
- **Modify `README.md`** — document `host` / `remotePath` / `settings.ssh.shell`, a "Remote projects over SSH" section, requirements, and troubleshooting entries.

All paths are relative to the repo root `C:\Users\amind\OneDrive\Desktop\Projects\CUSTOM MCPs & PRODUCTIVITY\multideck-ai-agent`.

---

### Task 1: Pure helper `Get-MdRemoteDir` (remotePath ?? path)

**Files:**
- Create: `tests/Test-MdBuilders.ps1`
- Create: `scripts/multideck.lib.ps1`

- [ ] **Step 1: Write the failing test**

Create `tests/Test-MdBuilders.ps1`:

```powershell
# Zero-dependency unit tests for multideck's pure command builders.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\multideck.lib.ps1')

$script:failures = 0
function Assert-Eq($actual, $expected, $name) {
    if ($actual -ceq $expected) {
        Write-Host "PASS: $name" -ForegroundColor Green
    } else {
        $script:failures++
        Write-Host "FAIL: $name" -ForegroundColor Red
        Write-Host "  expected: [$expected]" -ForegroundColor Yellow
        Write-Host "  actual:   [$actual]" -ForegroundColor Yellow
    }
}

# --- Get-MdRemoteDir ---
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = 'api'; remotePath = '/home/u/api' })) '/home/u/api' 'remoteDir uses remotePath when set'
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = '/srv/api' })) '/srv/api' 'remoteDir falls back to path'

if ($script:failures -gt 0) { Write-Host "`n$($script:failures) test(s) failed." -ForegroundColor Red; exit 1 }
Write-Host "`nAll tests passed." -ForegroundColor Green
```

- [ ] **Step 2: Run test to verify it fails**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: FAIL — dot-source throws because `scripts\multideck.lib.ps1` does not exist yet (e.g. "Cannot find path … multideck.lib.ps1"). Non-zero exit.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/multideck.lib.ps1`:

```powershell
<#
.SYNOPSIS
    Pure, side-effect-free command builders for multideck's remote (SSH) support.
    Kept separate from multideck.ps1 so they can be unit-tested without launching
    windows or running the main script. Dot-sourced by multideck.ps1.
#>

# Remote working directory for a project: remotePath when set, else path.
function Get-MdRemoteDir {
    param([Parameter(Mandatory = $true)]$Project)
    if ($Project.remotePath) { return "$($Project.remotePath)" }
    return "$($Project.path)"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: PASS — both `Get-MdRemoteDir` assertions pass, "All tests passed." Exit 0.

- [ ] **Step 5: Commit**

```powershell
git add tests/Test-MdBuilders.ps1 scripts/multideck.lib.ps1
git commit -m @'
Add Get-MdRemoteDir helper with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 2: Pure helper `Build-MdSshCommand` (login-shell wrap)

**Files:**
- Modify: `tests/Test-MdBuilders.ps1`
- Modify: `scripts/multideck.lib.ps1`

- [ ] **Step 1: Write the failing test**

Overwrite `tests/Test-MdBuilders.ps1` with the cumulative content (adds the `Build-MdSshCommand` block before the final tally):

```powershell
# Zero-dependency unit tests for multideck's pure command builders.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\multideck.lib.ps1')

$script:failures = 0
function Assert-Eq($actual, $expected, $name) {
    if ($actual -ceq $expected) {
        Write-Host "PASS: $name" -ForegroundColor Green
    } else {
        $script:failures++
        Write-Host "FAIL: $name" -ForegroundColor Red
        Write-Host "  expected: [$expected]" -ForegroundColor Yellow
        Write-Host "  actual:   [$actual]" -ForegroundColor Yellow
    }
}

# --- Get-MdRemoteDir ---
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = 'api'; remotePath = '/home/u/api' })) '/home/u/api' 'remoteDir uses remotePath when set'
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = '/srv/api' })) '/srv/api' 'remoteDir falls back to path'

# --- Build-MdSshCommand ---
Assert-Eq (Build-MdSshCommand -SshHost 'deploy@10.0.0.5' -RemoteDir '/srv/api' -ToolCmd 'claude --continue') `
    'ssh -t deploy@10.0.0.5 "bash -lc ''cd /srv/api && claude --continue''"' `
    'ssh command wraps in login shell by default'
Assert-Eq (Build-MdSshCommand -SshHost 'deploy@10.0.0.5' -RemoteDir '/srv/api' -ToolCmd 'codex --yolo' -Shell '') `
    'ssh -t deploy@10.0.0.5 "cd /srv/api && codex --yolo"' `
    'ssh command runs raw when shell disabled'

if ($script:failures -gt 0) { Write-Host "`n$($script:failures) test(s) failed." -ForegroundColor Red; exit 1 }
Write-Host "`nAll tests passed." -ForegroundColor Green
```

(In a PowerShell single-quoted string, `''` is one literal `'`, so the first expected value is exactly `ssh -t deploy@10.0.0.5 "bash -lc 'cd /srv/api && claude --continue'"`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: FAIL — the `Get-MdRemoteDir` lines PASS, then the call to `Build-MdSshCommand` throws "The term 'Build-MdSshCommand' is not recognized…". Non-zero exit.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/multideck.lib.ps1`:

```powershell

# Build the 'ssh -t <host> "..."' command that runs an agent in a remote dir.
# With $Shell set (default 'bash -lc') the remote command is wrapped in a login
# shell so the remote PATH (nvm/asdf/Homebrew/~/.local/bin) is sourced.
function Build-MdSshCommand {
    param(
        [Parameter(Mandatory = $true)][string]$SshHost,
        [Parameter(Mandatory = $true)][string]$RemoteDir,
        [Parameter(Mandatory = $true)][string]$ToolCmd,
        [string]$Shell = 'bash -lc'
    )
    $inner  = "cd $RemoteDir && $ToolCmd"
    $remote = if ($Shell) { "$Shell '$inner'" } else { $inner }
    return "ssh -t $SshHost `"$remote`""
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: PASS — all four assertions pass, "All tests passed." Exit 0.

- [ ] **Step 5: Commit**

```powershell
git add tests/Test-MdBuilders.ps1 scripts/multideck.lib.ps1
git commit -m @'
Add Build-MdSshCommand with login-shell wrap and tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 3: Pure helper `Build-MdCodeArgs` (VS Code Remote-SSH)

**Files:**
- Modify: `tests/Test-MdBuilders.ps1`
- Modify: `scripts/multideck.lib.ps1`

- [ ] **Step 1: Write the failing test**

Overwrite `tests/Test-MdBuilders.ps1` with the full cumulative content (adds the `Build-MdCodeArgs` block):

```powershell
# Zero-dependency unit tests for multideck's pure command builders.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\multideck.lib.ps1')

$script:failures = 0
function Assert-Eq($actual, $expected, $name) {
    if ($actual -ceq $expected) {
        Write-Host "PASS: $name" -ForegroundColor Green
    } else {
        $script:failures++
        Write-Host "FAIL: $name" -ForegroundColor Red
        Write-Host "  expected: [$expected]" -ForegroundColor Yellow
        Write-Host "  actual:   [$actual]" -ForegroundColor Yellow
    }
}

# --- Get-MdRemoteDir ---
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = 'api'; remotePath = '/home/u/api' })) '/home/u/api' 'remoteDir uses remotePath when set'
Assert-Eq (Get-MdRemoteDir ([pscustomobject]@{ path = '/srv/api' })) '/srv/api' 'remoteDir falls back to path'

# --- Build-MdSshCommand ---
Assert-Eq (Build-MdSshCommand -SshHost 'deploy@10.0.0.5' -RemoteDir '/srv/api' -ToolCmd 'claude --continue') `
    'ssh -t deploy@10.0.0.5 "bash -lc ''cd /srv/api && claude --continue''"' `
    'ssh command wraps in login shell by default'
Assert-Eq (Build-MdSshCommand -SshHost 'deploy@10.0.0.5' -RemoteDir '/srv/api' -ToolCmd 'codex --yolo' -Shell '') `
    'ssh -t deploy@10.0.0.5 "cd /srv/api && codex --yolo"' `
    'ssh command runs raw when shell disabled'

# --- Build-MdCodeArgs ---
$codeRemote = Build-MdCodeArgs -Dir '/home/ubuntu/work/api' -SshHost 'ubuntu@vm-2'
Assert-Eq ($codeRemote -join '|') '/c|code|--remote|ssh-remote+ubuntu@vm-2|"/home/ubuntu/work/api"' 'code args include --remote when host set'
$codeLocal = Build-MdCodeArgs -Dir 'C:\code\docs'
Assert-Eq ($codeLocal -join '|') '/c|code|"C:\code\docs"' 'code args are local when no host'

if ($script:failures -gt 0) { Write-Host "`n$($script:failures) test(s) failed." -ForegroundColor Red; exit 1 }
Write-Host "`nAll tests passed." -ForegroundColor Green
```

- [ ] **Step 2: Run test to verify it fails**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: FAIL — the first four assertions PASS, then `Build-MdCodeArgs` throws "not recognized". Non-zero exit.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/multideck.lib.ps1`:

```powershell

# Build the Start-Process cmd ArgumentList for opening VS Code, locally or - when
# $SshHost is set - over Remote-SSH (code --remote ssh-remote+<host> <dir>).
function Build-MdCodeArgs {
    param(
        [Parameter(Mandatory = $true)][string]$Dir,
        [string]$SshHost
    )
    if ($SshHost) {
        return @('/c', 'code', '--remote', "ssh-remote+$SshHost", "`"$Dir`"")
    }
    return @('/c', 'code', "`"$Dir`"")
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: PASS — all six assertions pass, "All tests passed." Exit 0.

- [ ] **Step 5: Commit**

```powershell
git add tests/Test-MdBuilders.ps1 scripts/multideck.lib.ps1
git commit -m @'
Add Build-MdCodeArgs for VS Code Remote-SSH with tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 4: Wire the lib + `settings.ssh.shell` + soft ssh check into multideck.ps1

**Files:**
- Modify: `scripts/multideck.ps1` (after `param(...)` block ~line 62; settings block ~line 331; after group filter ~line 345)

- [ ] **Step 1: Dot-source the lib**

In `scripts/multideck.ps1`, immediately after the closing `)` of the `param( … )` block (line 62) and before the `# --- Make this launcher Per-Monitor-DPI-Aware` comment, insert:

```powershell

# Pure command builders for remote/SSH support; kept in a sibling file so they
# can be unit-tested without running this script. See tests/Test-MdBuilders.ps1.
. (Join-Path $PSScriptRoot 'multideck.lib.ps1')
```

- [ ] **Step 2: Parse `settings.ssh.shell` into `$sshShell`**

Find this block (currently ~lines 328-331):

```powershell
$tools = @{ claude = "claude --continue"; codex = "codex --yolo" }
if ($cfg.settings.tools) {
    foreach ($prop in $cfg.settings.tools.PSObject.Properties) { $tools[$prop.Name] = "$($prop.Value)" }
}
```

Insert directly **after** it:

```powershell

# Login-shell wrapper for remote agent commands (default 'bash -lc'); "" disables wrapping.
$sshShell = "bash -lc"
if ($cfg.settings.ssh -and $null -ne $cfg.settings.ssh.shell) { $sshShell = "$($cfg.settings.ssh.shell)" }
```

- [ ] **Step 3: Add the soft `ssh` availability check**

Find the end of the group-filter block (currently ~line 345, the line `}` that closes `if ($Group) { … }`), just before the `# ------…- build the per-monitor grid` comment. Insert:

```powershell

# Warn once if remote projects are configured but the OpenSSH client is missing.
if (@($projects | Where-Object { $_.host }).Count -gt 0 -and -not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: remote projects are configured but 'ssh' is not on PATH. Enable the Windows OpenSSH client (Settings > Optional features)." -ForegroundColor Yellow
}
```

- [ ] **Step 4: Verify the script still parses and runs locally (regression)**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\multideck.ps1 -DryRun -Config multideck.config.example.json`
Expected: it prints the screen/slot line and a dry-run plan for the example's **local** projects with NO errors (the example has no remote projects yet, so no ssh warning). It must not throw. (Projects under a non-existent `baseDir` may print `SKIP: … not found` — that is fine and pre-existing.)

- [ ] **Step 5: Commit**

```powershell
git add scripts/multideck.ps1
git commit -m @'
Wire SSH lib, settings.ssh.shell, and ssh availability check into multideck

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 5: Add the remote branch to the launch loop

**Files:**
- Modify: `scripts/multideck.ps1` (launch loop, currently ~lines 371-410)

- [ ] **Step 1: Insert the remote branch at the top of the loop**

Find this exact code at the start of the `foreach ($p in $projects)` loop (currently ~lines 371-377):

```powershell
foreach ($p in $projects) {
    if ($null -ne $p.enabled -and -not $p.enabled) { continue }
    if (-not $p.path) { Write-Host "SKIP: project entry with no 'path'" -ForegroundColor Yellow; continue }

    $raw = Resolve-MdPath "$($p.path)"
    $dir = if ([System.IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $baseDir $raw }
    if (-not (Test-Path $dir)) { Write-Host "SKIP: $($p.path) not found ($dir)" -ForegroundColor Yellow; continue }
```

Replace it with (inserts the remote block between the `path` check and the local resolution; the local lines are kept exactly as-is):

```powershell
foreach ($p in $projects) {
    if ($null -ne $p.enabled -and -not $p.enabled) { continue }
    if (-not $p.path) { Write-Host "SKIP: project entry with no 'path'" -ForegroundColor Yellow; continue }

    # ---------------------------------------------------------- remote (SSH) projects
    if ($p.host) {
        $tool      = if ($p.tool) { "$($p.tool)" } else { $defaultTool }
        $remoteDir = Get-MdRemoteDir $p

        if ($tool -eq "code") {
            # VS Code Remote-SSH. Match by the remote folder basename (what VS Code shows).
            $name    = if ($p.title) { "$($p.title)" } else { Split-Path ("$remoteDir" -replace '/', '\') -Leaf }
            $running = [WinPos]::FindByTitleContains($name) -ne [IntPtr]::Zero
            if (-not $running -and -not $DryRun) {
                Start-Process cmd -ArgumentList (Build-MdCodeArgs -Dir $remoteDir -SshHost "$($p.host)") -WindowStyle Hidden
                Start-Sleep -Milliseconds $launchDelay
            }
            if (-not $running) { $newCount++ }
            $targets += @{ name = $name; match = "contains"; new = (-not $running) }
            Write-Host ("{0} {1} [code @ ssh-remote+{2}:{3}]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name, "$($p.host)", $remoteDir) `
                -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
            continue
        }

        $name = if ($p.title) { "$($p.title)" } else { Split-Path ("$($p.path)" -replace '/', '\') -Leaf }
        $cmd  = $tools[$tool]
        if (-not $cmd) { Write-Host "SKIP: $name - unknown tool '$tool' (add it under settings.tools)" -ForegroundColor Yellow; continue }

        $running = [WinPos]::FindByTitle($name) -ne [IntPtr]::Zero
        if (-not $running -and -not $DryRun) {
            $sshCmd = Build-MdSshCommand -SshHost "$($p.host)" -RemoteDir $remoteDir -ToolCmd $cmd -Shell $sshShell
            $wtArgs = "-w new --title `"$name`""
            if ($p.color) { $wtArgs += " --tabColor `"$($p.color)`"" }
            $wtArgs += " --suppressApplicationTitle -- cmd /k $sshCmd"
            Start-Process wt -ArgumentList $wtArgs
            Start-Sleep -Milliseconds $launchDelay
        }
        if (-not $running) { $newCount++ }
        $targets += @{ name = $name; match = "exact"; new = (-not $running) }
        Write-Host ("{0} {1} [{2} @ {3}:{4}]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name, $tool, "$($p.host)", $remoteDir) `
            -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
        continue
    }

    # ---------------------------------------------------------- local projects
    $raw = Resolve-MdPath "$($p.path)"
    $dir = if ([System.IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $baseDir $raw }
    if (-not (Test-Path $dir)) { Write-Host "SKIP: $($p.path) not found ($dir)" -ForegroundColor Yellow; continue }
```

- [ ] **Step 2: Write the dry-run integration check**

Create a temp config and run a dry run (this verifies the remote branch builds the right annotations and that the local `Test-Path` check is skipped for remote projects):

```powershell
$cfgPath = Join-Path $env:TEMP 'md-ssh-dryrun.config.json'
@'
{
  "layout": { "columns": 2, "rows": 1 },
  "settings": {
    "defaultTool": "claude",
    "ssh": { "shell": "bash -lc" },
    "tools": { "claude": "claude --continue", "codex": "codex --yolo" }
  },
  "projects": [
    { "host": "deploy@10.0.0.5", "path": "/srv/api", "tool": "codex" },
    { "host": "ubuntu@vm-2", "path": "api", "remotePath": "/home/ubuntu/work/api", "tool": "code" }
  ]
}
'@ | Set-Content -LiteralPath $cfgPath -Encoding ascii
```

- [ ] **Step 3: Run the dry run to verify the output**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\multideck.ps1 -DryRun -Config $env:TEMP\md-ssh-dryrun.config.json`
Expected output contains both annotated NEW lines and **no** `SKIP: … not found` lines:

```
NEW:  api [codex @ deploy@10.0.0.5:/srv/api]
NEW:  api [code @ ssh-remote+ubuntu@vm-2:/home/ubuntu/work/api]
```

(There may also be a `WARNING: … 'ssh' is not on PATH` line if the OpenSSH client is not installed — that is expected and fine. The key checks: both `[… @ …]` lines appear, and neither remote project is skipped with "not found".)

- [ ] **Step 4: Run the unit tests again (no regressions)**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: PASS — "All tests passed." Exit 0.

- [ ] **Step 5: Commit**

```powershell
git add scripts/multideck.ps1
git commit -m @'
Launch remote projects over ssh / VS Code Remote-SSH

A project with a `host` now launches its agent via ssh -t (login-shell
wrapped) or opens VS Code with --remote ssh-remote+<host>, skipping the
local path check. Tiling is unchanged. Dry-run annotates the remote target.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 6: Document the feature (example config + README)

**Files:**
- Modify: `multideck.config.example.json`
- Modify: `README.md`

- [ ] **Step 1: Update the example config**

Overwrite `multideck.config.example.json` with:

```json
{
  "baseDir": "C:/Users/you/code",

  "layout": {
    "columns": 2,
    "rows": 1
  },

  "settings": {
    "defaultTool": "claude",
    "settleSeconds": 3,
    "launchDelayMs": 400,
    "ssh": { "shell": "bash -lc" },
    "tools": {
      "claude": "claude --continue",
      "codex": "codex --yolo"
    }
  },

  "projects": [
    { "path": "internal/api",        "group": "internal", "color": "#3b82f6" },
    { "path": "internal/web",        "group": "internal", "color": "#22c55e" },
    { "path": "infra/terraform",     "group": "infra",    "color": "#f59e0b", "tool": "codex" },
    { "path": "docs",                "group": "internal", "color": "#a855f7", "tool": "code"  },
    { "path": "experiments/spike",   "group": "labs",     "color": "#ef4444", "enabled": false },
    { "path": "C:/work/ops-scripts", "title": "ops" },

    { "host": "deploy@10.0.0.5", "path": "/srv/api",  "group": "remote", "color": "#06b6d4", "tool": "claude" },
    { "host": "deploy@10.0.0.5", "path": "/srv/web",  "group": "remote", "color": "#ec4899", "tool": "codex"  },
    { "host": "ubuntu@vm-2",     "path": "api", "remotePath": "/home/ubuntu/work/api", "group": "remote", "tool": "code" }
  ]
}
```

- [ ] **Step 2: Add `host` and `remotePath` rows to the README project field table**

In `README.md`, find the project field-table row:

```markdown
| `enabled` | project | `true` | Set `false` to skip a project without deleting it. |
```

Replace it with:

```markdown
| `enabled` | project | `true` | Set `false` to skip a project without deleting it. |
| `host` | project | none | SSH target (`user@ip`, `user@host`, or an ssh-config alias). When set, the project runs **remotely** — the agent starts over `ssh`, or VS Code opens via Remote-SSH. |
| `remotePath` | project | `path` | Remote working directory, only needed when it differs from `path`. For `tool:"code"`, use an absolute remote path. |
```

- [ ] **Step 3: Add the `settings.ssh.shell` row to the README settings table**

In `README.md`, find the settings-table row:

```markdown
| `settings.tools` | settings | claude, codex | Map of tool name → command run inside Windows Terminal. |
```

Replace it with:

```markdown
| `settings.tools` | settings | claude, codex | Map of tool name → command run inside Windows Terminal. |
| `settings.ssh.shell` | settings | `bash -lc` | Login shell that wraps remote agent commands so the remote `PATH` is sourced. Set `""` to run unwrapped, or e.g. `sh -lc` / `zsh -lc`. |
```

- [ ] **Step 4: Add the "Remote projects over SSH" section**

In `README.md`, find the last line of the "Adding your own agent / tool" section:

```markdown
The command runs via `cmd /k <command>` inside a fresh Windows Terminal tab opened in the project folder. The special tool name `code` is handled separately — it launches VS Code in its own window and matches that window by title.
```

Insert directly **after** it:

```markdown

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
```

- [ ] **Step 5: Add requirements + troubleshooting notes**

In `README.md`, find the requirement line:

```markdown
- Whatever you launch: the **[Claude Code](https://www.anthropic.com/claude-code)** CLI, **Codex**, **[VS Code](https://code.visualstudio.com/)** (`code` on PATH), etc.
```

Replace it with:

```markdown
- Whatever you launch: the **[Claude Code](https://www.anthropic.com/claude-code)** CLI, **Codex**, **[VS Code](https://code.visualstudio.com/)** (`code` on PATH), etc.
- For **remote projects**: the **OpenSSH client** (`ssh` on PATH — built into Windows 10/11, enable via *Settings → System → Optional features*), key-based auth set up for the host, and for remote VS Code the **[Remote-SSH extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh)**.
```

Then find the troubleshooting bullet:

```markdown
- **`wt` not recognized** — install [Windows Terminal](https://aka.ms/terminal).
```

Insert directly **after** it:

```markdown
- **Remote window opens then closes / agent "not found"** — the remote tool isn't on the non-login `PATH`. Keep the default `settings.ssh.shell` of `bash -lc` (login-shell wrap), or set it to your remote shell. The window stays at a local prompt so you can read the error.
- **`ssh` not recognized** — enable the Windows OpenSSH client (*Settings → System → Optional features → Add → OpenSSH Client*).
- **Remote VS Code doesn't connect** — install the Remote-SSH extension and confirm `ssh <host>` works from a normal terminal first; use an absolute `remotePath`.
```

- [ ] **Step 6: Verify the example config is valid JSON and still dry-runs**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Raw multideck.config.example.json | ConvertFrom-Json | Out-Null; 'valid json'"`
Expected: prints `valid json` with no error.

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\multideck.ps1 -DryRun -Config multideck.config.example.json -Group remote`
Expected: the three `remote`-group projects print with `[… @ …]` annotations and are not skipped as "not found".

- [ ] **Step 7: Commit**

```powershell
git add multideck.config.example.json README.md
git commit -m @'
Document SSH/remote projects in example config and README

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 7: Final verification + manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit suite**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File tests\Test-MdBuilders.ps1`
Expected: "All tests passed." Exit 0.

- [ ] **Step 2: Confirm local behavior is unchanged**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\multideck.ps1 -DryRun -Config multideck.config.example.json`
Expected: the local example projects still print their normal `[claude]` / `[codex]` / `[code]` dry-run lines (no `@ host` annotation), proving the local path is untouched.

- [ ] **Step 3: Manual smoke test against a real host (requires an SSH target)**

Pick a reachable host you can `ssh` into with keys (a VM, a server, or your own machine via `ssh localhost` if an SSH server is enabled). Create `multideck.config.json` at the repo root, e.g.:

```jsonc
{
  "settings": { "defaultTool": "claude", "ssh": { "shell": "bash -lc" },
    "tools": { "claude": "claude --continue", "codex": "codex --yolo" } },
  "projects": [
    { "host": "<you@host>", "path": "<absolute remote dir>", "tool": "codex" },
    { "host": "<you@host>", "path": "<absolute remote dir>", "tool": "code" }
  ]
}
```

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\multideck.ps1 -Go`
Verify, recording results in the PR:
- A Windows Terminal window opens, connects to the host, `cd`s into the remote dir, and starts the agent.
- A VS Code window opens already connected via Remote-SSH to the remote folder.
- Both windows snap into the monitor grid.
- Closing the agent / dropping SSH leaves the terminal window open at a local prompt (not vanished).

- [ ] **Step 4: Update the spec status (optional) and confirm clean tree**

Run: `git status`
Expected: clean working tree; the branch `feat/ssh-remote-support` holds the SSH feature commits on top of the restructure.

---

## Self-Review

**Spec coverage** (each spec section → task):
- Config schema `host` / `remotePath` → Tasks 1, 5, 6.
- `settings.ssh.shell` (default `bash -lc`, `""` disables) → Tasks 2, 4, 6.
- Dispatch (remote code vs ssh terminal vs local, skip local Test-Path) → Task 5.
- CLI-over-ssh command incl. `ssh -t`, login-shell wrap, `cmd /k` persistence → Tasks 2, 5.
- VS Code Remote-SSH command + basename matching → Tasks 3, 5.
- Tiling unchanged → Task 5 keeps the local block + targets/match shape identical; verified in Task 7 Step 2.
- Dry-run annotation → Task 5 Steps 2-3.
- Soft `ssh` check → Task 4.
- Edge cases (unknown tool + host; basename collision documented) → Task 5 (unknown-tool skip retained) and spec/README notes.
- Testing (pure builders unit-tested; manual smoke) → Tasks 1-3, 7.
- Out of scope (no ~/.ssh/config scan, no tunnels, no password automation) → not implemented, documented in README (Task 6).

**Placeholder scan:** none — every code/step block is concrete; no TBD/TODO/"handle errors".

**Type/name consistency:** `Get-MdRemoteDir`, `Build-MdSshCommand` (params `-SshHost`, `-RemoteDir`, `-ToolCmd`, `-Shell`), and `Build-MdCodeArgs` (params `-Dir`, `-SshHost`) are defined in Tasks 1-3 and called with the same names/signatures in Task 5. `$sshShell` defined in Task 4, consumed in Task 5. `$remoteDir`, `$name`, `$targets` `@{ name; match; new }`, and `$newCount` match the existing loop/tiler contract.
