$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$exe = Join-Path $PSScriptRoot 'dist\Physalix\Physalix.exe'
if (Test-Path -LiteralPath $exe) {
    try {
        $handle = [System.IO.File]::Open($exe, 'Open', 'ReadWrite', 'None')
        $handle.Dispose()
    } catch {
        throw 'Fermez Physalix avant de reconstruire : son exécutable est verrouillé ou inaccessible.'
    }
}
& $python -m PyInstaller --clean --noconfirm Physalix.spec
if ($LASTEXITCODE -ne 0) { throw 'La construction a échoué.' }
Copy-Item -LiteralPath 'NOTICE-DEMO.txt' -Destination 'dist\Physalix\LISEZ-MOI.txt'
Copy-Item -LiteralPath 'README.md' -Destination 'dist\Physalix\GUIDE.md'
Get-Item -LiteralPath 'dist\Physalix\Physalix.exe'
