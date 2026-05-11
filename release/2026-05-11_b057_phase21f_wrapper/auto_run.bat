@echo off
REM ============================================================
REM bizplnner daily wrapper - proxy auto-start + run_all + sync + ALERT
REM Backlog 036 (2026-05-08): 5/2-5/7 stale = jbexport proxy down.
REM Backlog 042 (2026-05-08): silent fail prevention - alert on non-zero exit.
REM Backlog 057 (2026-05-11): Phase 2.1f - opt-in Render sync step.
REM Action: check proxy, auto-start if dead, run run_all.py, cleanup, sync, alert.
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
REM proxy startup timeout still triggers alert (5/2-5/7 chain prevention)
py scripts\send_alert.py --exit-code 2 --log "%LOG%" --tail-lines 50 >> "%LOG%" 2>&1
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

REM 5) Sync to Render (Backlog 057 Phase 2.1f) - opt-in via ENABLE_RENDER_SYNC env var.
REM   Activated only after Phase 2.1e Render deploy completes. Default: OFF (silent skip).
REM   Activation: set ENABLE_RENDER_SYNC=1 (system env var, persists across sessions).
REM   sync_to_render reads WHERE synced_to_render=0 from local DB, POSTs /api/sync,
REM   marks flag=1 on success. Failure = log only (no alert, retry next day per idempotency).
if defined ENABLE_RENDER_SYNC (
    if !RUN_ALL_EXIT! EQU 0 (
        echo [auto_run] sync_to_render start
        echo [auto_run] %DATE% %TIME% sync_to_render start >> "%LOG%"
        py pipeline\sync_to_render.py >> "%LOG%" 2>&1
        set "SYNC_EXIT=!ERRORLEVEL!"
        echo [auto_run] %DATE% %TIME% sync_to_render exit=!SYNC_EXIT! >> "%LOG%"
    ) else (
        echo [auto_run] sync_to_render skipped run_all_exit=!RUN_ALL_EXIT!
        echo [auto_run] %DATE% %TIME% sync_to_render skipped run_all_exit=!RUN_ALL_EXIT! >> "%LOG%"
    )
)

REM 6) Send alert email if run_all failed (silent fail prevention - backlog 042)
if !RUN_ALL_EXIT! NEQ 0 (
    echo [auto_run] sending alert for exit=!RUN_ALL_EXIT!
    echo [auto_run] %DATE% %TIME% alert exit=!RUN_ALL_EXIT! >> "%LOG%"
    py scripts\send_alert.py --exit-code !RUN_ALL_EXIT! --log "%LOG%" --tail-lines 50 >> "%LOG%" 2>&1
)

exit /b !RUN_ALL_EXIT!
