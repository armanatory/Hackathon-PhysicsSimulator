param([string]$Python)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $exhaustBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $exhaustBundledPython) { $Python = $exhaustBundledPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
try {
    $exhaustHealth = Invoke-RestMethod 'http://127.0.0.1:8003/api/health' -TimeoutSec 2
    if ($exhaustHealth.status -eq 'ok') {
        Write-Host 'ExhaustLab is already running at http://127.0.0.1:5176/'
        exit 0
    }
} catch { }
& $Python -c 'import numpy'
if ($LASTEXITCODE -ne 0) { throw 'This Python needs NumPy 2.x. Pass a NumPy-capable interpreter using -Python.' }
& $Python -u (Join-Path $PSScriptRoot 'server.py')
