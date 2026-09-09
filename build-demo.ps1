$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m PyInstaller --noconfirm Physalyx.spec
if ($LASTEXITCODE -ne 0) { throw 'La construction a échoué.' }
Copy-Item -LiteralPath 'NOTICE-DEMO.txt' -Destination 'dist\Physalix\LISEZ-MOI.txt'
Copy-Item -LiteralPath 'README.md' -Destination 'dist\Physalix\GUIDE.md'
Get-Item -LiteralPath 'dist\Physalix\Physalix.exe'
