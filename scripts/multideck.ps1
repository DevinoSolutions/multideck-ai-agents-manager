<#
.SYNOPSIS
    multideck - open every project in its own terminal (Claude Code / Codex / VS Code /
    any CLI agent) and auto-tile them into a grid across ALL your monitors.

.DESCRIPTION
    Reads multideck.config.json (at the repo root beside the .bat launchers, or pass
    -Config <path>). For each
    enabled project it launches the configured tool in that directory - inside a Windows
    Terminal window, or VS Code in its own window - then snaps every window into a
    per-monitor grid using TRUE physical pixels (Per-Monitor-DPI-Aware), so geometry
    stays correct on mixed-scale monitor setups.

    Run with no arguments in a console to get an interactive menu.

.PARAMETER RetileAll
    Re-tile EVERY matching window, including ones already open - not just freshly launched.

.PARAMETER DryRun
    Print what would happen and exit without launching or moving anything.

.PARAMETER Init
    Generate multideck.config.json by scanning a folder (-BaseDir) for git repositories.

.PARAMETER BaseDir
    Folder to scan with -Init. If omitted you'll be prompted.

.PARAMETER Group
    Launch only projects whose "group" matches (e.g. -Group lead-gen).

.PARAMETER Go
    Skip the interactive menu and run directly (launch + tile new windows).

.PARAMETER Force
    With -Init, overwrite an existing config without asking.

.PARAMETER Config
    Path to a config file. Default: multideck.config.json at the repo root.

.EXAMPLE
    multideck                      # interactive menu
.EXAMPLE
    multideck -Go                  # launch missing + tile, no menu
.EXAMPLE
    multideck -RetileAll           # re-snap every open window
.EXAMPLE
    multideck -Group lead-gen      # launch just one group
.EXAMPLE
    multideck -Init -BaseDir C:\code   # auto-build a config from a folder

.LINK
    https://github.com/DevinoSolutions/multideck-ai-agent
#>
param(
    [switch]$RetileAll,
    [switch]$DryRun,
    [switch]$Init,
    [switch]$Go,
    [switch]$Force,
    [string]$Group,
    [string]$BaseDir,
    [string]$Config
)

# Pure command builders for remote/SSH support; kept in a sibling file so they
# can be unit-tested without running this script. See tests/Test-MdBuilders.ps1.
. (Join-Path $PSScriptRoot 'multideck.lib.ps1')

# --- Make this launcher Per-Monitor-DPI-Aware (V2) BEFORE any screen/window API.
#     Without this, PowerShell runs DPI-unaware: Screen bounds and MoveWindow use a
#     virtualized 96-DPI space, so windows mis-scale on any monitor whose scale
#     differs from the primary. With it, Screen.AllScreens + MoveWindow use TRUE
#     physical pixels per monitor, so the grid is correct on every screen. ---
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DpiAware {
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr v);
    [DllImport("shcore.dll")] static extern int  SetProcessDpiAwareness(int v);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    public static void PerMonitorV2() {
        try { if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return; } catch {} // PerMonitorV2 (Win10 1703+)
        try { if (SetProcessDpiAwarenessContext(new IntPtr(-3))) return; } catch {} // PerMonitor   (Win10 1607+)
        try { SetProcessDpiAwareness(2); return; } catch {}                          // PerMonitor   (Win8.1+)
        try { SetProcessDPIAware(); } catch {}                                       // System       (Vista+)
    }
}
"@
[DpiAware]::PerMonitorV2()

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public class WinPos {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    public static IntPtr FindByTitle(string title) {
        IntPtr result = IntPtr.Zero;
        EnumWindows((hWnd, _) => {
            if (!IsWindowVisible(hWnd)) return true;
            StringBuilder sb = new StringBuilder(512);
            GetWindowText(hWnd, sb, 512);
            if (sb.ToString() == title) { result = hWnd; return false; }
            return true;
        }, IntPtr.Zero);
        return result;
    }

    public static IntPtr FindByTitleContains(string needle) {
        IntPtr result = IntPtr.Zero;
        EnumWindows((hWnd, _) => {
            if (!IsWindowVisible(hWnd)) return true;
            StringBuilder sb = new StringBuilder(512);
            GetWindowText(hWnd, sb, 512);
            if (sb.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) { result = hWnd; return false; }
            return true;
        }, IntPtr.Zero);
        return result;
    }
}
"@

