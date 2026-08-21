param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [ValidateSet('core','full','production')][string]$Profile = $(if ($env:DEPLOY_PROFILE) { $env:DEPLOY_PROFILE } else { 'production' })
)
$ErrorActionPreference = 'Stop'
$EnvFile = ".env.$ClientId"
$Project = "agent-$ClientId"
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "No existe $EnvFile" }
$compose = @('compose','--env-file',$EnvFile,'-p',$Project,'-f','docker-compose.yml')
if ($Profile -eq 'production') { $compose += @('-f','infrastructure/compose/docker-compose.prod.example.yml') }
$compose += @('--profile',$Profile)
$services = @(& docker @compose config --services) | Where-Object { $_ }
if ($LASTEXITCODE -ne 0 -or $services.Count -eq 0) { throw "El perfil $Profile no es válido o está vacío." }
$failed = $false
foreach ($service in $services) {
    $cid = (& docker @compose ps -q $service).Trim()
    if (-not $cid) { Write-Host ("{0,-26} AUSENTE" -f $service); $failed = $true; continue }
    $state = (& docker inspect -f '{{.State.Status}}' $cid).Trim()
    $health = (& docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $cid).Trim()
    Write-Host ("{0,-26} estado={1,-10} salud={2}" -f $service,$state,$health)
    if ($state -ne 'running' -or $health -ne 'healthy') { $failed = $true }
    $published = (& docker port $cid 2>$null)
    if ($published) {
        if ($Profile -eq 'production' -and $service -ne 'tls-proxy') {
            Write-Error "$service publica puertos en production" -ErrorAction Continue; $failed = $true
        } elseif ($Profile -eq 'core' -and $service -ne 'reverse-proxy') {
            Write-Error "$service publica puertos en core" -ErrorAction Continue; $failed = $true
        }
    }
}
if ($failed) { throw 'Uno o más servicios no están listos.' }
$bridgeId = (& docker @compose ps -q bridge-api).Trim()
& docker exec $bridgeId alembic -c /app/alembic.ini current --check-heads | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'La base de datos no está en la cabeza de migraciones.' }
$proxyId = (& docker @compose ps -q reverse-proxy).Trim()
& docker exec $proxyId wget -q -O - http://127.0.0.1:8080/readyz | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Readiness proxy -> API -> PostgreSQL falló.' }
Write-Host "health=PASS profile=$Profile services=$($services.Count) migrations=head readiness=pass" -ForegroundColor Green
