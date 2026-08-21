param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [string]$Domain = '',
    [ValidateRange(1024,65535)][int]$ProxyPort = 9000,
    [ValidateSet('core','full','production')][string]$Profile = 'core',
    [string]$TlsCertificate = '',
    [string]$TlsPrivateKey = '',
    [switch]$AllowSelfSignedTlsBootstrap,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$Project = "agent-$ClientId"
$EnvFile = ".env.$ClientId"
if (-not $Domain) { $Domain = "$ClientId.local" }
if (Test-Path -LiteralPath $EnvFile) { throw "$EnvFile ya existe. No se sobrescribe para evitar perder secretos." }
foreach ($command in @('docker','git')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command no está instalado." }
}
& docker compose version | Out-Null
& docker info | Out-Null

if ($Profile -eq 'production') {
    if ($Domain -notmatch '^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$' -or $Domain -notmatch '\.' -or $Domain -match '\.(local|localhost|invalid)$') {
        throw 'production exige un dominio DNS público válido.'
    }
    if (-not (Test-Path -LiteralPath $TlsCertificate -PathType Leaf)) { throw 'TlsCertificate no existe.' }
    if (-not (Test-Path -LiteralPath $TlsPrivateKey -PathType Leaf)) { throw 'TlsPrivateKey no existe.' }
    $TlsCertificate = (Resolve-Path -LiteralPath $TlsCertificate).Path.Replace('\','/')
    $TlsPrivateKey = (Resolve-Path -LiteralPath $TlsPrivateKey).Path.Replace('\','/')
}

# Preflight atómico: puerto libre antes de escribir secretos o construir.
try {
    $probe = [System.Net.Sockets.TcpClient]::new()
    $probe.Connect('127.0.0.1', $ProxyPort)
    $probe.Dispose()
    throw "El puerto $ProxyPort ya está en uso. Elige otro con -ProxyPort."
} catch [System.Net.Sockets.SocketException] {
    # Conexión rechazada: puerto libre.
}

function New-Hex([int]$Bytes = 32) {
    $buffer = [byte[]]::new($Bytes)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer)).Replace('-','').ToLowerInvariant()
}
function New-Secret([int]$Bytes = 36) {
    $buffer = [byte[]]::new($Bytes)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer)
}

$AdminPassword = "$(New-Secret 24)Aa1!"
$environment = if ($Profile -eq 'production') { 'production' } else { 'staging' }
$allowedOrigins = if ($Profile -eq 'production') { "https://$Domain" } else { "http://localhost:$ProxyPort" }
$allowedHosts = if ($Profile -eq 'production') { "$Domain,api.$Domain,bridge-api" } else { "localhost,127.0.0.1,$Domain,api.$Domain,bridge-api" }
$publicScheme = if ($Profile -eq 'production') { 'https' } else { 'http' }
$publicSuffix = if ($Profile -eq 'production') { '' } else { ":$ProxyPort" }
$sourceCommit = (& git rev-parse HEAD).Trim()
$versionMatch = Select-String -LiteralPath (Join-Path $PSScriptRoot '..\bridge-api\pyproject.toml') -Pattern '^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$' | Select-Object -First 1
if (-not $versionMatch) { throw 'No se pudo obtener la versión SemVer de bridge-api/pyproject.toml.' }
$applicationVersion = $versionMatch.Matches[0].Groups[1].Value
$releaseVersion = "$applicationVersion-$($sourceCommit.Substring(0,12))"

