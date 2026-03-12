@echo off
REM SP-StockBot Local AI Launcher for Windows
REM Activates venv, starts Ollama service, runs FastAPI server
REM LOCAL SHIFT 2026-03-12

setlocal enabledelayedexpansion

echo.
echo ================================================================================
echo   SP-StockBot Local AI Server Launcher
echo   Device: AMD Ryzen 5 5500U + GTX 1650 4GB + 8GB RAM
echo ================================================================================
echo.

REM Step 1: Activate virtual environment
echo [1/4] Activating Python virtual environment...
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: venv not found. Run: python -m venv venv
    exit /b 1
)
call venv\Scripts\activate.bat
echo OK: venv activated
echo.

REM Step 2: Check Ollama
echo [2/4] Checking Ollama service...
ollama --version > nul 2>&1
if errorlevel 1 (
    echo ERROR: Ollama not found or not in PATH
    echo Please install from: https://ollama.ai/download/windows
    exit /b 1
)
echo OK: Ollama available
echo.

REM Step 3: Display setup instructions
echo [3/4] Setup instructions:
echo.
echo If this is your first run, execute these commands in separate terminals:
echo.
echo   Terminal 1 (Ollama - if not already running as service):
echo     ollama serve
echo.
echo   Terminal 2 (This window):
echo     This script will auto-start the bot
echo.
echo   Terminal 3 (ngrok tunnel):
echo     ngrok http 8000
echo     Copy the public URL and update Line Bot webhook at:
echo     https://developers.line.biz/console/
echo.
echo ================================================================================
echo.

REM Step 4: Start FastAPI server
echo [4/4] Starting FastAPI server on http://localhost:8000 ...
echo.
echo Workers: 1 (optimized for 8GB RAM)
echo Reload: disabled (production mode)
echo.
cd SP-StockBot
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info

REM If uvicorn exits, show message
echo.
echo ================================================================================
echo Server stopped. Check logs/agent_activity.log for details.
echo ================================================================================
pause
