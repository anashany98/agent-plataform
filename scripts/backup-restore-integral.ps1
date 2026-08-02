param(
    [Parameter(Mandatory=$true)][ValidateSet('backup','restore')][string]$Action,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [string]$RestorePath = ""
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $env:BACKUP_ENCRYPTION_PASSPHRASE) { throw 'Define BACKUP_ENCRYPTION_PASSPHRASE en el entorno.' }
foreach ($cmd in @('docker','openssl','tar')) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd es obligatorio." } }
$EnvFile = ".env.$ClientId"
$Project = "agent-$ClientId"
if (-not (Test-Path $EnvFile)) { throw "No existe $EnvFile" }
$compose = @('compose','--env-file',$EnvFile,'-p',$Project,'--profile','full')

function Get-ServiceContainer([string]$Service) {
    $id = (& docker @compose ps -q $Service).Trim()
    if (-not $id) { throw "El servicio $Service no está iniciado." }
    return $id
}
function Backup-Database([string]$Service, [string]$Output) {
    $cid = Get-ServiceContainer $Service
    & docker exec $cid sh -ec 'rm -f /tmp/agent-platform.dump; pg_dump -Fc --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB" -f /tmp/agent-platform.dump'
    if ($LASTEXITCODE -ne 0) { throw "Falló pg_dump de $Service" }
    & docker cp "${cid}:/tmp/agent-platform.dump" $Output
    & docker exec $cid rm -f /tmp/agent-platform.dump | Out-Null
    if (-not (Test-Path $Output) -or (Get-Item $Output).Length -eq 0) { throw "Dump vacío para $Service" }
}
function Restore-Database([string]$Service, [string]$Input) {
    $cid = Get-ServiceContainer $Service
    & docker cp $Input "${cid}:/tmp/agent-platform.dump"
    & docker exec $cid sh -ec 'pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/agent-platform.dump; rm -f /tmp/agent-platform.dump'
    if ($LASTEXITCODE -ne 0) { throw "Falló la restauración de $Service" }
}
function Backup-Volume([string]$Volume, [string]$Output) {
    $dir = (Resolve-Path (Split-Path $Output -Parent)).Path
    $name = Split-Path $Output -Leaf
    & docker run --rm --read-only -v "${Volume}:/data:ro" -v "${dir}:/backup" alpine:3.20 sh -ec "tar -C /data -cf /backup/$name ."
    if ($LASTEXITCODE -ne 0) { throw "Falló la copia del volumen $Volume" }
}
function Restore-Volume([string]$Volume, [string]$Input) {
    $dir = (Resolve-Path (Split-Path $Input -Parent)).Path
    $name = Split-Path $Input -Leaf
    & docker run --rm -v "${Volume}:/data" -v "${dir}:/backup:ro" alpine:3.20 sh -ec "find /data -mindepth 1 -delete; tar -C /data -xf /backup/$name"
    if ($LASTEXITCODE -ne 0) { throw "Falló la restauración del volumen $Volume" }
}
function Wait-Healthy {
    $deadline = (Get-Date).AddMinutes(10)
    while ((Get-Date) -lt $deadline) {
        $ids = @(& docker @compose ps -q) | Where-Object { $_ }
        $bad = 0
        foreach ($id in $ids) {
            $state = (& docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $id).Trim()
            if ($state -ne 'running healthy' -and $state -ne 'running none') { $bad++ }
        }
        if ($ids.Count -ge 14 -and $bad -eq 0) { return }
        Start-Sleep -Seconds 5
    }
    & docker @compose ps
    throw 'Los servicios no recuperaron un estado saludable dentro de 10 minutos.'
}

if ($Action -eq 'backup') {
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $base = "infrastructure/backups/$ClientId"
    $stage = "$base/.$timestamp.stage"
    $output = "$base/$ClientId-$timestamp.tar.gz.enc"
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        Backup-Database bridge-db "$stage/bridge-db.dump"
        Backup-Database chatwoot-db "$stage/chatwoot-db.dump"
        Backup-Database activepieces-db "$stage/activepieces-db.dump"
        Backup-Volume "${Project}_bridge_uploads" "$stage/bridge-uploads.tar"
        Backup-Volume "${Project}_chatwoot_storage_data" "$stage/chatwoot-storage.tar"
        $commit = (& git rev-parse HEAD 2>$null); if (-not $commit) { $commit = 'unknown' }
        @{client_id=$ClientId; project=$Project; created_at_utc=$timestamp; git_commit=$commit; format_version=3; encrypted=$true} |
            ConvertTo-Json -Compress | Set-Content -Encoding utf8NoBOM "$stage/manifest.json"
        Push-Location $stage
        Get-FileHash bridge-db.dump,chatwoot-db.dump,activepieces-db.dump,bridge-uploads.tar,chatwoot-storage.tar,manifest.json -Algorithm SHA256 |
            ForEach-Object { "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($_.Path))" } | Set-Content -Encoding ASCII SHA256SUMS
        Pop-Location
        & tar -C $stage -czf "$stage/package.tar.gz" bridge-db.dump chatwoot-db.dump activepieces-db.dump bridge-uploads.tar chatwoot-storage.tar manifest.json SHA256SUMS
        & openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE -in "$stage/package.tar.gz" -out $output
        if ($LASTEXITCODE -ne 0) { throw 'Falló el cifrado del backup.' }
        "{0}  {1}" -f (Get-FileHash $output -Algorithm SHA256).Hash.ToLower(), (Split-Path $output -Leaf) | Set-Content -Encoding ASCII "$output.sha256"
        Write-Host $output -ForegroundColor Green
    } finally { Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue }
    exit 0
}

if (-not $RestorePath -or -not (Test-Path $RestorePath)) { throw 'RestorePath no es válido.' }
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("agent-restore-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    & openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE -in $RestorePath -out "$tmp/package.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo descifrar el backup.' }
    & tar -C $tmp -xzf "$tmp/package.tar.gz"
    $manifest = Get-Content "$tmp/manifest.json" -Raw | ConvertFrom-Json
    if ($manifest.client_id -ne $ClientId) { throw "El backup pertenece a $($manifest.client_id)." }
    foreach ($line in Get-Content "$tmp/SHA256SUMS") {
        $parts = $line -split '\s+',2
        $actual = (Get-FileHash (Join-Path $tmp $parts[1]) -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $parts[0]) { throw "Checksum incorrecto: $($parts[1])" }
    }
    & docker @compose stop bridge-api chatwoot-web chatwoot-worker activepieces-app activepieces-worker
    Restore-Database bridge-db "$tmp/bridge-db.dump"
    Restore-Database chatwoot-db "$tmp/chatwoot-db.dump"
    Restore-Database activepieces-db "$tmp/activepieces-db.dump"
    Restore-Volume "${Project}_bridge_uploads" "$tmp/bridge-uploads.tar"
    Restore-Volume "${Project}_chatwoot_storage_data" "$tmp/chatwoot-storage.tar"
    & docker @compose up -d
    Wait-Healthy
    & docker @compose ps
} finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
