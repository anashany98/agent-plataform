param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [Parameter(Mandatory=$true)][string]$TargetRef
)
$ErrorActionPreference = 'Stop'
$EnvFile = ".env.$ClientId"
$Project = "agent-$ClientId"
if (-not $env:BACKUP_ENCRYPTION_PASSPHRASE) { throw 'Define BACKUP_ENCRYPTION_PASSPHRASE.' }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "No existe $EnvFile" }
$envValues = @{}
foreach ($line in Get-Content -LiteralPath $EnvFile) {
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
        $key,$value = $line.Split('=',2); $envValues[$key] = $value
    }
}
$Profile = if ($env:DEPLOY_PROFILE) { $env:DEPLOY_PROFILE } elseif ($envValues.DEPLOY_PROFILE) { $envValues.DEPLOY_PROFILE } else { 'production' }
if ($Profile -notin @('core','full','production')) { throw "Perfil inválido: $Profile" }
if (& git status --porcelain --untracked-files=no) { throw 'Hay cambios tracked sin confirmar.' }
$target = (& git rev-parse "$TargetRef^{commit}" 2>$null).Trim()
if (-not $target) { throw "No existe $TargetRef" }
$previous = (& git rev-parse HEAD).Trim()
if ($previous -eq $target) { Write-Host 'La versión ya está instalada.'; exit 0 }

$compose = @('compose','--env-file',$EnvFile,'-p',$Project,'-f','docker-compose.yml')
if ($Profile -eq 'production') { $compose += @('-f','infrastructure/compose/docker-compose.prod.example.yml') }
$compose += @('--profile',$Profile)
$databaseServices = @('bridge-db','bridge-redis')
if ($Profile -eq 'full') { $databaseServices += @('chatwoot-db','chatwoot-redis','activepieces-db','activepieces-redis') }
$python = if (Test-Path "$PSScriptRoot/../.venv/Scripts/python.exe") { "$PSScriptRoot/../.venv/Scripts/python.exe" } else { 'python' }
$recoveryEngine = "scripts/.env.$ClientId.recovery.py"
Copy-Item -LiteralPath "$PSScriptRoot/backup-restore-integral.py" -Destination $recoveryEngine -Force

function Get-ServiceImageId([string]$Service) {
    $container = (& docker @compose ps -q $Service).Trim()
    if (-not $container) { throw "El servicio $Service no está iniciado; no se puede fijar el rollback." }
    $imageId = (& docker inspect --format '{{.Image}}' $container).Trim()
    if ($LASTEXITCODE -ne 0 -or $imageId -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "No se pudo fijar la imagen actual de $Service."
    }
    return $imageId
}

$previousBridgeImage = Get-ServiceImageId 'bridge-api'
$previousPortalImage = Get-ServiceImageId 'portal'

$backupOutput = @(& $python $recoveryEngine backup $ClientId --profile $Profile)
$backup = $backupOutput | Where-Object { $_ -is [string] -and (Test-Path -LiteralPath $_) } | Select-Object -Last 1
if (-not $backup) { throw 'No se pudo determinar el backup previo.' }

try {
    & git checkout --detach $target
    if ($LASTEXITCODE -ne 0) { throw 'Falló checkout del target.' }
    & "$PSScriptRoot/preflight-production.ps1" -EnvFile $EnvFile -Profile $Profile -Mode release
    & docker @compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose target inválido.' }
    & docker @compose run --rm --no-deps --no-build --pull never --entrypoint alembic bridge-api -c /app/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Falló la migración target.' }
    & docker @compose up -d --no-build --pull never --wait --wait-timeout 600
    if ($LASTEXITCODE -ne 0) { throw 'Falló el arranque target.' }
    & "$PSScriptRoot/check-health.ps1" -ClientId $ClientId -Profile $Profile
    $statePath = ".env.$ClientId.update-state.json"
    $stateTemp = "$statePath.$([guid]::NewGuid().ToString('N')).tmp"
    $statePayload = @{
        client_id = $ClientId
        profile = $Profile
        previous_commit = $previous
        target_commit = $target
        previous_bridge_image = $previousBridgeImage
        previous_portal_image = $previousPortalImage
        recovery_engine = $recoveryEngine
        backup = $backup
        updated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json
    try {
        [IO.File]::WriteAllText((Join-Path (Get-Location) $stateTemp), $statePayload, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $stateTemp -Destination $statePath -Force
    } finally {
        if (Test-Path -LiteralPath $stateTemp) { Remove-Item -LiteralPath $stateTemp -Force }
    }
    Write-Host "Actualización completada: $previous -> $target" -ForegroundColor Green
} catch {
    $original = $_
    Write-Warning 'Actualización fallida; restaurando commit y backup previos.'
    & git checkout --detach $previous
    try {
        $targetBridgeImage = $env:BRIDGE_API_IMAGE
        $targetPortalImage = $env:PORTAL_IMAGE
        $env:BRIDGE_API_IMAGE = $previousBridgeImage
        $env:PORTAL_IMAGE = $previousPortalImage
        & docker image inspect $previousBridgeImage $previousPortalImage | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Faltan las imágenes exactas del rollback.' }
        & docker @compose config --quiet
        & docker @compose up -d --no-build --pull never @databaseServices
        & $python $recoveryEngine restore $ClientId $backup --profile $Profile
        & "$PSScriptRoot/check-health.ps1" -ClientId $ClientId -Profile $Profile
    } catch {
        Write-Error "Rollback automático también falló: $($_.Exception.Message)" -ErrorAction Continue
    } finally {
        $env:BRIDGE_API_IMAGE = $targetBridgeImage
        $env:PORTAL_IMAGE = $targetPortalImage
    }
    throw $original
}
