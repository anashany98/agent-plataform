param(
    [ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId = 'desarrollo-local',
    [string]$Domain = '',
    [ValidateRange(1024,65535)][int]$ProxyPort = 9000
)
$ErrorActionPreference = 'Stop'
if (-not $Domain) { $Domain = "$ClientId.local" }
& "$PSScriptRoot/scripts/provision-client.ps1" -ClientId $ClientId -Domain $Domain -ProxyPort $ProxyPort
