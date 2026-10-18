[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$Iscc = '',
    [switch]$PackageOnly,
    [string]$CertificateThumbprint = '',
    [string]$TimestampUrl = '',
    [string]$SignTool = '',
    [switch]$AllowUnsigned
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
$signScript = Join-Path $PSScriptRoot 'sign_release.ps1'
if (-not $CertificateThumbprint) {
    $CertificateThumbprint = if ($env:PHYSALIX_CERTIFICATE_THUMBPRINT) { $env:PHYSALIX_CERTIFICATE_THUMBPRINT } else { '2ab2e1ce2e420168237ed606cf324ad2da45f809' }
}
if (-not $TimestampUrl) {
    $TimestampUrl = if ($env:PHYSALIX_TIMESTAMP_URL) { $env:PHYSALIX_TIMESTAMP_URL } else { 'http://time.certum.pl/' }
}
if (-not $SignTool -and $env:PHYSALIX_SIGNTOOL) { $SignTool = $env:PHYSALIX_SIGNTOOL }
$signingArguments = @{
    CertificateThumbprint = $CertificateThumbprint
    TimestampUrl = $TimestampUrl
}
if ($SignTool) { $signingArguments.SignTool = $SignTool }
Push-Location $root
try {
    if ($AllowUnsigned) {
        Write-Warning 'Unsigned build explicitly requested. These artifacts are not release-ready.'
    } else {
        & $signScript @signingArguments -CheckOnly
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'artifacts') | Out-Null
    & $Python scripts/verify_distribution.py environment
    if ($LASTEXITCODE -ne 0) { throw 'Build environment check failed.' }
    $version = (& $Python -c "from physalix import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read version.' }
    $existingExe = Join-Path $root 'dist\Physalyx\Physalyx.exe'
    if (Test-Path -LiteralPath $existingExe) {
        try {
            $handle = [IO.File]::Open($existingExe, 'Open', 'ReadWrite', 'None')
            $handle.Dispose()
        } catch { throw 'Close Physalyx before building: executable locked or inaccessible.' }
    }
    # Delete only these known generated directories, never artifacts or the source tree.
    foreach ($relative in @('build\Physalyx', 'dist\Physalyx')) {
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
    Write-Host 'Tests passed. Building Physalyx...'
    Invoke-Logged $Python @('-m', 'PyInstaller', '--clean', '--noconfirm', 'Physalix.spec') 'artifacts/release-build.log'
    $bundle = Join-Path $root 'dist\Physalyx'
    if (-not $AllowUnsigned) {
        & $signScript @signingArguments -FilePath "$bundle\Physalyx.exe"
    }
    & $Python scripts/verify_distribution.py bundle $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Frozen executable validation failed.' }
    & $Python scripts/generate_compliance.py $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Third-party compliance inventory failed.' }
    & "$PSScriptRoot\test_launch.ps1" -Executable "$bundle\Physalyx.exe"
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
    $installer = Join-Path $artifactDir "Physalyx-Setup-$version.exe"
    if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force }
    $isccArguments = @("/DAppVersion=$version", "/DSourceDir=$bundle", "/DArtifactDir=$artifactDir")
    if (-not $AllowUnsigned) {
        # Inno invokes the same checked signer for Setup, the uninstaller and its temporary self-copies.
        $innoSignCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File $q{0}$q -FilePath $f -CertificateThumbprint {1} -TimestampUrl $q{2}$q' -f $signScript, $CertificateThumbprint, $TimestampUrl
        if ($SignTool) { $innoSignCommand += ' -SignTool $q{0}$q' -f $SignTool }
        $isccArguments += '/DSignToolName=physalix'
        $isccArguments += "/Sphysalix=$innoSignCommand"
    }
    $isccArguments += 'packaging/installer/Physalix.iss'
    Invoke-Logged $Iscc $isccArguments 'artifacts/release-installer.log'
    if (-not (Test-Path -LiteralPath $installer)) { throw 'Inno Setup did not produce the installer.' }
    if (-not $AllowUnsigned) {
        # Inno signed it natively; verify it once more before any final digest is calculated.
        & $signScript @signingArguments -FilePath $installer -VerifyOnly
    }
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  Physalyx-Setup-$version.exe" | Set-Content -LiteralPath "$installer.sha256" -Encoding ascii
    & $Python scripts/prepare_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Update manifest generation failed.' }
    Get-Item -LiteralPath $installer | Select-Object FullName, Length
    if ($AllowUnsigned) {
        Write-Warning "Unsigned build $version ready for testing only. Do not publish these artifacts."
    } else {
        Write-Host "Signed release $version ready. No publication performed."
    }
} finally { Pop-Location }
