param(
    [Parameter(Mandatory=$true)][ValidateSet('backup','restore')][string]$Action,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [string]$RestorePath = '',
    [ValidateSet('','core','full','production')][string]$Profile = ''
)
$ErrorActionPreference = 'Stop'
$python = if (Test-Path "$PSScriptRoot/../.venv/Scripts/python.exe") {
    "$PSScriptRoot/../.venv/Scripts/python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} else {
    throw 'Python 3 es obligatorio.'
}
$arguments = @("$PSScriptRoot/backup-restore-integral.py", $Action, $ClientId)
if ($Action -eq 'restore') {
    if (-not $RestorePath) { throw 'RestorePath es obligatorio para restore.' }
    $arguments += $RestorePath
}
if ($Profile) { $arguments += @('--profile', $Profile) }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Backup/restore falló con código $LASTEXITCODE." }
