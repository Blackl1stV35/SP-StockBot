#!/bin/bash
# SP-StockBot Local AI Launcher for Linux/macOS
# Activates venv, starts Ollama service, runs FastAPI server
# LOCAL SHIFT 2026-03-12

setterm() { echo -e "\033[$(($1))m"; }

echo ""
echo "================================================================================"
echo "   SP-StockBot Local AI Server Launcher"
echo "   Device: AMD Ryzen 5 5500U + GTX 1650 4GB + 8GB RAM"
echo "================================================================================"
echo ""

# Step 1: Activate virtual environment
echo "[1/4] Activating Python virtual environment..."

# Check for Windows 'Scripts' path inside the SP-StockBot directory
if [ ! -f "venv/Scripts/activate" ]; then
    # Fallback to check Linux/Mac 'bin' path just in case
    if [ ! -f "venv/bin/activate" ]; then
        echo "ERROR: venv not found in SP-StockBot directory."
        echo "Please run: cd SP-StockBot && python -m venv venv"
        exit 1
    else
        source venv/bin/activate
    fi
else
    source venv/Scripts/activate
fi

echo "OK: venv activated"
echo ""

# Step 2: Check Ollama
echo "[2/4] Checking Ollama service..."
if ! command -v ollama &> /dev/null; then
    echo "ERROR: Ollama not found or not in PATH"
    echo "Please install from: https://ollama.ai/download"
    exit 1
fi
ollama --version
echo "OK: Ollama available"
echo ""

# Step 3: Display setup instructions
echo "[3/4] Setup instructions:"
echo ""
echo "If this is your first run, execute these commands in separate terminals:"
echo ""
echo "   Terminal 1 (Ollama serve):"
echo "     ollama serve"
echo ""
echo "   Terminal 2 (This script):"
echo "     bash launch_local.sh"
echo ""
echo "   Terminal 3 (ngrok tunnel):"
echo "     ngrok http 8000"
echo "     Copy public URL and update Line Bot webhook at:"
echo "     https://developers.line.biz/console/"
echo ""
echo "================================================================================"
echo ""

# Step 4: Start FastAPI server
echo "[4/4] Starting FastAPI server on http://localhost:8000 ..."
echo ""
echo "Workers: 1 (optimized for 8GB RAM)"
echo "Reload: disabled (production mode)"
echo ""

cd SP-StockBot
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level info

# If uvicorn exits, show message
echo ""
echo "================================================================================"
echo "Server stopped. Check logs/agent_activity.log for details."
echo "================================================================================"
