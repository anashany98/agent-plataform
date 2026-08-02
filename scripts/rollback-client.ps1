param([Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
if (-not $env:BACKUP_ENCRYPTION_PASSPHRASE) { throw 'Define BACKUP_ENCRYPTION_PASSPHRASE.' }
$statePath="infrastructure/update-state/$ClientId.json"
if (-not (Test-Path $statePath)) { throw "No existe estado de actualización para $ClientId" }
$state=Get-Content $statePath -Raw | ConvertFrom-Json
if (-not (Test-Path $state.backup)) { throw "No existe $($state.backup)" }
$EnvFile=".env.$ClientId"; $Project="agent-$ClientId"; $compose=@('compose','--env-file',$EnvFile,'-p',$Project,'--profile','full')
& git diff --quiet; if ($LASTEXITCODE -ne 0) { throw 'Hay cambios sin confirmar.' }
& git checkout --detach $state.previous_commit; if ($LASTEXITCODE -ne 0) { throw 'Falló checkout anterior.' }
& docker @compose build; if ($LASTEXITCODE -ne 0) { throw 'Falló build de rollback.' }
& docker @compose up -d; if ($LASTEXITCODE -ne 0) { throw 'Falló arranque de rollback.' }
& "$PSScriptRoot/backup-restore-integral.ps1" -Action restore -ClientId $ClientId -RestorePath $state.backup
& "$PSScriptRoot/check-health.ps1" -ClientId $ClientId
Move-Item $statePath "$statePath.rolled-back-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
Write-Host "Rollback completado a $($state.previous_commit)." -ForegroundColor Green
