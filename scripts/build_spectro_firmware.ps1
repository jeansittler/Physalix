[CmdletBinding()]
param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$Python = '',
    [string]$BuildDirectory = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$sketch = Join-Path $root 'firmware\physalix_spectrophotometer_nano'
$metadata = Join-Path $sketch 'firmware_metadata.h'
$resourceDirectory = Join-Path $root 'physalix\resources\firmware\nano-spectro'
$uploaderDirectory = Join-Path $root 'physalix\resources\firmware\uno'
$resourceHex = Join-Path $resourceDirectory 'physalix_spectrophotometer_nano.hex'
$manifest = Join-Path $resourceDirectory 'manifest.json'
$ArduinoCli = (Get-Command $ArduinoCli -ErrorAction Stop).Source
$versionOutput = (& $ArduinoCli version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch 'Version:\s*1\.5\.1(?:\s|$)') {
    throw "Arduino CLI 1.5.1 requis : $versionOutput"
}
$core = (& $ArduinoCli core list 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $core -notmatch '(?m)^arduino:avr\s+1\.8\.8\s') {
    throw 'Core arduino:avr@1.8.8 requis.'
}
$libraries = (& $ArduinoCli lib list 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $libraries -notmatch '(?m)^Adafruit AS7341\s+1\.4\.1\s') {
    throw 'Bibliothèque Adafruit AS7341 1.4.1 requise.'
}
if (-not $Python) {
    $Python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        $Python = Join-Path (Split-Path -Parent $root) 'Physalix\.venv\Scripts\python.exe'
    }
}
$Python = (Get-Command $Python -ErrorAction Stop).Source
if (-not $BuildDirectory) {
    $BuildDirectory = Join-Path $root 'build\firmware\physalix_spectrophotometer_nano'
}
$BuildDirectory = [IO.Path]::GetFullPath($BuildDirectory)
New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null
& $ArduinoCli compile --fqbn arduino:avr:uno --clean --warnings all `
    --output-dir $BuildDirectory $sketch
if ($LASTEXITCODE -ne 0) { throw "Compilation Arduino échouée ($LASTEXITCODE)." }
$compiled = Join-Path $BuildDirectory 'physalix_spectrophotometer_nano.ino.hex'
if (-not (Test-Path -LiteralPath $compiled)) { throw "HEX applicatif absent : $compiled" }
New-Item -ItemType Directory -Force -Path $resourceDirectory | Out-Null
Copy-Item -LiteralPath $compiled -Destination $resourceHex -Force
Push-Location $root
try {
    & $Python scripts/generate_firmware_manifest.py --target spectro `
        --metadata $metadata --hex $resourceHex --output $manifest `
        --uploader-directory $uploaderDirectory
    if ($LASTEXITCODE -ne 0) { throw "Génération du manifeste échouée ($LASTEXITCODE)." }
} finally { Pop-Location }
Write-Host "Firmware Nano : $resourceHex"
Write-Host "Manifeste : $manifest"
