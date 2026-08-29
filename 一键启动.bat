@echo off
title ArtiControlNet AIGC Workbench
cd /d "%~dp0"

echo ============================================================
echo   ArtiControlNet AIGC Workbench - One-click launcher
echo   Close this window to STOP the program
echo ============================================================
echo.

REM ---- First run: auto install dependencies ----
if not exist "%~dp0Server\.venv\Scripts\python.exe" (
    echo [setup] Creating Python venv and installing backend deps...
    cd /d "%~dp0Server"
    python -m venv .venv
    if errorlevel 1 echo [ERROR] Failed to create venv. Install Python 3.9+ and add it to PATH.
    if errorlevel 1 pause
    if errorlevel 1 exit /b 1
    call .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 echo [ERROR] Failed to install backend deps. Check your network.
    if errorlevel 1 pause
    if errorlevel 1 exit /b 1
    cd /d "%~dp0"
)

if not exist "%~dp0frontend\node_modules" (
    echo [setup] Installing frontend deps with npm...
    cd /d "%~dp0frontend"
    call npm install
    if errorlevel 1 echo [ERROR] Failed to install frontend deps. Check network / Node.js.
    if errorlevel 1 pause
    if errorlevel 1 exit /b 1
    cd /d "%~dp0"
)

REM ---- Port check ----
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Port 8000 is already in use. The program may already be running.
    echo Close the previous window, or kill the process using port 8000.
    pause
    exit /b 1
)

REM ---- Build frontend ----
echo [1/3] Building frontend (npm run build) ...
cd /d "%~dp0frontend"
call npm run build
if errorlevel 1 (
    echo [WARN] Frontend build failed. Starting with last build output. See errors above.
)
cd /d "%~dp0"

REM ---- Deploy to Server\static ----
echo [2/3] Deploying frontend to Server\static ...
robocopy "%~dp0frontend\dist" "%~dp0Server\static" /MIR /NFL /NDL /NJH /NJS /NP >nul

REM ---- Start backend (foreground, close window to stop) ----
echo [3/3] Starting backend at http://localhost:8000
echo.
echo Running... Close this window to stop.
echo.

if "%ARTN_SKIP_BROWSER%"=="" start /b powershell -NoProfile -Command "$ok=$false;for($i=0;$i -lt 120;$i++){try{if((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000 -TimeoutSec 1).StatusCode -eq 200){$ok=$true;break}}catch{};Start-Sleep -Milliseconds 500};Start-Process 'http://localhost:8000'"

cd /d "%~dp0Server"
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000

echo.
echo Server stopped.
pause
