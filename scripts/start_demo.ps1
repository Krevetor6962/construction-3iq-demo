param([int]$Port = 8095)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Create the project environment and install its dependencies first; see README.md."
}
Set-Location $Root
& $Python (Join-Path $Root "apps\construction-command-center\server.py") --port $Port
exit $LASTEXITCODE
