#!/usr/bin/env python
"""Launch uvicorn server from correct directory (no reload)."""
import os
import subprocess
import sys

os.chdir(r"D:\stock-monitor-line\SP-StockBot")
subprocess.run([
    sys.executable, "-m", "uvicorn",
    "main:app",
    "--host", "0.0.0.0",
    "--port", "8000"
], cwd=os.getcwd())
