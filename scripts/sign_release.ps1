[CmdletBinding()]
param(
    [string]$FilePath = '',
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [Parameter(Mandatory=$true)][string]$TimestampUrl,
    [string]$SignTool = '',
    [switch]$CheckOnly,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-SignTool([string]$RequestedPath) {
    if ($RequestedPath) {
        if (Test-Path -LiteralPath $RequestedPath -PathType Leaf) {
            return (Get-Item -LiteralPath $RequestedPath).FullName
        }
        $requestedCommand = Get-Command $RequestedPath -CommandType Application -ErrorAction SilentlyContinue
        if ($requestedCommand) { return $requestedCommand.Source }
        throw "SignTool was not found: $RequestedPath"
    }

    $command = Get-Command 'signtool.exe' -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $kitRoots = @()
    $installedRoots = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -ErrorAction SilentlyContinue
    if ($installedRoots -and $installedRoots.KitsRoot10) { $kitRoots += $installedRoots.KitsRoot10 }
    $kitRoots += "${env:ProgramFiles(x86)}\Windows Kits\10"
    foreach ($kitRoot in $kitRoots | Select-Object -Unique) {
        $binRoot = Join-Path $kitRoot 'bin'
        if (-not (Test-Path -LiteralPath $binRoot -PathType Container)) { continue }
        $candidates = Get-ChildItem -LiteralPath $binRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
            Sort-Object { [version]$_.Name } -Descending |
            ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' }
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    throw 'SignTool was not found. Install the Windows SDK or pass -SignTool (or PHYSALIX_SIGNTOOL).'
}

$thumbprint = ($CertificateThumbprint -replace '\s', '').ToUpperInvariant()
if ($thumbprint -notmatch '^[0-9A-F]{40}$') { throw 'CertificateThumbprint must be a SHA-1 certificate thumbprint (40 hexadecimal characters).' }
if ($TimestampUrl -notmatch '^https?://') { throw 'An RFC 3161 timestamp server URL is required.' }
$resolvedSignTool = Resolve-SignTool $SignTool
$certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
if (-not $certificate) {
    throw "Code-signing certificate $thumbprint is unavailable in Cert:\CurrentUser\My. Connect and authenticate SimplySign Desktop, then retry."
}
if (-not $certificate.HasPrivateKey) { throw "Certificate $thumbprint has no accessible private key." }

if ($CheckOnly) {
    Write-Host "Signing prerequisites ready: $resolvedSignTool"
    return
}
if (-not $FilePath) { throw 'FilePath is required unless -CheckOnly is used.' }
$resolvedFile = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path

if (-not $VerifyOnly) {
    & $resolvedSignTool sign /sha1 $thumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $resolvedFile
    if ($LASTEXITCODE -ne 0) { throw "Signature or RFC 3161 timestamping failed: $resolvedFile" }
}
& $resolvedSignTool verify /pa /all /v $resolvedFile
if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed: $resolvedFile" }

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedFile
if ($signature.Status -ne 'Valid') { throw "Windows reports an invalid Authenticode signature on $resolvedFile ($($signature.Status))." }
if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $thumbprint) {
    throw "Unexpected signing certificate on $resolvedFile."
}
if (-not $signature.TimeStamperCertificate) { throw "RFC 3161 timestamp is missing on $resolvedFile." }
Write-Host "Verified Authenticode signature, certificate $thumbprint, and RFC 3161 timestamp: $resolvedFile"
