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
