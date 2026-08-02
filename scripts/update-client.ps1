param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
  [Parameter(Mandatory=$true)][string]$TargetRef
)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
if (-not $env:BACKUP_ENCRYPTION_PASSPHRASE) { throw 'Define BACKUP_ENCRYPTION_PASSPHRASE.' }
$EnvFile=".env.$ClientId"; $Project="agent-$ClientId"
if (-not (Test-Path $EnvFile)) { throw "No existe $EnvFile" }
& git diff --quiet; if ($LASTEXITCODE -ne 0) { throw 'Hay cambios sin confirmar.' }
& git diff --cached --quiet; if ($LASTEXITCODE -ne 0) { throw 'Hay cambios preparados sin confirmar.' }
$target=(& git rev-parse "$TargetRef^{commit}" 2>$null).Trim(); if (-not $target) { throw "No existe $TargetRef" }
$previous=(& git rev-parse HEAD).Trim(); if ($previous -eq $target) { Write-Host 'La versión ya está instalada.'; exit 0 }
$backupOutput=@(& "$PSScriptRoot/backup-restore-integral.ps1" -Action backup -ClientId $ClientId)
$backup=($backupOutput | Where-Object { $_ -is [string] -and (Test-Path $_) } | Select-Object -Last 1)
if (-not $backup) { throw 'No se pudo determinar el backup previo.' }
$compose=@('compose','--env-file',$EnvFile,'-p',$Project,'--profile','full')
try {
  & git checkout --detach $target; if ($LASTEXITCODE -ne 0) { throw 'Falló checkout.' }
  & docker @compose config | Out-Null
  & docker @compose build --pull; if ($LASTEXITCODE -ne 0) { throw 'Falló build.' }
  & docker @compose up -d; if ($LASTEXITCODE -ne 0) { throw 'Falló arranque.' }
  & "$PSScriptRoot/check-health.ps1" -ClientId $ClientId
  $dir='infrastructure/update-state'; New-Item -ItemType Directory -Force $dir | Out-Null
  @{client_id=$ClientId;previous_commit=$previous;target_commit=$target;backup=$backup;updated_at_utc=(Get-Date).ToUniversalTime().ToString('o')} |
    ConvertTo-Json | Set-Content -Encoding utf8NoBOM "$dir/$ClientId.json"
  Write-Host "Actualización completada: $previous -> $target" -ForegroundColor Green
} catch {
  Write-Warning 'Actualización fallida. Se intenta rollback automático.'
  & git checkout --detach $previous
  & docker @compose build
  & docker @compose up -d
  & "$PSScriptRoot/backup-restore-integral.ps1" -Action restore -ClientId $ClientId -RestorePath $backup
  throw
}
