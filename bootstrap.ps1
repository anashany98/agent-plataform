param(
    [ValidatePattern('^[a-z0-9][a-z0-9-]{1,48}$')][string]$ClientId = 'desarrollo-local',
    [string]$Domain = '',
    [ValidateRange(1024,65535)][int]$ProxyPort = 9000,
    [ValidateSet('core','full','production')][string]$Profile = 'core',
    [string]$TlsCertificate = '',
    [string]$TlsPrivateKey = '',
    [switch]$AllowSelfSignedTlsBootstrap,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
if (-not $Domain) { $Domain = "$ClientId.local" }
$arguments = @{
    ClientId = $ClientId
    Domain = $Domain
    ProxyPort = $ProxyPort
    Profile = $Profile
    TlsCertificate = $TlsCertificate
    TlsPrivateKey = $TlsPrivateKey
    AllowSelfSignedTlsBootstrap = $AllowSelfSignedTlsBootstrap
    NoStart = $NoStart
}
& "$PSScriptRoot/scripts/provision-client.ps1" @arguments
