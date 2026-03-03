@echo off
REM SP-StockBot Quick Setup Script for Windows
REM This script sets up the bot in a clean virtual environment

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║          SP-StockBot - Setup & Configuration             ║
echo ║    Internal Line Bot for Repair Shop Inventory           ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo ✗ Python not found. Please install Python 3.10.11 first.
    echo   https://www.python.org/downloads/
    exit /b 1
)

echo ✓ Python found

REM Create virtual environment
if not exist venv (
    echo.
    echo Setting up virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ✗ Failed to create virtual environment
        exit /b 1
    )
    echo ✓ Virtual environment created
) else (
    echo ✓ Virtual environment already exists
)

REM Activate venv
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ✗ Failed to activate virtual environment
    exit /b 1
)

REM Upgrade pip
echo.
echo Installing dependencies...
python -m pip install --upgrade pip setuptools wheel >nul 2>&1
if errorlevel 1 (
    echo ✗ Failed to upgrade pip
    exit /b 1
)

REM Install requirements
cd SP-StockBot
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ✗ Installation failed. Check log above for details.
    exit /b 1
)
cd ..

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║        ✓ Installation Complete!                          ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo Next steps:
echo   1. Copy SP-StockBot\.env.example to SP-StockBot\.env
echo   2. Edit SP-StockBot\.env with your credentials:
echo      - LINE_CHANNEL_SECRET (from Line Console)
echo      - LINE_CHANNEL_ACCESS_TOKEN (from Line Console)
echo      - LINE_SUPER_ADMIN_ID (your Line User ID)
echo      - SUPER_ADMIN_PIN (4-6 digits, e.g., 7482)
echo      - GROQ_API_KEY (from https://console.groq.com)
echo.
echo   3. (Optional) Set up Google Drive integration:
echo      - Create service account in Google Cloud Console
echo      - Download JSON key file
echo      - Set GOOGLE_SERVICE_ACCOUNT_JSON in .env
echo.
echo   4. Run the bot:
echo      python SP-StockBot\main.py
echo.
echo   5. Configure Line Webhook:
echo      - Channel → Messaging API → Webhook URL
echo      - Set to: https://your-domain.com/callback
echo.
echo For local testing with ngrok:
echo   - ngrok http 8000
echo   - Copy URL and add /callback endpoint
echo.
echo Documentation: See README.md
echo.
pause