$content = @"
COMPOSE_PROJECT_NAME=$Project
DEPLOY_PROFILE=$Profile
RELEASE_VERSION=$releaseVersion
SOURCE_COMMIT=$sourceCommit
BRIDGE_API_IMAGE=agent-platform-bridge-api:$releaseVersion
PORTAL_IMAGE=agent-platform-portal:$releaseVersion
RELEASE_MANIFEST_FILE=.env.$ClientId.release.json
ENVIRONMENT=$environment
INSTALLATION_ID=$ClientId
PILOT_MODE=false
RUN_MIGRATIONS=true
ALLOW_DEMO_DATA=false
AUTO_SEED_DEMO_DATA=false
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false
DEBUG=false
PROXY_BIND_ADDRESS=127.0.0.1
PROXY_PORT=$ProxyPort
TLS_BIND_ADDRESS=0.0.0.0
HTTP_PORT=80
HTTPS_PORT=443
TLS_CERT_FILE=$TlsCertificate
TLS_PRIVATE_KEY_FILE=$TlsPrivateKey
ALLOW_SELF_SIGNED_TLS_BOOTSTRAP=$($AllowSelfSignedTlsBootstrap.ToString().ToLowerInvariant())
PUBLIC_BASE_URL=${publicScheme}://$Domain$publicSuffix
PORTAL_HOST=$Domain
API_HOST=api.$Domain
ALLOWED_ORIGINS=$allowedOrigins
ALLOWED_HOSTS=$allowedHosts
POSTGRES_DB=bridge_db
POSTGRES_USER=bridge_user
POSTGRES_PASSWORD=$(New-Hex 32)
REDIS_PASSWORD=$(New-Hex 32)
AUTH_SECRET=$(New-Hex 48)
AUTH_TOKEN_TTL_SEC=3600
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=$AdminPassword
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=120
LOGIN_RATE_LIMIT_REQUESTS=8
LOGIN_RATE_LIMIT_WINDOW_SEC=900
TRUSTED_PROXY_COUNT=$(if ($Profile -eq 'production') { 2 } else { 1 })
TRUSTED_PROXY_CIDRS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
REDIS_ENABLED=true
RATE_LIMIT_BACKEND=redis
REDIS_RATE_LIMIT_FAIL_OPEN=false
REDIS_SOCKET_TIMEOUT_SEC=0.5
REDIS_CONNECT_TIMEOUT_SEC=0.5
OUTBOX_WORKER_ENABLED=true
OUTBOX_WORKER_POLL_SEC=1.0
OUTBOX_WORKER_LEASE_SEC=60
OUTBOX_WORKER_DISPATCH_LOCK_SEC=30
OUTBOX_MAX_ATTEMPTS=8
OUTBOX_RETRY_BASE_DELAY_SEC=1.0
OUTBOX_RETRY_MAX_DELAY_SEC=300.0
OUTBOX_BATCH_SIZE=16
SCHEDULED_TASK_WORKER_ENABLED=true
SCHEDULED_TASK_WORKER_POLL_SEC=30.0
EMAIL_PROVIDER=local
CHATWOOT_ENABLED=false
CHATWOOT_WEBHOOK_SECRET=
CHATWOOT_SAFE_FETCH_ALLOW_PRIVATE_NETWORK=false
PRESTASHOP_BASE_URL=
PRESTASHOP_API_KEY=
PRESTASHOP_SHOP_ID=
PRESTASHOP_SHOP_GROUP_ID=
PRESTASHOP_COUNTRY_ID=
PRESTASHOP_CURRENCY_ID=
GHL_BASE_URL=https://services.leadconnectorhq.com
GHL_API_TOKEN=
GHL_LOCATION_ID=
GHL_PIPELINE_ID=
GHL_PIPELINE_STAGE_ID=
INTEGRATION_RETRY_ATTEMPTS=3
INTEGRATION_RETRY_BASE_DELAY_SEC=0.25
INTEGRATION_RETRY_MAX_DELAY_SEC=2.0
IDEMPOTENCY_LEASE_SEC=300
IDEMPOTENCY_MAX_ATTEMPTS=8
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_SEC=30
OLLAMA_BASE_URL=
CHEAP_LLM_PROVIDER=none
CHEAP_LLM_MODEL=
STANDARD_LLM_PROVIDER=none
STANDARD_LLM_MODEL=
ADVANCED_LLM_PROVIDER=none
ADVANCED_LLM_MODEL=
CRITICAL_LLM_PROVIDER=none
CRITICAL_LLM_MODEL=
OPENAI_BASE_URL=
OPENAI_API_KEY=
ANTHROPIC_BASE_URL=
ANTHROPIC_API_KEY=
LLM_PRICING_CATALOG_JSON=
LLM_MAX_DAILY_COST_USD=25
LLM_MAX_INPUT_BYTES=131072
LLM_MAX_OUTPUT_TOKENS=1024
EMBEDDING_PROVIDER=local_tfidf
EMBEDDING_MODEL=local-tfidf
EMBEDDING_DIMENSION=768
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
RAG_MIN_SCORE=0.55
RAG_MAX_FILE_MB=25
OCR_ENABLED=true
COUNTRY=ES
CURRENCY=EUR
DEFAULT_VAT_RATE=0.21
INVOICE_SERIES=INV-2026-
SHIPPING_FLAT_RATE=15.00
FREE_SHIPPING_THRESHOLD=300.00
QUOTE_CONFIRMATION_TTL_SEC=1800
STOCK_RESERVATION_TTL_SEC=900
ENABLE_QUOTES=true
ENABLE_ORDERS=false
ENABLE_INVOICES=false
ENABLE_AUTOMATIC_ORDER_CONFIRMATION=false
ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false
ENABLE_AUTOMATIC_PUBLISHING=false
NGINX_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
REDIS_IMAGE=redis:7.2.14-alpine3.21@sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8
BRIDGE_POSTGRES_IMAGE=pgvector/pgvector:pg15@sha256:a20a57d7aa5217a6af0a391ccf69f4a8512406d6c14be08132f801468cc3cc62
BACKUP_QUIESCE=true
BACKUP_HELPER_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
"@

