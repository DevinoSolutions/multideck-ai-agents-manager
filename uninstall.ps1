<#
.SYNOPSIS
    Remove what install.ps1 added: take this folder back off the user PATH and delete the
    Desktop + Start-Menu shortcuts. Leaves your scripts and config untouched.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Uninstalling multideck shortcuts/PATH for $repo" -ForegroundColor Cyan

# --- 1. user PATH ---------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @($userPath -split ';' | Where-Object { $_ -ne '' -and $_ -ne $repo })
if (($userPath -split ';') -contains $repo) {
    [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')
    Write-Host "  - Removed from user PATH" -ForegroundColor Green
} else {
    Write-Host "  = Not on user PATH" -ForegroundColor DarkGray
}

# --- 2. shortcuts ---------------------------------------------------------
$desktop  = [Environment]::GetFolderPath('Desktop')
$startDir = Join-Path ([Environment]::GetFolderPath('Programs')) 'multideck'
$targets = @(
    (Join-Path $desktop  'multideck.lnk'),
    (Join-Path $desktop  'multideck (retile).lnk'),
    (Join-Path $startDir 'multideck.lnk'),
    (Join-Path $startDir 'multideck (retile).lnk')
)
foreach ($t in $targets) {
    if (Test-Path $t) { Remove-Item -LiteralPath $t -Force; Write-Host "  - $t" -ForegroundColor Green }
}
if ((Test-Path $startDir) -and -not (Get-ChildItem -LiteralPath $startDir -Force)) { Remove-Item -LiteralPath $startDir -Force }

Write-Host "`nDone. Your multideck files and config were left in place." -ForegroundColor Cyan
