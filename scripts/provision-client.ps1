param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId,
    [string]$Domain = "",
    [ValidateRange(1024,65535)][int]$ProxyPort = 9000
)
$ErrorActionPreference = "Stop"
if (-not $Domain) { $Domain = "$ClientId.local" }
$Project = "agent-$ClientId"
$EnvFile = ".env.$ClientId"
if (Test-Path $EnvFile) { throw "$EnvFile ya existe. No se sobrescribe para evitar perder secretos." }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker no está instalado." }

# Preflight atómico (D-009): valida que el puerto esté libre ANTES de escribir
# .env / build / up, para no alterar instalaciones existentes ni dejar parciales.
try {
  $probe = New-Object System.Net.Sockets.TcpClient
  $probe.Connect("127.0.0.1", $ProxyPort)
  $probe.Close()
  throw "El puerto $ProxyPort ya está en uso por otro proceso/proyecto. Elige otro puerto (parámetro -ProxyPort)."
} catch [System.Net.Sockets.SocketException] {
  # Conexión rechazada => puerto libre; continuar.
}

docker compose version | Out-Null
function New-Secret([int]$Bytes = 36) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer).Replace("`r","").Replace("`n","")
}
function New-Hex([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return ([BitConverter]::ToString($buffer)).Replace("-","").ToLowerInvariant()
}
$AdminPassword = "$(New-Secret 24)Aa1!"
$content = @"
COMPOSE_PROJECT_NAME=$Project
ENVIRONMENT=staging
INSTALLATION_ID=$ClientId
PILOT_MODE=true
AUTO_SEED_DEMO_DATA=false
PROXY_PORT=$ProxyPort
PORTAL_HOST=$Domain
API_HOST=api.$Domain
CHATWOOT_HOST=chat.$Domain
FLOWWINK_HOST=agents.$Domain
ACTIVEPIECES_HOST=automation.$Domain
ALLOWED_ORIGINS=https://$Domain,https://chat.$Domain,http://$Domain,http://localhost:$ProxyPort
ALLOWED_HOSTS=$Domain,api.$Domain,localhost,127.0.0.1,bridge-api
POSTGRES_DB=bridge_db
POSTGRES_USER=bridge_user
POSTGRES_PASSWORD=$(New-Secret 36)
REDIS_PASSWORD=$(New-Secret 36)
AUTH_SECRET=$(New-Secret 48)
AUTH_TOKEN_TTL_SEC=3600
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=$AdminPassword
CHATWOOT_WEBHOOK_SECRET=$(New-Secret 48)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=120
LOGIN_RATE_LIMIT_REQUESTS=8
LOGIN_RATE_LIMIT_WINDOW_SEC=900
CHATWOOT_SECRET_KEY_BASE=$(New-Hex 64)
CHATWOOT_POSTGRES_DB=chatwoot_db
CHATWOOT_POSTGRES_USER=chatwoot
CHATWOOT_POSTGRES_PASSWORD=$(New-Secret 36)
CHATWOOT_REDIS_PASSWORD=$(New-Secret 36)
CHATWOOT_API_TOKEN=
CHATWOOT_ACCOUNT_ID=
BRIDGE_WEBHOOK_URL=
CHATWOOT_PUBLIC_URL=https://chat.$Domain
ACTIVEPIECES_POSTGRES_DB=activepieces
ACTIVEPIECES_POSTGRES_USER=activepieces
ACTIVEPIECES_POSTGRES_PASSWORD=$(New-Secret 36)
ACTIVEPIECES_REDIS_PASSWORD=$(New-Secret 36)
ACTIVEPIECES_ENCRYPTION_KEY=$(New-Hex 16)
ACTIVEPIECES_JWT_SECRET=$(New-Secret 48)
ACTIVEPIECES_API_KEY=
ACTIVEPIECES_PUBLIC_URL=https://automation.$Domain
PRESTASHOP_BASE_URL=
PRESTASHOP_API_KEY=
PRESTASHOP_SHOP_ID=
GHL_BASE_URL=https://services.leadconnectorhq.com
GHL_API_TOKEN=
GHL_LOCATION_ID=
GHL_PIPELINE_ID=
GHL_PIPELINE_STAGE_ID=
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false
OLLAMA_BASE_URL=http://host.docker.internal:11434
CHEAP_LLM_PROVIDER=ollama
CHEAP_LLM_MODEL=qwen2.5:3b
STANDARD_LLM_PROVIDER=ollama
STANDARD_LLM_MODEL=qwen2.5:7b
ADVANCED_LLM_PROVIDER=openai
ADVANCED_LLM_MODEL=
CRITICAL_LLM_PROVIDER=anthropic
CRITICAL_LLM_MODEL=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
ANTHROPIC_API_KEY=
LLM_MAX_DAILY_COST_USD=25
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
EMBEDDING_BASE_URL=http://host.docker.internal:11434
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
FLOWWINK_SUPABASE_URL=
FLOWWINK_SUPABASE_ANON_KEY=
FLOWWINK_SUPABASE_PROJECT_ID=
"@
[IO.File]::WriteAllText((Join-Path (Get-Location) $EnvFile), $content, [Text.UTF8Encoding]::new($false))
$compose = @("compose", "--env-file", $EnvFile, "-p", $Project, "--profile", "full")
& docker @compose config | Out-Null
& docker @compose build --pull
& docker @compose up -d
$services = @('reverse-proxy','portal','bridge-api','bridge-db','bridge-redis','flowwink-app','chatwoot-web','chatwoot-worker','chatwoot-db','chatwoot-redis','activepieces-app','activepieces-worker','activepieces-db','activepieces-redis')
$deadline = (Get-Date).AddMinutes(10)
do {
    $allReady = $true
    foreach ($service in $services) {
        $cid = (& docker @compose ps -q $service).Trim()
        if (-not $cid) { $allReady = $false; continue }
        $status = (& docker inspect -f '{{.State.Status}}' $cid).Trim()
        $health = (& docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $cid).Trim()
        if ($status -ne 'running' -or ($health -notin @('healthy','none'))) { $allReady = $false }
    }
    if (-not $allReady) { Start-Sleep -Seconds 5 }
} while (-not $allReady -and (Get-Date) -lt $deadline)
& docker @compose ps
if (-not $allReady) { throw "El stack no alcanzó estado saludable. Revisa los logs." }
$receipt = @"
Instalación: $ClientId
Proyecto Compose: $Project
Portal/Proxy: http://localhost:$ProxyPort
Usuario inicial: admin
Contraseña inicial: $AdminPassword
Cambiar la contraseña en el primer acceso.
Archivo de entorno: $EnvFile
"@
[IO.File]::WriteAllText((Join-Path (Get-Location) "provision-$ClientId.txt"), $receipt, [Text.UTF8Encoding]::new($false))
Write-Host "Instalación creada. Credenciales guardadas en provision-$ClientId.txt." -ForegroundColor Green
