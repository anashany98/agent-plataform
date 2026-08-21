param(
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [ValidateSet('core','full','production')][string]$Profile = 'production',
    [ValidateSet('bootstrap','release')][string]$Mode = 'release',
    [switch]$AllowDirty
)
$ErrorActionPreference = 'Stop'
$python = if (Test-Path "$PSScriptRoot/../.venv/Scripts/python.exe") {
    "$PSScriptRoot/../.venv/Scripts/python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    'python'
} else {
    throw 'Python 3 es obligatorio para el preflight.'
}
$arguments = @("$PSScriptRoot/production-preflight.py", '--env-file', $EnvFile, '--profile', $Profile, '--mode', $Mode)
if ($AllowDirty) { $arguments += '--allow-dirty' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Preflight production falló con código $LASTEXITCODE." }
