<#
.SYNOPSIS
    Install multideck for the current user: add this folder to the user PATH (so you can
    type `multideck` from anywhere) and create Desktop + Start-Menu shortcuts.
    User-scoped only - no admin required, fully reversible with uninstall.ps1.
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Installing multideck from $repo" -ForegroundColor Cyan

# --- 1. user PATH ---------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @($userPath -split ';' | Where-Object { $_ -ne '' })
if ($parts -notcontains $repo) {
    [Environment]::SetEnvironmentVariable('Path', (($parts + $repo) -join ';'), 'User')
    Write-Host "  + Added to user PATH (restart terminals to pick it up)" -ForegroundColor Green
} else {
    Write-Host "  = Already on user PATH" -ForegroundColor DarkGray
}

# --- 2. shortcuts ---------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
function New-MdShortcut($lnk, $targetBat, $desc) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath       = (Join-Path $repo $targetBat)
    $s.WorkingDirectory = $repo
    $s.Description      = $desc
    $s.Save()
    Write-Host "  + $lnk" -ForegroundColor Green
}

$desktop  = [Environment]::GetFolderPath('Desktop')
$startDir  = Join-Path ([Environment]::GetFolderPath('Programs')) 'multideck'
New-Item -ItemType Directory -Force -Path $startDir | Out-Null

New-MdShortcut (Join-Path $desktop  'multideck.lnk')          'multideck.bat'         'Launch + tile your projects (menu)'
New-MdShortcut (Join-Path $desktop  'multideck (retile).lnk') 'multideck-retile.bat'  'Re-tile all open project windows'
New-MdShortcut (Join-Path $startDir 'multideck.lnk')          'multideck.bat'         'Launch + tile your projects (menu)'
New-MdShortcut (Join-Path $startDir 'multideck (retile).lnk') 'multideck-retile.bat'  'Re-tile all open project windows'

Write-Host "`nDone. Open a NEW terminal and run:  multideck" -ForegroundColor Cyan
Write-Host "(First run with no config? It'll offer to scan a folder and build one.)" -ForegroundColor DarkGray
