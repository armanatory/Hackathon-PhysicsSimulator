# Start missing MetaSense services on their reserved local ports.
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

$apiUrl = 'http://127.0.0.1:8001'
$pageUrl = 'http://127.0.0.1:5174/'
$apiSchema = Get-HttpContent "$apiUrl/openapi.json"
if ($apiSchema) {
    if ($apiSchema -notmatch '"title":"MetaSense"') {
        throw "Port 8001 is in use by a different service."
    }
} else {
    $pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "MetaSense Python environment is missing: $pythonExe"
    }
    $backendDir = Join-Path $projectRoot 'backend'
    $backendArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001')
    if (Test-Path -LiteralPath (Join-Path (Split-Path $projectRoot -Parent) '.env')) {
        $backendArgs += @('--env-file', '..\..\.env')
    }
    Start-Process -FilePath $pythonExe -ArgumentList $backendArgs -WorkingDirectory $backendDir `
        -RedirectStandardOutput (Join-Path $runtimeDir 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'backend.stderr.log') -WindowStyle Hidden | Out-Null
}

$page = Get-HttpContent $pageUrl
if ($page) {
    if ($page -notmatch '<title>MetaSense') {
        throw "Port 5174 is in use by a different service."
    }
} else {
    $nodeCommand = Get-Command node -ErrorAction Stop
    $frontendDir = Join-Path $projectRoot 'frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules\vite\bin\vite.js'))) {
        throw 'Frontend dependencies are missing. Run pnpm install in MetaSense\frontend.'
    }
    Start-Process -FilePath $nodeCommand.Source `
        -ArgumentList @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5174', '--strictPort') `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'frontend.stderr.log') -WindowStyle Hidden | Out-Null
}

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    $apiSchema = Get-HttpContent "$apiUrl/openapi.json"
    $page = Get-HttpContent $pageUrl
    if ($apiSchema -match '"title":"MetaSense"' -and $page -match '<title>MetaSense') {
        $ready = $true
        break
    }
    Start-Sleep -Milliseconds 300
}
if (-not $ready) {
    throw "MetaSense did not become ready. Check logs in $runtimeDir."
}
Write-Output "MetaSense page: $pageUrl"
Write-Output "MetaSense API:  $apiUrl/docs"