if ($Profile -eq 'full') {
    $content += @"
CHATWOOT_HOST=chat.$Domain
FLOWWINK_HOST=agents.$Domain
ACTIVEPIECES_HOST=automation.$Domain
CHATWOOT_SECRET_KEY_BASE=$(New-Hex 64)
CHATWOOT_POSTGRES_DB=chatwoot_db
CHATWOOT_POSTGRES_USER=chatwoot
CHATWOOT_POSTGRES_PASSWORD=$(New-Hex 32)
CHATWOOT_REDIS_PASSWORD=$(New-Hex 32)
CHATWOOT_API_TOKEN=
CHATWOOT_ACCOUNT_ID=
CHATWOOT_HANDOFF_TEAM_ID=0
CHATWOOT_HANDOFF_ASSIGNEE_ID=0
CHATWOOT_WEBHOOK_SECRET=$(New-Hex 48)
BRIDGE_WEBHOOK_URL=${publicScheme}://api.$Domain$publicSuffix/webhooks/chatwoot
CHATWOOT_PUBLIC_URL=${publicScheme}://chat.$Domain$publicSuffix
ACTIVEPIECES_POSTGRES_DB=activepieces
ACTIVEPIECES_POSTGRES_USER=activepieces
ACTIVEPIECES_POSTGRES_PASSWORD=$(New-Hex 32)
ACTIVEPIECES_REDIS_PASSWORD=$(New-Hex 32)
ACTIVEPIECES_ENCRYPTION_KEY=$(New-Hex 16)
ACTIVEPIECES_JWT_SECRET=$(New-Hex 48)
ACTIVEPIECES_API_KEY=
ACTIVEPIECES_PUBLIC_URL=${publicScheme}://automation.$Domain$publicSuffix
FLOWWINK_SUPABASE_URL=
FLOWWINK_SUPABASE_ANON_KEY=
FLOWWINK_SUPABASE_PROJECT_ID=
CHATWOOT_POSTGRES_IMAGE=pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc
ACTIVEPIECES_POSTGRES_IMAGE=pgvector/pgvector:0.8.0-pg14@sha256:c55d7e7deac05dde62139e0ded4fcf4f58363656cbc382dbea82fbed995aa767
ACTIVEPIECES_IMAGE=ghcr.io/activepieces/activepieces:0.86.3@sha256:208517c4f0d798a477a0c594bf432dd0f4918433f4b6f5b5f188a6e10e638c6c
"@
}

$temporaryEnv = ".$EnvFile.$([guid]::NewGuid().ToString('N')).tmp"
try {
    [IO.File]::WriteAllText((Join-Path (Get-Location) $temporaryEnv), $content, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryEnv -Destination $EnvFile
} finally {
    if (Test-Path -LiteralPath $temporaryEnv) { Remove-Item -LiteralPath $temporaryEnv -Force }
}

& "$PSScriptRoot/preflight-production.ps1" -EnvFile $EnvFile -Profile $Profile -Mode bootstrap -AllowDirty
if ($NoStart) { Write-Host "Configuración validada en $EnvFile; arranque omitido." -ForegroundColor Green; exit 0 }

$compose = @('compose','--env-file',$EnvFile,'-p',$Project,'-f','docker-compose.yml')
if ($Profile -eq 'production') { $compose += @('-f','infrastructure/compose/docker-compose.prod.example.yml') }
$compose += @('--profile',$Profile)
if ($Profile -eq 'production') {
    & docker @compose pull --policy always --ignore-buildable
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron preparar las imágenes externas fijadas por digest.' }
}
& docker @compose build --pull
if ($LASTEXITCODE -ne 0) { throw 'Falló el build; no se eliminaron datos ni el archivo de entorno.' }
if ($Profile -eq 'production') {
    & python "$PSScriptRoot/create-release-manifest.py" --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) { throw 'Las imágenes no tienen trazabilidad release válida.' }
}
& docker @compose up -d --no-build --pull never --wait --wait-timeout 600
if ($LASTEXITCODE -ne 0) { throw 'El stack no alcanzó readiness; no se eliminaron datos ni volúmenes.' }
& "$PSScriptRoot/check-health.ps1" -ClientId $ClientId -Profile $Profile

$receipt = @"
Instalación: $ClientId
Perfil: $Profile
Proyecto Compose: $Project
Portal/Proxy: ${publicScheme}://$Domain$publicSuffix
Usuario inicial: admin
Contraseña inicial: $AdminPassword
Cambiar la contraseña en el primer acceso.
Archivo de entorno: $EnvFile
"@
$receiptPath = "provision-$ClientId.txt"
[IO.File]::WriteAllText((Join-Path (Get-Location) $receiptPath), $receipt, [Text.UTF8Encoding]::new($false))
Write-Host "Instalación creada. Credenciales guardadas localmente en $receiptPath." -ForegroundColor Green
