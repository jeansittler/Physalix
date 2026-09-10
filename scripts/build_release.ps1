[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$Iscc = '',
    [switch]$PackageOnly,
    [string]$CertificateThumbprint = '',
    [string]$TimestampUrl = '',
    [string]$SignTool = 'signtool.exe'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Invoke-Logged([string]$Tool, [string[]]$ToolArgs, [string]$Log) {
    # Windows PowerShell 5.1 wraps native stderr in ErrorRecord objects.
    # Capture it without treating progress on stderr as a build failure.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Tool @ToolArgs *> $Log
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($code -ne 0) { throw "$Tool failed ($code); see $Log" }
}
$root = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
$Python = (Get-Command $Python -ErrorAction Stop).Source
Push-Location $root
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'artifacts') | Out-Null
    & $Python scripts/verify_distribution.py environment
    if ($LASTEXITCODE -ne 0) { throw 'Build environment check failed.' }
    $version = (& $Python -c "from physalix import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read version.' }
    if ($CertificateThumbprint -and -not $TimestampUrl) { throw 'Supply -TimestampUrl for signing.' }
    $existingExe = Join-Path $root 'dist\Physalix\Physalix.exe'
    if (Test-Path -LiteralPath $existingExe) {
        try {
            $handle = [IO.File]::Open($existingExe, 'Open', 'ReadWrite', 'None')
            $handle.Dispose()
        } catch { throw 'Close Physalix before building: executable locked or inaccessible.' }
    }
    # Delete only these known generated directories, never artifacts or the source tree.
    foreach ($relative in @('build\Physalix', 'dist\Physalix')) {
        $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not $target.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe cleanup path.' }
        if (Test-Path -LiteralPath $target) {
            $links = @(Get-Item -LiteralPath $target; Get-ChildItem -LiteralPath $target -Recurse -Force) |
                Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
            if ($links) { throw "Refusing cleanup through a junction/symlink: $target" }
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
    Invoke-Logged $Python @('-m', 'unittest', 'discover', '-s', 'tests', '-v') 'artifacts/release-tests.log'
    Write-Host 'Tests passed. Building Physalix...'
    Invoke-Logged $Python @('-m', 'PyInstaller', '--clean', '--noconfirm', 'Physalix.spec') 'artifacts/release-build.log'
    $bundle = Join-Path $root 'dist\Physalix'
    if ($CertificateThumbprint) {
        & "$PSScriptRoot\sign_release.ps1" -FilePath "$bundle\Physalix.exe" -CertificateThumbprint $CertificateThumbprint -TimestampUrl $TimestampUrl -SignTool $SignTool
    }
    & $Python scripts/verify_distribution.py bundle $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Frozen executable validation failed.' }
    & "$PSScriptRoot\test_launch.ps1" -Executable "$bundle\Physalix.exe"
    if ($PackageOnly) { Write-Host "Package verified: $bundle (installer explicitly skipped)."; return }
    if (-not $Iscc) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) { $Iscc = $command.Source }
        else {
            foreach ($candidate in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
                if (Test-Path -LiteralPath $candidate) { $Iscc = $candidate; break }
            }
        }
    }
    if (-not $Iscc) { throw 'Package verified, but Inno Setup 6 is missing. Install it from https://jrsoftware.org/isdl.php then rerun this script.' }
    $artifactDir = Join-Path $root 'artifacts'
    $installer = Join-Path $artifactDir "Physalix-Setup-$version.exe"
    if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force }
    Invoke-Logged $Iscc @("/DAppVersion=$version", "/DSourceDir=$bundle", "/DArtifactDir=$artifactDir", 'packaging/installer/Physalix.iss') 'artifacts/release-installer.log'
    if (-not (Test-Path -LiteralPath $installer)) { throw 'Inno Setup did not produce the installer.' }
    if ($CertificateThumbprint) {
        & "$PSScriptRoot\sign_release.ps1" -FilePath $installer -CertificateThumbprint $CertificateThumbprint -TimestampUrl $TimestampUrl -SignTool $SignTool
    }
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  Physalix-Setup-$version.exe" | Set-Content -LiteralPath "$installer.sha256" -Encoding ascii
    & $Python scripts/prepare_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Update manifest generation failed.' }
    Get-Item -LiteralPath $installer | Select-Object FullName, Length
    Write-Host "Release $version ready. No publication performed."
} finally { Pop-Location }
