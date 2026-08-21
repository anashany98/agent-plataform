param([Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId)
$ErrorActionPreference = 'Stop'
if (-not $env:BACKUP_ENCRYPTION_PASSPHRASE) { throw 'Define BACKUP_ENCRYPTION_PASSPHRASE.' }
$statePath = ".env.$ClientId.update-state.json"
if (-not (Test-Path -LiteralPath $statePath)) { throw "No existe estado para $ClientId" }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$Profile = if ($state.profile) { $state.profile } else { 'production' }
if ($Profile -notin @('core','full','production')) { throw "Perfil inválido: $Profile" }
if (-not (Test-Path -LiteralPath $state.backup)) { throw "No existe $($state.backup)" }
if ($state.previous_bridge_image -notmatch '^sha256:[0-9a-f]{64}$' -or $state.previous_portal_image -notmatch '^sha256:[0-9a-f]{64}$') {
    throw 'El estado no contiene image IDs exactos; rollback automático no seguro.'
}
$recoveryEngine = "scripts/.env.$ClientId.recovery.py"
if ($state.recovery_engine -ne $recoveryEngine -or -not (Test-Path -LiteralPath $recoveryEngine -PathType Leaf)) {
    throw 'No existe el motor de recovery exacto que creó el backup.'
}
$python = if (Test-Path "$PSScriptRoot/../.venv/Scripts/python.exe") { "$PSScriptRoot/../.venv/Scripts/python.exe" } else { 'python' }
$EnvFile = ".env.$ClientId"
$Project = "agent-$ClientId"
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "No existe $EnvFile" }
if (& git status --porcelain --untracked-files=no) { throw 'Hay cambios tracked sin confirmar.' }
$compose = @('compose','--env-file',$EnvFile,'-p',$Project,'-f','docker-compose.yml')
if ($Profile -eq 'production') { $compose += @('-f','infrastructure/compose/docker-compose.prod.example.yml') }
$compose += @('--profile',$Profile)
$databaseServices = @('bridge-db','bridge-redis')
if ($Profile -eq 'full') { $databaseServices += @('chatwoot-db','chatwoot-redis','activepieces-db','activepieces-redis') }

& git checkout --detach $state.previous_commit
if ($LASTEXITCODE -ne 0) { throw 'Falló checkout anterior.' }
$targetBridgeImage = $env:BRIDGE_API_IMAGE
$targetPortalImage = $env:PORTAL_IMAGE
try {
    $env:BRIDGE_API_IMAGE = $state.previous_bridge_image
    $env:PORTAL_IMAGE = $state.previous_portal_image
    & docker image inspect $state.previous_bridge_image $state.previous_portal_image | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Faltan las imágenes exactas del rollback.' }
    & docker @compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose anterior inválido.' }
    & docker @compose up -d --no-build --pull never @databaseServices
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron iniciar los servicios de datos.' }
    & $python $recoveryEngine restore $ClientId $state.backup --profile $Profile
    & "$PSScriptRoot/check-health.ps1" -ClientId $ClientId -Profile $Profile
} finally {
    $env:BRIDGE_API_IMAGE = $targetBridgeImage
    $env:PORTAL_IMAGE = $targetPortalImage
}
$rolledBack = "$statePath.rolled-back-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
Move-Item -LiteralPath $statePath -Destination $rolledBack
Remove-Item -LiteralPath $recoveryEngine -Force
Write-Host "Rollback completado a $($state.previous_commit) usando restore verificado." -ForegroundColor Green
