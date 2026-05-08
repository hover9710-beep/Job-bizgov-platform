@echo off
REM ============================================================
REM bizplnner daily wrapper - proxy auto-start + run_all.py
REM Backlog 036 (2026-05-08): 5/2-5/7 stale = jbexport proxy down.
REM Action: check proxy, auto-start if dead, run run_all.py, cleanup.
REM bizplnner Task Action: cmd /c auto_run.bat
REM ASCII-only. Path via %~dp0 (Start In = bat dir, no hardcoded korean).
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PROXY_URL=http://127.0.0.1:5001"
set "PROXY_PORT=5001"
set "PROXY_STARTED=0"
set "LOG=logs\auto_run.log"

if not exist logs mkdir logs

REM 1) Check proxy alive (curl HTTP code)
curl -s -o NUL -w "%%{http_code}" %PROXY_URL% > "%TEMP%\proxy_status.txt" 2>NUL
set /p PROXY_STATUS=<"%TEMP%\proxy_status.txt"
if "!PROXY_STATUS!"=="200" goto proxy_ready
if "!PROXY_STATUS!"=="405" goto proxy_ready

REM 2) Dead - start in minimized window, wait up to 30s
echo [auto_run] proxy not responding (status=!PROXY_STATUS!), starting...
echo [auto_run] %DATE% %TIME% proxy start >> "%LOG%"
start "jbexport_proxy" /min py connectors\connectors_jbexport\jbexport_proxy.py
set "PROXY_STARTED=1"

for /L %%i in (1,1,30) do (
    timeout /t 1 /nobreak >NUL
    curl -s -o NUL -w "%%{http_code}" %PROXY_URL% > "%TEMP%\proxy_status.txt" 2>NUL
    set /p PROXY_STATUS=<"%TEMP%\proxy_status.txt"
    if "!PROXY_STATUS!"=="200" goto proxy_ready
    if "!PROXY_STATUS!"=="405" goto proxy_ready
)

echo [auto_run] proxy failed to start in 30s
echo [auto_run] %DATE% %TIME% proxy startup TIMEOUT exit 2 >> "%LOG%"
exit /b 2

:proxy_ready
echo [auto_run] proxy ready: !PROXY_STATUS! (started_by_us=!PROXY_STARTED!)
echo [auto_run] %DATE% %TIME% proxy ready status=!PROXY_STATUS! started=!PROXY_STARTED! >> "%LOG%"

REM 3) Run run_all.py
py run_all.py >> "%LOG%" 2>&1
set "RUN_ALL_EXIT=!ERRORLEVEL!"
echo [auto_run] %DATE% %TIME% run_all exit=!RUN_ALL_EXIT! >> "%LOG%"

REM 4) Cleanup proxy started by us only (preserve user-started proxy)
if "!PROXY_STARTED!"=="1" (
    echo [auto_run] cleaning up proxy started by us
    taskkill /F /FI "WINDOWTITLE eq jbexport_proxy*" >NUL 2>&1
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%PROXY_PORT% ^| findstr LISTENING') do (
        taskkill /F /PID %%a >NUL 2>&1
    )
    echo [auto_run] %DATE% %TIME% proxy cleanup done >> "%LOG%"
)

exit /b !RUN_ALL_EXIT!
