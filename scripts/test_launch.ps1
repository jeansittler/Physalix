param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
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
    } while ($process.MainWindowTitle -ne 'Physalix' -and [DateTime]::UtcNow -lt $deadline)
    if ($process.MainWindowTitle -ne 'Physalix' -or -not $process.Responding) { throw 'No responsive Physalix window.' }
    $modules = @($process.Modules | ForEach-Object { $_.FileName })
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
