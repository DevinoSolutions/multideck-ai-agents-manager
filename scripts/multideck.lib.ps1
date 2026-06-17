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
