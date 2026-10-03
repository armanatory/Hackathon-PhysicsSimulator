# Start only the MetaSense API, protected bridge, and private QUIC connector.
# This script never stops services, provisions Cloudflare, or launches a search.
$ErrorActionPreference = 'Stop'
$caseRoot = $PSScriptRoot
$cloudRuntime = Join-Path $caseRoot '.runtime\cloudflare'
$pythonExe = Join-Path $caseRoot '.venv\Scripts\python.exe'
$backendDir = Join-Path $caseRoot 'backend'
$privateTokenPath = Join-Path $cloudRuntime 'tunnel-token.txt'
$originSecretPath = Join-Path $cloudRuntime 'origin-secret.txt'
$apiPort = 8001
$bridgePort = 8005
$metricsPort = 20252

New-Item -ItemType Directory -Path $cloudRuntime -Force | Out-Null
foreach ($requiredPath in @($pythonExe, $privateTokenPath, $originSecretPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required MetaSense file missing: $requiredPath"
    }
}
if ((Get-Item -LiteralPath $privateTokenPath).Length -eq 0) { throw 'Private tunnel token file is empty.' }
$originSecret = (Get-Content -LiteralPath $originSecretPath -Raw).Trim()
if ($originSecret.Length -lt 32 -or $originSecret.Length -gt 512 -or $originSecret -notmatch '^[\x20-\x7E]+$') {
    throw 'Private MetaSense origin secret is invalid.'
}
$bridgeHeaders = @{ 'X-MetaSense-Origin-Secret' = $originSecret }
# The environment contains only a file path; the secret is never a command argument.
$env:METASENSE_ORIGIN_SECRET_FILE = $originSecretPath

function Get-MetaResponse([string]$uri, [hashtable]$headers = @{}) {
    try { return Invoke-WebRequest -Uri $uri -Headers $headers -UseBasicParsing -TimeoutSec 2 }
    catch { return $null }
}

function Test-MetaSchema($response) {
    if (-not $response) { return $false }
    try { return (($response.Content | ConvertFrom-Json).info.title -eq 'MetaSense') }
    catch { return $false }
}

function Get-MetaListeners([int]$port) {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Assert-MetaLoopback($listeners, [int]$port) {
    foreach ($listener in $listeners) {
        if ($listener.LocalAddress -ne '127.0.0.1') {
            throw "Port $port is not restricted to the expected loopback address."
        }
    }
}

function Save-MetaProcessRecord([string]$name, $processInfo, [string]$moduleName = '', [int]$port = 0) {
    if (-not $processInfo -or -not $processInfo.ExecutablePath -or -not $processInfo.CreationDate) {
        throw "Cannot verify the $name process identity."
    }
    $processRecord = [ordered]@{
        pid = [int]$processInfo.ProcessId
        parent_pid = [int]$processInfo.ParentProcessId
        creation_time_utc = ([datetime]$processInfo.CreationDate).ToUniversalTime().ToString('O')
        executable = [string]$processInfo.ExecutablePath
        module = $moduleName
        loopback_port = $port
        verified_at_utc = [datetime]::UtcNow.ToString('O')
    }
    $recordPath = Join-Path $cloudRuntime ($name + '.process.json')
    $processRecord | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding UTF8
}

function Get-MetaRecordedProcess([string]$name) {
    $recordPath = Join-Path $cloudRuntime ($name + '.process.json')
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) { return $null }
    try {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $processId = [int]$record.pid
        if ($processId -le 0) { return $null }
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
        if (-not $processInfo) { return $null }
        $creation = ([datetime]$processInfo.CreationDate).ToUniversalTime().ToString('O')
        $savedCreation = ([datetime]$record.creation_time_utc).ToUniversalTime().ToString('O')
        if ($creation -ne $savedCreation -or $processInfo.ExecutablePath -ne $record.executable) {
            return $null # Stale/reused PIDs are never trusted or stopped.
        }
        return $processInfo
    } catch { return $null }
}

function Register-MetaListener([string]$name, [string]$moduleName, [int]$port) {
    $listeners = Get-MetaListeners $port
    if (-not $listeners) { throw "$name did not open its reserved loopback port." }
    Assert-MetaLoopback $listeners $port
    $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($processIds.Count -ne 1) { throw "Port $port has ambiguous process ownership." }
    $processId = [int]$processIds[0]
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $modulePattern = '(?:^|\s)-m\s+uvicorn\s+' + [regex]::Escape($moduleName) + '(?:\s|$)'
    $hostPattern = '(?:^|\s)--host\s+127\.0\.0\.1(?:\s|$)'
    $portPattern = '(?:^|\s)--port\s+' + $port + '(?:\s|$)'
    if (-not $processInfo -or $processInfo.Name -ne 'python.exe' -or
        $processInfo.CommandLine -notmatch $modulePattern -or
        $processInfo.CommandLine -notmatch $hostPattern -or $processInfo.CommandLine -notmatch $portPattern) {
        throw "Port $port belongs to an unverified service; no process was stopped."
    }
    $previous = Get-MetaRecordedProcess $name
    if ($previous -and $previous.ProcessId -ne $processId) {
        throw "A different verified $name process already exists; no duplicate was started."
    }
    Save-MetaProcessRecord $name $processInfo $moduleName $port
}

