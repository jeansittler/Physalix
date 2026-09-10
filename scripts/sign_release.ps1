param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [Parameter(Mandatory=$true)][string]$TimestampUrl,
    [string]$SignTool = 'signtool.exe'
)
$ErrorActionPreference = 'Stop'
if ($TimestampUrl -notmatch '^https?://') { throw 'A timestamp server URL is required.' }
& $SignTool sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $FilePath
if ($LASTEXITCODE -ne 0) { throw "Signature failed: $FilePath" }
& $SignTool verify /pa /v $FilePath
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed: $FilePath" }
