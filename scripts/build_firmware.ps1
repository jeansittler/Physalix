[CmdletBinding()]
param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$Python = '',
    [string]$BuildDirectory = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedCliVersion = '1.5.1'
$ExpectedCoreVersion = '1.8.8'
$Fqbn = 'arduino:avr:uno'
$root = Split-Path -Parent $PSScriptRoot
$sketch = Join-Path $root 'firmware\physalix_acquisition_uno'
$metadata = Join-Path $sketch 'firmware_metadata.h'
$resourceDirectory = Join-Path $root 'physalix\resources\firmware\uno'
$resourceHex = Join-Path $resourceDirectory 'physalix_acquisition_uno.hex'
$manifest = Join-Path $resourceDirectory 'manifest.json'

try {
    $ArduinoCli = (Get-Command $ArduinoCli -ErrorAction Stop).Source
} catch {
    throw "Arduino CLI $ExpectedCliVersion est requis. Installez-le explicitement puis relancez ce script."
}

$versionOutput = (& $ArduinoCli version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch 'Version:\s*([^\s]+)') {
    throw "Impossible de déterminer la version d'Arduino CLI : $versionOutput"
}
if ($Matches[1] -ne $ExpectedCliVersion) {
    throw "Arduino CLI $ExpectedCliVersion attendu, version $($Matches[1]) détectée."
}

$coreOutput = (& $ArduinoCli core list 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "Impossible de lister les cores Arduino : $coreOutput" }
$coreLine = $coreOutput -split "`r?`n" | Where-Object { $_ -match '^arduino:avr\s+' } | Select-Object -First 1
if (-not $coreLine) {
    throw "Core arduino:avr@$ExpectedCoreVersion absent. Installez-le explicitement avec : arduino-cli core install arduino:avr@$ExpectedCoreVersion"
}
$installedCoreVersion = ($coreLine -split '\s+')[1]
if ($installedCoreVersion -ne $ExpectedCoreVersion) {
    throw "Core arduino:avr@$ExpectedCoreVersion attendu, version $installedCoreVersion détectée."
}

if (-not $Python) {
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
}
$Python = (Get-Command $Python -ErrorAction Stop).Source

if (-not $BuildDirectory) {
    $BuildDirectory = Join-Path $root 'build\firmware\physalix_acquisition_uno'
}
$BuildDirectory = [IO.Path]::GetFullPath($BuildDirectory)
New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null

Write-Host "Compilation firmware avec Arduino CLI $ExpectedCliVersion, core arduino:avr@$ExpectedCoreVersion, FQBN $Fqbn"
& $ArduinoCli compile --fqbn $Fqbn --clean --output-dir $BuildDirectory $sketch
if ($LASTEXITCODE -ne 0) { throw "La compilation Arduino a échoué avec le code $LASTEXITCODE." }

$compiledHex = Join-Path $BuildDirectory 'physalix_acquisition_uno.ino.hex'
$bootloaderHex = Join-Path $BuildDirectory 'physalix_acquisition_uno.ino.with_bootloader.hex'
if (-not (Test-Path -LiteralPath $compiledHex) -or (Get-Item -LiteralPath $compiledHex).Length -eq 0) {
    throw "HEX applicatif absent ou vide après compilation : $compiledHex"
}
$stagingDirectory = Join-Path $BuildDirectory 'distribution'
$stagedHex = Join-Path $stagingDirectory 'physalix_acquisition_uno.hex'
$stagedManifest = Join-Path $stagingDirectory 'manifest.json'
New-Item -ItemType Directory -Force -Path $stagingDirectory | Out-Null
Copy-Item -LiteralPath $compiledHex -Destination $stagedHex -Force

Push-Location $root
try {
    & $Python scripts/generate_firmware_manifest.py --metadata $metadata --hex $stagedHex --output $stagedManifest
    if ($LASTEXITCODE -ne 0) { throw "La génération du manifeste a échoué avec le code $LASTEXITCODE." }
} finally { Pop-Location }

New-Item -ItemType Directory -Force -Path $resourceDirectory | Out-Null
Copy-Item -LiteralPath $stagedHex -Destination $resourceHex -Force
Copy-Item -LiteralPath $stagedManifest -Destination $manifest -Force

Write-Host "HEX applicatif : $resourceHex"
Write-Host "Manifeste : $manifest"
if (Test-Path -LiteralPath $bootloaderHex) {
    Write-Host "Le HEX avec bootloader reste uniquement dans le dossier build et n'est pas distribué."
}