$apiUri = "http://127.0.0.1:$apiPort"
$apiSchema = Get-MetaResponse "$apiUri/openapi.json"
if ($apiSchema) {
    if (-not (Test-MetaSchema $apiSchema)) { throw 'Port 8001 belongs to another application.' }
} else {
    if (Get-MetaListeners $apiPort) { throw 'Port 8001 is occupied by an unverified service.' }
    $apiArguments = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$apiPort")
    $privateEnvironment = Join-Path (Split-Path $caseRoot -Parent) '.env'
    if (Test-Path -LiteralPath $privateEnvironment -PathType Leaf) {
        $apiArguments += @('--env-file', '..\..\.env')
    }
    Start-Process -FilePath $pythonExe -ArgumentList $apiArguments -WorkingDirectory $backendDir `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cloudRuntime 'api.stdout.log') `
        -RedirectStandardError (Join-Path $cloudRuntime 'api.stderr.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $apiSchema = Get-MetaResponse "$apiUri/openapi.json"
    if (Test-MetaSchema $apiSchema) { break }
    Start-Sleep -Milliseconds 200
}
if (-not (Test-MetaSchema $apiSchema)) { throw 'MetaSense API did not become ready.' }
Register-MetaListener 'api' 'app.main:app' $apiPort

$bridgeUri = "http://127.0.0.1:$bridgePort"
$bridgeHealth = Get-MetaResponse "$bridgeUri/api/health" $bridgeHeaders
if (-not $bridgeHealth) {
    if (Get-MetaListeners $bridgePort) {
        throw 'Port 8005 is occupied by a service that does not accept MetaSense origin authentication.'
    }
    Start-Process -FilePath $pythonExe `
        -ArgumentList @('-m', 'uvicorn', 'cloud_bridge:app', '--host', '127.0.0.1', '--port', "$bridgePort") `
        -WorkingDirectory $backendDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $cloudRuntime 'bridge.stdout.log') `
        -RedirectStandardError (Join-Path $cloudRuntime 'bridge.stderr.log') | Out-Null
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $bridgeHealth = Get-MetaResponse "$bridgeUri/api/health" $bridgeHeaders
    if ($bridgeHealth) { break }
    Start-Sleep -Milliseconds 200
}
if (-not $bridgeHealth) { throw 'Authenticated MetaSense bridge did not become ready.' }
try {
    Invoke-WebRequest -Uri "$bridgeUri/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
    throw 'MetaSense bridge unexpectedly accepts unsigned requests.'
} catch {
    if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 403) { throw }
}
Register-MetaListener 'bridge' 'cloud_bridge:app' $bridgePort

$cloudflaredExe = (Get-Command cloudflared -ErrorAction Stop).Source
$tokenPattern = '(?:^|\s)--token-file\s+"' + [regex]::Escape($privateTokenPath) + '"(?:\s|$)'
$caseConnectors = @(Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" | Where-Object {
    $_.CommandLine -match $tokenPattern
})
if ($caseConnectors.Count -gt 1) { throw 'Multiple connectors use the private MetaSense token; no new connector was started.' }
if ($caseConnectors.Count -eq 1) {
    $connectorInfo = $caseConnectors[0]
    if ($connectorInfo.ExecutablePath -ne $cloudflaredExe -or $connectorInfo.CommandLine -notmatch '--protocol\s+quic(?:\s|$)') {
        throw 'The existing MetaSense connector has an unverified executable or protocol.'
    }
} else {
    if (Get-MetaListeners $metricsPort) { throw 'Reserved MetaSense tunnel metrics port 20252 is occupied.' }
    $tunnelArguments = @('--no-autoupdate', 'tunnel', '--protocol', 'quic', '--loglevel', 'warn',
        '--metrics', "127.0.0.1:$metricsPort", 'run', '--token-file', ('"' + $privateTokenPath + '"'))
    $connector = Start-Process -FilePath $cloudflaredExe -ArgumentList $tunnelArguments `
        -WorkingDirectory $caseRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $cloudRuntime 'tunnel.stdout.log') `
        -RedirectStandardError (Join-Path $cloudRuntime 'tunnel.stderr.log') -PassThru
    Start-Sleep -Milliseconds 500
    $processId = [int]$connector.Id
    $connectorInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if (-not $connectorInfo -or $connectorInfo.ExecutablePath -ne $cloudflaredExe -or
        $connectorInfo.CommandLine -notmatch $tokenPattern) {
        throw 'Private MetaSense connector did not start with its expected identity.'
    }
}
Save-MetaProcessRecord 'tunnel' $connectorInfo '' $metricsPort
Write-Output 'MetaSense API verified on 127.0.0.1:8001.'
Write-Output 'Protected MetaSense bridge verified on 127.0.0.1:8005; unsigned requests return 403.'
Write-Output 'Private QUIC connector verified. Website: https://metasense.santerihukari.com/'
