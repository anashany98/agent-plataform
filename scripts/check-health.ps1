param([Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId)
$ErrorActionPreference='Stop'
$EnvFile=".env.$ClientId"; $Project="agent-$ClientId"
if (-not (Test-Path $EnvFile)) { throw "No existe $EnvFile" }
$compose=@('compose','--env-file',$EnvFile,'-p',$Project,'--profile','full')
$services=@('reverse-proxy','portal','bridge-api','bridge-db','bridge-redis','flowwink-app','chatwoot-web','chatwoot-worker','chatwoot-db','chatwoot-redis','activepieces-app','activepieces-worker','activepieces-db','activepieces-redis')
$failed=$false
foreach($service in $services){
  $cid=(& docker @compose ps -q $service).Trim()
  if(-not $cid){ Write-Host ("{0,-26} AUSENTE" -f $service); $failed=$true; continue }
  $state=(& docker inspect -f '{{.State.Status}}' $cid).Trim()
  $health=(& docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $cid).Trim()
  Write-Host ("{0,-26} estado={1,-10} salud={2}" -f $service,$state,$health)
  if($state -ne 'running' -or $health -notin @('healthy','none')){$failed=$true}
}
if($failed){throw 'Uno o más servicios no están saludables.'}
