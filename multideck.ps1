<#
.SYNOPSIS
    multideck - open every project in its own terminal (Claude Code / Codex / VS Code /
    any CLI agent) and auto-tile them into a grid across ALL your monitors.

.DESCRIPTION
    Reads multideck.config.json (next to this script, or pass -Config <path>). For each
    enabled project it launches the configured tool in that directory - inside a Windows
    Terminal window, or VS Code in its own window - then snaps every window into a
    per-monitor grid. The launcher is made Per-Monitor-DPI-Aware first, so positioning
    uses TRUE physical pixels and stays correct even when monitors run different scales
    (e.g. a 175% laptop screen next to 250% 4K monitors).

.PARAMETER RetileAll
    Re-tile EVERY matching window, including ones that were already open - not just the
    windows launched on this run. Great after plugging/unplugging a monitor.

.PARAMETER DryRun
    Print what would be launched and where each window would be tiled, then exit without
    launching or moving anything. Use it to validate a new config.

.PARAMETER Config
    Path to a config file. Default: multideck.config.json beside this script.

.EXAMPLE
    .\multideck.bat
    Launch any not-yet-open projects and tile the new windows.

.EXAMPLE
    .\multideck.bat -RetileAll
    Re-snap every project window into the grid (also via multideck-retile.bat).

.EXAMPLE
    .\multideck.bat -DryRun
    Preview the plan for your config without touching any windows.

.LINK
    https://github.com/DevinoSolutions/multideck-ai-agent
#>
param(
    [switch]$RetileAll,
    [switch]$DryRun,
    [string]$Config
)

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

