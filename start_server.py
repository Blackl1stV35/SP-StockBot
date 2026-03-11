#!/usr/bin/env python
"""Launch uvicorn server from correct directory."""
import os
import subprocess
import sys

# Change to SP-StockBot directory
os.chdir(r"D:\stock-monitor-line\SP-StockBot")

# Run uvicorn
subprocess.run([
    sys.executable, "-m", "uvicorn",
    "main:app",
    "--reload",
    "--host", "0.0.0.0",
    "--port", "8000"
], cwd=os.getcwd())
