@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="--no-browser" set "TUTOR_NO_BROWSER=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=(Get-Location).Path; $python=Join-Path $root '.venv\Scripts\pythonw.exe'; $runtime=Join-Path $root 'outputs\runtime'; $pidPath=Join-Path $runtime 'little-tutor.pid'; $outLog=Join-Path $runtime 'uvicorn.out.log'; $errLog=Join-Path $runtime 'uvicorn.err.log'; $url='http://127.0.0.1:8000/'; function Test-Health { try { $null=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1; return $true } catch { return $false } }; if (-not (Test-Path -LiteralPath $python)) { throw ('Python environment not found: ' + $python) }; if (Test-Health) { Write-Host ('little-tutor is already running: ' + $url); if (-not $env:TUTOR_NO_BROWSER) { Start-Process $url }; exit 0 }; $listener=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if ($listener) { throw ('Port 8000 is occupied by PID ' + $listener.OwningProcess) }; New-Item -ItemType Directory -Force -Path $runtime | Out-Null; $process=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.web:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $root -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru; Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ascii; $ready=$false; for ($i=0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; if (Test-Health) { $ready=$true; break }; if ($process.HasExited) { break } }; if (-not $ready) { if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }; throw ('little-tutor did not become ready. Check ' + $errLog) }; Write-Host ('little-tutor started: ' + $url); Write-Host ('PID: ' + $process.Id); Write-Host ('Logs: ' + $runtime); if (-not $env:TUTOR_NO_BROWSER) { Start-Process $url }"

if errorlevel 1 (
  echo.
  echo little-tutor failed to start.
  pause
)
endlocal