function Resolve-MdPath([string]$path) {
    if (-not $path) { return $path }
    $path = [Environment]::ExpandEnvironmentVariables($path)
    if ($path -like "~*") { $path = Join-Path $HOME ($path.Substring(1).TrimStart('\', '/')) }
    return $path
}

# ---------------------------------------------------------------- load config
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Config) { $Config = Join-Path $scriptDir "multideck.config.json" }

if (-not (Test-Path $Config)) {
    Write-Host "No config found at: $Config" -ForegroundColor Red
    Write-Host "First run? Copy the example and edit it:" -ForegroundColor Yellow
    Write-Host "    copy multideck.config.example.json multideck.config.json" -ForegroundColor Gray
    Write-Host "Then preview with:  multideck.bat -DryRun" -ForegroundColor Gray
    exit 1
}

try {
    $cfg = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
} catch {
    Write-Host "Config is not valid JSON ($Config):" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Yellow
    exit 1
}

# settings + defaults (null-checked so 0 is respected)
$baseDir     = if ($cfg.baseDir) { Resolve-MdPath "$($cfg.baseDir)" } else { $scriptDir }
$defaultTool = if ($cfg.settings.defaultTool) { "$($cfg.settings.defaultTool)" } else { "claude" }
$settle      = if ($null -ne $cfg.settings.settleSeconds) { [int]$cfg.settings.settleSeconds } else { 3 }
$launchDelay = if ($null -ne $cfg.settings.launchDelayMs) { [int]$cfg.settings.launchDelayMs } else { 400 }
$cols        = if ($null -ne $cfg.layout.columns) { [int]$cfg.layout.columns } else { 2 }
$rows        = if ($null -ne $cfg.layout.rows)    { [int]$cfg.layout.rows }    else { 1 }
if ($cols -lt 1) { $cols = 1 }
if ($rows -lt 1) { $rows = 1 }

# tool command templates (run inside Windows Terminal). 'code' is special-cased below.
$tools = @{ claude = "claude --continue"; codex = "codex --yolo" }
if ($cfg.settings.tools) {
    foreach ($prop in $cfg.settings.tools.PSObject.Properties) { $tools[$prop.Name] = "$($prop.Value)" }
}

if (-not $cfg.projects) {
    Write-Host "No 'projects' defined in $Config" -ForegroundColor Yellow
    exit 1
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
$targets  = @()    # every enabled project that has (or will have) a window, in list order
$newCount = 0

foreach ($p in $cfg.projects) {
    if ($null -ne $p.enabled -and -not $p.enabled) { continue }
    if (-not $p.path) { Write-Host "SKIP: project entry with no 'path'" -ForegroundColor Yellow; continue }

    $raw = Resolve-MdPath "$($p.path)"
    $dir = if ([System.IO.Path]::IsPathRooted($raw)) { $raw } else { Join-Path $baseDir $raw }
    if (-not (Test-Path $dir)) {
        Write-Host "SKIP: $($p.path) not found ($dir)" -ForegroundColor Yellow
        continue
    }

    $name = if ($p.title) { "$($p.title)" } else { Split-Path $dir -Leaf }
    $tool = if ($p.tool) { "$($p.tool)" } else { $defaultTool }

    if ($tool -eq "code") {
        $running = [WinPos]::FindByTitleContains($name) -ne [IntPtr]::Zero
        if (-not $running -and -not $DryRun) {
            Start-Process cmd -ArgumentList "/c", "code", "`"$dir`"" -WindowStyle Hidden
            Start-Sleep -Milliseconds $launchDelay
        }
        if (-not $running) { $newCount++ }
        $targets += @{ name = $name; match = "contains"; new = (-not $running) }
        Write-Host ("{0} {1} [code]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name) `
            -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
        continue
    }

    $cmd = $tools[$tool]
    if (-not $cmd) {
        Write-Host "SKIP: $name - unknown tool '$tool' (add it under settings.tools)" -ForegroundColor Yellow
        continue
    }

    $running = [WinPos]::FindByTitle($name) -ne [IntPtr]::Zero
    if (-not $running -and -not $DryRun) {
        $wtArgs = "-w new -d `"$dir`" --title `"$name`""
        if ($p.color) { $wtArgs += " --tabColor `"$($p.color)`"" }
        $wtArgs += " --suppressApplicationTitle -- cmd /k $cmd"
        Start-Process wt -ArgumentList $wtArgs
        Start-Sleep -Milliseconds $launchDelay
    }
    if (-not $running) { $newCount++ }
    $targets += @{ name = $name; match = "exact"; new = (-not $running) }
    Write-Host ("{0} {1} [{2}]" -f $(if ($running) { "OPEN:" } else { "NEW: " }), $name, $tool) `
        -ForegroundColor $(if ($running) { "DarkGray" } else { "Green" })
}

# ------------------------------------------------------------ tile the windows
# Default: position only what we just launched. -RetileAll: position everything.
$toPlace = if ($RetileAll) { $targets } else { @($targets | Where-Object { $_.new }) }

if ($toPlace.Count -eq 0) {
    Write-Host "`nNothing to position." -ForegroundColor Cyan
} else {
    $modeLabel = if ($RetileAll) { " [retile all]" } elseif ($DryRun) { " [dry run]" } else { "" }
    Write-Host "`nTiling $($toPlace.Count) window(s)$modeLabel..." -ForegroundColor Cyan
    if (-not $DryRun -and $newCount -gt 0) { Start-Sleep -Seconds $settle }  # let new windows appear

    $slot = 0
    foreach ($entry in $toPlace) {
        $pos = $positions[$slot % $positions.Count]
        $screenNum = [Math]::Floor(($slot % $positions.Count) / $perScreen) + 1

        if ($DryRun) {
            Write-Host ("  {0,-30} -> screen {1} {2}   {3}x{4} @ ({5},{6})" -f `
                $entry.name, $screenNum, $pos.label, $pos.w, $pos.h, $pos.x, $pos.y) -ForegroundColor Gray
            $slot++; continue
        }

        $hwnd = if ($entry.match -eq "contains") { [WinPos]::FindByTitleContains($entry.name) }
                else { [WinPos]::FindByTitle($entry.name) }

        if ($hwnd -ne [IntPtr]::Zero) {
            [WinPos]::MoveWindow($hwnd, $pos.x, $pos.y, $pos.w, $pos.h, $true) | Out-Null
            Write-Host "  $($entry.name) -> screen $screenNum $($pos.label)" -ForegroundColor Gray
        } else {
            Write-Host "  Not found: $($entry.name)" -ForegroundColor Yellow
        }
        $slot++
    }
}

Write-Host "`nDone!" -ForegroundColor Green
