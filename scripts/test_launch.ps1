param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$productVersion = (Get-Item -LiteralPath $Executable).VersionInfo.ProductVersion
$expectedTitle = if ($productVersion -like '*-dev') { "Physalix $([char]0x2014) $productVersion" } else { 'Physalix' }
if (-not ('PhysalixSmoke.NativeMethods' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;

namespace PhysalixSmoke {
    public static class NativeMethods {
        [DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
        public static extern int GetWindowLong(IntPtr window, int index);
    }
}
'@
}
$windowStyleIndex = -16  # GWL_STYLE
$overlappedWindowMask = 0x00CF0000  # WS_OVERLAPPEDWINDOW; absent from the splash.
$root = Split-Path -Parent $PSScriptRoot
$savedEnvironment = @{}
Get-ChildItem Env: | Where-Object { $_.Name -match '^(PATH$|PYTHON|QT_|PYSIDE|VIRTUAL_ENV|CONDA)' } |
    ForEach-Object { $savedEnvironment[$_.Name] = $_.Value }
$process = $null
try {
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    # This requested GUI smoke test intentionally opens the application window.
    $process = Start-Process -FilePath $Executable -WorkingDirectory $env:TEMP -WindowStyle Normal -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 200
        $process.Refresh()
        if ($process.HasExited) { throw "Physalix exited during startup: $($process.ExitCode)" }
        $window = $process.MainWindowHandle
        $style = if ($window -ne [IntPtr]::Zero) {
            [PhysalixSmoke.NativeMethods]::GetWindowLong($window, $windowStyleIndex)
        } else { 0 }
        $mainWindowReady = (
            $process.MainWindowTitle -eq $expectedTitle -and
            ($style -band $overlappedWindowMask) -eq $overlappedWindowMask
        )
    } while (-not $mainWindowReady -and [DateTime]::UtcNow -lt $deadline)
    if (-not $mainWindowReady -or -not $process.Responding) { throw 'No responsive Physalix main window.' }
    $modules = @(
        foreach ($module in $process.Modules) {
            $module.FileName
        }
    )
    if ($modules | Where-Object { $_ -match '\\.venv\\|\\codex-runtimes\\' }) { throw 'Developer DLL used by the application.' }
    $pythonDll = @($modules | Where-Object { $_ -like '*\python312.dll' })
    $bundleRoot = Split-Path -Parent $Executable
    if ($pythonDll.Count -ne 1 -or -not $pythonDll[0].StartsWith($bundleRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The bundled Python DLL was not loaded.'
    }
    $report = @{ ok = $true; executable = $Executable; title = $process.MainWindowTitle; modules = $modules; cwd = $env:TEMP }
    if (-not $process.CloseMainWindow() -or -not $process.WaitForExit(10000)) { throw 'Physalix did not close normally.' }
    if ($process.ExitCode -ne 0) { throw "Physalix exit code: $($process.ExitCode)" }
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$root\artifacts\normal-launch-check.json" -Encoding UTF8
    Write-Host 'Normal launch OK: responsive window, bundled Python DLL, clean exit.'
} finally {
    if ($process) { if (-not $process.HasExited) { $process.Kill() }; $process.Dispose() }
    foreach ($key in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process') }
}