$script:Interactive = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
$script:Palette = @('#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4',
                    '#ec4899', '#84cc16', '#f97316', '#14b8a6', '#6366f1', '#eab308')

function Resolve-MdPath([string]$path) {
    if (-not $path) { return $path }
    $path = [Environment]::ExpandEnvironmentVariables($path)
    if ($path -like '~*') { $path = Join-Path $HOME ($path.Substring(1).TrimStart('\', '/')) }
    return ($path -replace '/', '\')          # accept forward slashes in configs
}

function Read-MdConfig([string]$path) {
    return (Get-Content -Raw -LiteralPath $path | ConvertFrom-Json)
}

# Scan a folder for git repos and write (or preview) a config. Groups come from the
# top folder of each repo's relative path, so INTERNAL/caly -> group "INTERNAL".
function Invoke-MdInit {
    param([string]$Root, [string]$OutPath, [switch]$DryRun, [switch]$Force, [int]$MaxDepth = 3)

    if (-not $Root) {
        if ($script:Interactive) { $Root = (Read-Host "Base folder to scan for projects").Trim('"', ' ') }
        if (-not $Root) { Write-Host "No base folder given." -ForegroundColor Yellow; return $false }
    }
    if (-not (Test-Path $Root)) { Write-Host "Folder not found: $Root" -ForegroundColor Red; return $false }
    $root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')

    Write-Host "Scanning $root for git repositories..." -ForegroundColor Cyan
    $skip = @('.git', 'node_modules', '.svn', '.hg', 'bin', 'obj', '.next', 'dist', 'vendor', '.venv', 'target')
    $repos = New-Object System.Collections.Generic.List[string]
    $stack = New-Object System.Collections.Generic.Stack[object]
    $stack.Push([pscustomobject]@{ Dir = $root; Depth = 0 })
    while ($stack.Count -gt 0 -and $repos.Count -lt 300) {
        $node = $stack.Pop()
        if ((Test-Path (Join-Path $node.Dir '.git')) -and $node.Depth -ge 1) { $repos.Add($node.Dir); continue }
        if ($node.Depth -lt $MaxDepth) {
            try {
                Get-ChildItem -LiteralPath $node.Dir -Directory -Force -ErrorAction Stop |
                    Where-Object { $skip -notcontains $_.Name } |
                    ForEach-Object { $stack.Push([pscustomobject]@{ Dir = $_.FullName; Depth = $node.Depth + 1 }) }
            } catch {}
        }
    }

    $dirs = if ($repos.Count -gt 0) { $repos } else {
        Write-Host "No git repos found - falling back to immediate subfolders." -ForegroundColor Yellow
        @(Get-ChildItem -LiteralPath $root -Directory -Force | Where-Object { $skip -notcontains $_.Name } | ForEach-Object { $_.FullName })
    }
    $dirs = @($dirs | Sort-Object)
    if ($dirs.Count -eq 0) { Write-Host "Nothing found under $root." -ForegroundColor Yellow; return $false }

    # detect duplicate leaf folder names so generated window titles stay unique
    $leaves = $dirs | ForEach-Object { ($_ -replace '\\', '/').Split('/')[-1] }
    $dupLeaves = @($leaves | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })

    $projects = @()
    for ($i = 0; $i -lt $dirs.Count; $i++) {
        $rel = ($dirs[$i].Substring($root.Length).TrimStart('\') -replace '\\', '/')
        $parts = $rel -split '/'
        $proj = [ordered]@{ path = $rel }
        if ($parts.Count -gt 1) { $proj.group = $parts[0] }
        if ($dupLeaves -contains $parts[-1]) { $proj.title = ($rel -replace '/', '-') }  # keep titles unique
        $proj.color = $script:Palette[$i % $script:Palette.Count]
        $projects += $proj
    }

    $cfg = [ordered]@{
        baseDir  = ($root -replace '\\', '/')
        layout   = [ordered]@{ columns = 2; rows = 1 }
        settings = [ordered]@{
            defaultTool = 'claude'; settleSeconds = 3; launchDelayMs = 400
            tools = [ordered]@{ claude = 'claude --continue'; codex = 'codex --yolo' }
        }
        projects = $projects
    }

    $groups = @($projects | ForEach-Object { $_.group } | Where-Object { $_ } | Sort-Object -Unique)
    Write-Host "Found $($projects.Count) project(s)$(if($groups.Count){" in groups: $($groups -join ', ')"})." -ForegroundColor Green
    $projects | ForEach-Object { Write-Host ("  {0,-40} {1}" -f $_.path, $(if($_.group){"[$($_.group)]"}else{""})) -ForegroundColor Gray }

    if ($DryRun) { Write-Host "(dry run - not written)" -ForegroundColor Magenta; return $true }

    if ((Test-Path $OutPath) -and -not $Force) {
        if ($script:Interactive) {
            if ((Read-Host "$OutPath exists. Overwrite? (y/N)") -notmatch '^(y|yes)$') { Write-Host "Cancelled." -ForegroundColor Yellow; return $false }
        } else { Write-Host "$OutPath exists - use -Force to overwrite." -ForegroundColor Yellow; return $false }
    }

    [System.IO.File]::WriteAllText($OutPath, ($cfg | ConvertTo-Json -Depth 6))
    Write-Host "Wrote $($projects.Count) project(s) to $OutPath" -ForegroundColor Green
    Write-Host "Review it, then run multideck." -ForegroundColor Cyan
    return $true
}

function Show-MdMenu {
    param($Cfg)
    $groups = @($Cfg.projects | ForEach-Object { $_.group } | Where-Object { $_ } | Sort-Object -Unique)
    while ($true) {
        Write-Host ""
        Write-Host "  multideck" -ForegroundColor Cyan
        Write-Host "  =========" -ForegroundColor Cyan
        Write-Host "   1) Launch missing + tile new windows   (default)"
        Write-Host "   2) Re-tile ALL open windows"
        if ($groups.Count) { Write-Host "   3) Launch a group   ($($groups -join ', '))" }
        Write-Host "   4) Dry run (preview, change nothing)"
        Write-Host "   5) Re-generate config from a folder scan"
        Write-Host "   Q) Quit"
        $c = Read-Host "  Choose [1]"
        if (-not $c) { $c = '1' }
        switch ($c.Trim().ToLower()) {
            '1' { return @{ Action = 'run'; RetileAll = $false; DryRun = $false; Group = $null } }
            '2' { return @{ Action = 'run'; RetileAll = $true;  DryRun = $false; Group = $null } }
            '3' {
                if (-not $groups.Count) { Write-Host "  No groups defined in config." -ForegroundColor Yellow; continue }
                for ($i = 0; $i -lt $groups.Count; $i++) { Write-Host ("   {0}) {1}" -f ($i + 1), $groups[$i]) }
                $g = Read-Host "  Group number"; $idx = 0
                if ([int]::TryParse($g, [ref]$idx) -and $idx -ge 1 -and $idx -le $groups.Count) {
                    return @{ Action = 'run'; RetileAll = $false; DryRun = $false; Group = $groups[$idx - 1] }
                }
                Write-Host "  Invalid choice." -ForegroundColor Yellow
            }
            '4' { return @{ Action = 'run'; RetileAll = $false; DryRun = $true; Group = $null } }
            '5' { return @{ Action = 'init' } }
            'q' { return @{ Action = 'quit' } }
            default { Write-Host "  Unrecognized choice." -ForegroundColor Yellow }
        }
    }
}

# ---------------------------------------------------------------- config path
# This script now lives in scripts/; the config + .bat launchers sit one level up at
# the repo root. Prefer a config beside the script (override), else use the repo root.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
if (-not $repoRoot) { $repoRoot = $scriptDir }
if (-not $Config) {
    $beside = Join-Path $scriptDir "multideck.config.json"
    $Config = if (Test-Path -LiteralPath $beside) { $beside } else { Join-Path $repoRoot "multideck.config.json" }
}

# ---------------------------------------------------------------- -Init and go
if ($Init) {
    [void](Invoke-MdInit -Root $BaseDir -OutPath $Config -DryRun:$DryRun -Force:$Force)
    return
}

# ---------------------------------------------------------------- load config
if (-not (Test-Path $Config)) {
    if ($script:Interactive) {
        Write-Host "No config found at: $Config" -ForegroundColor Yellow
        $r = (Read-Host "Enter a base folder to scan and generate one now (blank to cancel)").Trim('"', ' ')
        if (-not $r -or -not (Invoke-MdInit -Root $r -OutPath $Config)) { return }
        Write-Host ""
    } else {
        Write-Host "No config found at: $Config" -ForegroundColor Red
        Write-Host "Copy multideck.config.example.json to multideck.config.json," -ForegroundColor Yellow
        Write-Host "or run:  multideck -Init -BaseDir <folder>" -ForegroundColor Yellow
        exit 1
    }
}

try {
    $cfg = Read-MdConfig $Config
} catch {
    Write-Host "Config is not valid JSON ($Config):" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Yellow
    exit 1
}

# ---------------------------------------------------------------- menu (no flags)
$hasDirective = $RetileAll -or $DryRun -or $Go -or [bool]$Group
if (-not $hasDirective -and $script:Interactive) {
    $m = Show-MdMenu -Cfg $cfg
    switch ($m.Action) {
        'quit' { Write-Host "Bye." -ForegroundColor Cyan; return }
        'init' {
            [void](Invoke-MdInit -Root $BaseDir -OutPath $Config)
            Write-Host "Re-run multideck to use the new config." -ForegroundColor Cyan
            return
        }
        'run'  { $RetileAll = $m.RetileAll; $DryRun = $m.DryRun; if ($m.Group) { $Group = $m.Group } }
    }
}

# ---------------------------------------------------------------- settings + defaults
$baseDir     = if ($cfg.baseDir) { Resolve-MdPath "$($cfg.baseDir)" } else { $repoRoot }
$defaultTool = if ($cfg.settings.defaultTool) { "$($cfg.settings.defaultTool)" } else { "claude" }
$settle      = if ($null -ne $cfg.settings.settleSeconds) { [int]$cfg.settings.settleSeconds } else { 3 }
$launchDelay = if ($null -ne $cfg.settings.launchDelayMs) { [int]$cfg.settings.launchDelayMs } else { 400 }
$cols        = if ($null -ne $cfg.layout.columns) { [int]$cfg.layout.columns } else { 2 }
$rows        = if ($null -ne $cfg.layout.rows)    { [int]$cfg.layout.rows }    else { 1 }
if ($cols -lt 1) { $cols = 1 }
if ($rows -lt 1) { $rows = 1 }

$tools = @{ claude = "claude --continue"; codex = "codex --yolo" }
if ($cfg.settings.tools) {
    foreach ($prop in $cfg.settings.tools.PSObject.Properties) { $tools[$prop.Name] = "$($prop.Value)" }
}

# Login-shell wrapper for remote agent commands (default 'bash -lc'); "" disables wrapping.
$sshShell = "bash -lc"
if ($cfg.settings.ssh -and $null -ne $cfg.settings.ssh.shell) { $sshShell = "$($cfg.settings.ssh.shell)" }

if (-not $cfg.projects) { Write-Host "No 'projects' defined in $Config" -ForegroundColor Yellow; exit 1 }

# ---------------------------------------------------------------- group filter
$projects = @($cfg.projects)
if ($Group) {
    $avail = @($cfg.projects | ForEach-Object { $_.group } | Where-Object { $_ } | Sort-Object -Unique)
    $projects = @($cfg.projects | Where-Object { "$($_.group)".ToLower() -eq $Group.ToLower() })
    if ($projects.Count -eq 0) {
        Write-Host "No projects in group '$Group'. Available groups: $($avail -join ', ')" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Group '$Group': $($projects.Count) project(s)" -ForegroundColor Cyan
}

# Warn once if remote projects are configured but the OpenSSH client is missing.
if (@($projects | Where-Object { $_.host }).Count -gt 0 -and -not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: remote projects are configured but 'ssh' is not on PATH. Enable the Windows OpenSSH client (Settings > Optional features)." -ForegroundColor Yellow
}

# ------------------------------------------------- build the per-monitor grid
$screens = [System.Windows.Forms.Screen]::AllScreens | Sort-Object { $_.Bounds.X }
$positions = @()
foreach ($s in $screens) {
    $wa = $s.WorkingArea
    $cellW = [int]($wa.Width / $cols)
    $cellH = [int]($wa.Height / $rows)
    for ($r = 0; $r -lt $rows; $r++) {
        for ($c = 0; $c -lt $cols; $c++) {
            $positions += @{
                x = $wa.X + ($c * $cellW); y = $wa.Y + ($r * $cellH)
                w = $cellW; h = $cellH; label = "r$($r + 1)c$($c + 1)"
            }
        }
    }
}
$perScreen = $cols * $rows
Write-Host "Detected $($screens.Count) screen(s) -> $($positions.Count) tile slot(s) ($cols x $rows per screen)" -ForegroundColor Cyan
if ($DryRun) { Write-Host "DRY RUN - nothing will be launched or moved.`n" -ForegroundColor Magenta }

# ------------------------------------------- discover + (optionally) launch
$targets  = @()
$newCount = 0

foreach ($p in $projects) {
    if ($null -ne $p.enabled -and -not $p.enabled) { continue }
    if (-not $p.path) { Write-Host "SKIP: project entry with no 'path'" -ForegroundColor Yellow; continue }

    # ---------------------------------------------------------- remote (SSH) projects
    if ($p.host) {
        $tool      = if ($p.tool) { "$($p.tool)" } else { $defaultTool }
        $remoteDir = Get-MdRemoteDir $p

        if ($tool -eq "code") {
            # VS Code Remote-SSH. The window title is the opened folder's basename, so
            # match on that ($key) regardless of any display 'title' the user set.
            $key     = Get-MdLeafName $remoteDir
            $name    = if ($p.title) { "$($p.title)" } else { $key }
            $running = [WinPos]::FindByTitleContains($key) -ne [IntPtr]::Zero
            if (-not $running -and -not $DryRun) {
                Start-Process cmd -ArgumentList (Build-MdCodeArgs -Dir $remoteDir -SshHost "$($p.host)") -WindowStyle Hidden
                Start-Sleep -Milliseconds $launchDelay
            }
            if (-not $running) { $newCount++ }
            $targets += @{ name = $name; key = $key; match = "contains"; remoteCode = $true; new = (-not $running) }
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
        $targets += @{ name = $name; key = $name; match = "exact"; new = (-not $running) }
        Write-Host ("{0} {1} [{2} @ {3}:{4}]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name, $tool, "$($p.host)", $remoteDir) `
            -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
        continue
    }

    # ---------------------------------------------------------- local projects
    $raw = Resolve-MdPath "$($p.path)"
    $dir = if ([System.IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $baseDir $raw }
    if (-not (Test-Path $dir)) { Write-Host "SKIP: $($p.path) not found ($dir)" -ForegroundColor Yellow; continue }

    $name = if ($p.title) { "$($p.title)" } else { Split-Path $dir -Leaf }
    $tool = if ($p.tool) { "$($p.tool)" } else { $defaultTool }

    if ($tool -eq "code") {
        # VS Code titles its window by the opened folder's basename - match on that,
        # not a user 'title' (which it never shows), or tiling silently misses it.
        $key     = Get-MdLeafName $dir
        $running = [WinPos]::FindByTitleContains($key) -ne [IntPtr]::Zero
        if (-not $running -and -not $DryRun) {
            Start-Process cmd -ArgumentList "/c", "code", "`"$dir`"" -WindowStyle Hidden
            Start-Sleep -Milliseconds $launchDelay
        }
        if (-not $running) { $newCount++ }
        $targets += @{ name = $name; key = $key; match = "contains"; new = (-not $running) }
        Write-Host ("{0} {1} [code]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name) `
            -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
        continue
    }

    $cmd = $tools[$tool]
    if (-not $cmd) { Write-Host "SKIP: $name - unknown tool '$tool' (add it under settings.tools)" -ForegroundColor Yellow; continue }

    $running = [WinPos]::FindByTitle($name) -ne [IntPtr]::Zero
    if (-not $running -and -not $DryRun) {
        $wtArgs = "-w new -d `"$dir`" --title `"$name`""
        if ($p.color) { $wtArgs += " --tabColor `"$($p.color)`"" }
        $wtArgs += " --suppressApplicationTitle -- cmd /k $cmd"
        Start-Process wt -ArgumentList $wtArgs
        Start-Sleep -Milliseconds $launchDelay
    }
    if (-not $running) { $newCount++ }
    $targets += @{ name = $name; key = $name; match = "exact"; new = (-not $running) }
    Write-Host ("{0} {1} [{2}]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name, $tool) `
        -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
}

# ------------------------------------------------------------ tile the windows
$toPlace = if ($RetileAll) { $targets } else { @($targets | Where-Object { $_.new }) }

if ($toPlace.Count -eq 0) {
    Write-Host "`nNothing to position." -ForegroundColor Cyan
} else {
    $modeLabel = if ($RetileAll) { " [retile all]" } elseif ($DryRun) { " [dry run]" } else { "" }
    Write-Host "`nTiling $($toPlace.Count) window(s)$modeLabel..." -ForegroundColor Cyan
    if (-not $DryRun -and $newCount -gt 0) { Start-Sleep -Seconds $settle }

    $slot = 0
    foreach ($entry in $toPlace) {
        $pos = $positions[$slot % $positions.Count]
        $screenNum = [Math]::Floor(($slot % $positions.Count) / $perScreen) + 1

        if ($DryRun) {
            Write-Host ("  {0,-30} -> screen {1} {2}   {3}x{4} @ ({5},{6})" -f `
                $entry.name, $screenNum, $pos.label, $pos.w, $pos.h, $pos.x, $pos.y) -ForegroundColor Gray
            $slot++; continue
        }

        # A freshly-launched window may not exist yet - VS Code Remote-SSH in particular
        # connects (and on first contact installs its remote server) asynchronously, often
        # past $settle. Poll a few extra seconds for new windows so they still get tiled.
        $find  = { if ($entry.match -eq "contains") { [WinPos]::FindByTitleContains($entry.key) } else { [WinPos]::FindByTitle($entry.key) } }
        $hwnd  = & $find
        if ($hwnd -eq [IntPtr]::Zero -and $entry.new) {
            $deadline = if ($entry.remoteCode) { 20 } else { 6 }
            for ($waited = 0; $waited -lt $deadline -and $hwnd -eq [IntPtr]::Zero; $waited++) {
                Start-Sleep -Seconds 1
                $hwnd = & $find
            }
        }

        if ($hwnd -ne [IntPtr]::Zero) {
            # Move twice on purpose. A window is born on whatever monitor it opens on
            # (usually the primary), so the first MoveWindow often drags it onto a monitor
            # with a DIFFERENT scale. That crossing fires WM_DPICHANGED mid-call, and a
            # Per-Monitor-DPI window (Windows Terminal, VS Code) rescales itself to Windows'
            # suggested rect by the source/target DPI ratio - so the size we asked for is
            # lost (a 960x996 cell on a 175% monitor lands as 837x697 when the window came
            # from a 250% monitor). The second call runs once the window already lives on
            # the target monitor at its final DPI, so the requested size sticks. Same-scale
            # moves never cross a boundary, so the second call is a harmless no-op.
            [WinPos]::MoveWindow($hwnd, $pos.x, $pos.y, $pos.w, $pos.h, $true) | Out-Null
            [WinPos]::MoveWindow($hwnd, $pos.x, $pos.y, $pos.w, $pos.h, $true) | Out-Null
            Write-Host "  $($entry.name) -> screen $screenNum $($pos.label)" -ForegroundColor Gray
        } else {
            Write-Host "  Not found: $($entry.name)" -ForegroundColor Yellow
        }
        $slot++
    }
}

Write-Host "`nDone!" -ForegroundColor Green
