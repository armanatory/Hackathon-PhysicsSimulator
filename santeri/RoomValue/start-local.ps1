# Start only missing RoomValue services on ports 8002 and 5175.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Get-HttpContent([string]$url) {
    try {
        return (Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing).Content
    } catch {
        return $null
    }
}

$apiUrl = 'http://127.0.0.1:8002'
$pageUrl = 'http://127.0.0.1:5175/'
$schema = Get-HttpContent "$apiUrl/openapi.json"
if ($schema) {
    if ($schema -notmatch '"title":"RoomValue"') {
        throw 'Port 8002 is in use by a different service.'
    }
} else {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = Join-Path (Split-Path $projectRoot -Parent) 'MetaSense\.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw 'Python 3.11 dependencies are missing. Install backend\requirements.txt in RoomValue\.venv.'
    }
    Start-Process -FilePath $pythonExe `
        -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8002') `
        -WorkingDirectory $projectRoot `
        -RedirectStandardOutput (Join-Path $runtimeDir 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'backend.stderr.log') -WindowStyle Hidden | Out-Null
}

$page = Get-HttpContent $pageUrl
if ($page) {
    if ($page -notmatch '<title>RoomValue') {
        throw 'Port 5175 is in use by a different service.'
    }
} else {
    $nodeCommand = Get-Command node -ErrorAction Stop
    $frontendDir = Join-Path $projectRoot 'frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules\vite\bin\vite.js'))) {
        throw 'Frontend dependencies are missing. Run pnpm install in RoomValue\frontend.'
    }
    Start-Process -FilePath $nodeCommand.Source `
        -ArgumentList @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5175', '--strictPort') `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'frontend.stderr.log') -WindowStyle Hidden | Out-Null
}

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $schema = Get-HttpContent "$apiUrl/openapi.json"
    $page = Get-HttpContent $pageUrl
    if ($schema -match '"title":"RoomValue"' -and $page -match '<title>RoomValue') {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 300
}
if (-not $ready) {
    throw "RoomValue did not become ready. Check logs in $runtimeDir."
}
Write-Output "RoomValue page: $pageUrl"
Write-Output "RoomValue API:  $apiUrl/docs"
