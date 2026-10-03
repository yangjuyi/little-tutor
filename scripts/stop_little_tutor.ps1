$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $root "outputs\runtime\little-tutor.pid"
$url = "http://127.0.0.1:8000/"

function Test-TutorHealth {
    try {
        $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $pidPath)) {
    if (Test-TutorHealth) {
        throw "little-tutor is responding, but its PID file is missing. Stop it manually before retrying."
    }
    Write-Host "little-tutor is not running."
    exit 0
}

$processId = 0
if (-not [int]::TryParse(
    (Get-Content -LiteralPath $pidPath -Raw).Trim(),
    [ref]$processId
)) {
    Remove-Item -LiteralPath $pidPath -Force
    throw "Invalid little-tutor PID file."
}

$processInfo = Get-CimInstance Win32_Process `
    -Filter "ProcessId = $processId" `
    -ErrorAction SilentlyContinue
if (-not $processInfo) {
    Remove-Item -LiteralPath $pidPath -Force
    if (Test-TutorHealth) {
        throw "The recorded process is gone, but port 8000 is still responding."
    }
    Write-Host "little-tutor is not running. Removed stale PID file."
    exit 0
}

$commandLine = [string]$processInfo.CommandLine
$underProject = $commandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0
$isUvicorn = $commandLine -match "uvicorn"
if (-not $underProject -or -not $isUvicorn) {
    throw "PID $processId does not match this little-tutor checkout; refusing to stop it."
}

Stop-Process -Id $processId -Force
Remove-Item -LiteralPath $pidPath -Force

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (-not (Test-TutorHealth)) {
        Write-Host "little-tutor stopped."
        exit 0
    }
}

throw "little-tutor process stopped, but port 8000 is still responding."
