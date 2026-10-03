# Keep the PC side of roomvalue.santerihukari.com running on loopback only.
$ErrorActionPreference = 'Stop'
$caseRoot = $PSScriptRoot
$cloudRuntime = Join-Path $caseRoot '.runtime\cloudflare'
$pythonExe = Join-Path (Split-Path $caseRoot -Parent) '.venv\Scripts\python.exe'
$privateTokenPath = Join-Path $cloudRuntime 'tunnel-token.txt'
$originSecretPath = Join-Path $cloudRuntime 'origin-secret.txt'
foreach ($requiredPath in @($pythonExe, $privateTokenPath, $originSecretPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Required RoomValue file missing: $requiredPath" }
}
$originSecret = (Get-Content -LiteralPath $originSecretPath -Raw).Trim()
$bridgeHeaders = @{ 'X-RoomValue-Origin-Secret' = $originSecret }

function Get-RoomResponse([string]$uri, [hashtable]$headers = @{}) {
    try { return Invoke-WebRequest -Uri $uri -Headers $headers -UseBasicParsing -TimeoutSec 3 }
    catch { return $null }
}

$apiSchema = Get-RoomResponse 'http://127.0.0.1:8002/openapi.json'
if ($apiSchema) {
    if ($apiSchema.Content -notmatch '"title":"RoomValue"') { throw 'Port 8002 belongs to another application.' }
} else {
    Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8002') -WorkingDirectory $caseRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cloudRuntime 'api.stdout.log') -RedirectStandardError (Join-Path $cloudRuntime 'api.stderr.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $apiSchema = Get-RoomResponse 'http://127.0.0.1:8002/openapi.json'
    if ($apiSchema -and $apiSchema.Content -match '"title":"RoomValue"') { break }
    Start-Sleep -Milliseconds 200
}
if (-not $apiSchema) { throw 'RoomValue API did not start.' }

$bridgeHealth = Get-RoomResponse 'http://127.0.0.1:8004/api/health' $bridgeHeaders
if (-not $bridgeHealth) {
    $portInUse = Get-NetTCPConnection -LocalPort 8004 -State Listen -ErrorAction SilentlyContinue
    if ($portInUse) { throw 'Port 8004 is occupied by a service that does not accept RoomValue bridge authentication.' }
    Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'backend.cloud_bridge:app', '--host', '127.0.0.1', '--port', '8004') -WorkingDirectory $caseRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cloudRuntime 'bridge.stdout.log') -RedirectStandardError (Join-Path $cloudRuntime 'bridge.stderr.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $bridgeHealth = Get-RoomResponse 'http://127.0.0.1:8004/api/health' $bridgeHeaders
    if ($bridgeHealth) { break }
    Start-Sleep -Milliseconds 200
}
if (-not $bridgeHealth) { throw 'Authenticated RoomValue bridge did not start.' }
try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8004/api/health' -UseBasicParsing -TimeoutSec 3 | Out-Null
    throw 'RoomValue bridge unexpectedly accepts unauthenticated requests.'
} catch {
    if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 403) { throw }
}

$runningConnector = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'cloudflared.exe' -and $_.CommandLine -match [regex]::Escape($privateTokenPath)
}
if (-not $runningConnector) {
    $cloudflaredExe = (Get-Command cloudflared -ErrorAction Stop).Source
    $tunnelArguments = @('--no-autoupdate', 'tunnel', '--protocol', 'quic', '--loglevel', 'warn', '--metrics', '127.0.0.1:20251', 'run', '--token-file', ('"' + $privateTokenPath + '"'))
    $connector = Start-Process -FilePath $cloudflaredExe -ArgumentList $tunnelArguments -WorkingDirectory $caseRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cloudRuntime 'tunnel.stdout.log') -RedirectStandardError (Join-Path $cloudRuntime 'tunnel.stderr.log') -PassThru
    $connector.Id | Set-Content -LiteralPath (Join-Path $cloudRuntime 'tunnel.pid')
}
Write-Output 'RoomValue API verified on 127.0.0.1:8002.'
Write-Output 'Authenticated RoomValue bridge verified on 127.0.0.1:8004; unsigned requests return 403.'
Write-Output 'Private Cloudflare connector started. Website: https://roomvalue.santerihukari.com/'
