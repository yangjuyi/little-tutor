@echo off
title little-tutor
cd /d "%~dp0"
rem 已有实例在跑：直接开浏览器，避免端口冲突
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null; exit 1 } catch { exit 0 }"
if %errorlevel%==1 (
  start "" http://127.0.0.1:8000/
  exit /b
)
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 40;$i++){try{$null=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop;break}catch{Start-Sleep -Milliseconds 500}};Start-Process 'http://127.0.0.1:8000/'"
.venv\Scripts\python.exe -m uvicorn app.web:app --host 127.0.0.1 --port 8000
