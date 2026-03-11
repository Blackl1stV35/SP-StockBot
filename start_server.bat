@echo off
cd /d D:\stock-monitor-line\SP-StockBot
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
