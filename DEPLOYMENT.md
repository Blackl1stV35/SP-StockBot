# SP-StockBot: Quick Start Guide

## Installation (5 minutes)

### Windows

```bash
# 1. Run setup script (handles venv + pip install)
SETUP.bat

# or manually:
python -m venv venv
venv\Scripts\activate
pip install -r SP-StockBot/requirements.txt

# 2. Configure credentials
cd SP-StockBot
copy .env.example .env
# Edit .env with your credentials
```

### macOS/Linux

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r SP-StockBot/requirements.txt

# 2. Configure
cd SP-StockBot
cp .env.example .env
# Edit .env with your credentials
```

## Configuration (.env)

**Required:**
- `LINE_CHANNEL_SECRET`: From Line Console
- `LINE_CHANNEL_ACCESS_TOKEN`: From Line Console  
- `LINE_SUPER_ADMIN_ID`: Your Line User ID
- `SUPER_ADMIN_PIN`: 4-6 digits (e.g., `7482`)
- `GROQ_API_KEY`: From https://console.groq.com/keys

**Optional:**
- `GOOGLE_SERVICE_ACCOUNT_JSON`: Google Drive service account JSON
- `DATABASE_URL`: Default is `sqlite:///./stock_bot.db`

## Running the Bot

### Development (Local Testing)

```bash
# Activate venv first
venv\Scripts\activate

# Start bot
python SP-StockBot/main.py

# Output:
# ✓ Uvicorn running on http://0.0.0.0:8000
# ✓ SP-StockBot started successfully
```

### Production (with Gunicorn)

```bash
pip install gunicorn
gunicorn SP-StockBot.main:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile -
```

### Docker

```bash
docker build -t sp-stockbot:latest .
docker run -d \
  --name stockbot \
  -e LINE_CHANNEL_SECRET=... \
  -e LINE_CHANNEL_ACCESS_TOKEN=... \
  -e GROQ_API_KEY=... \
  -p 8000:8000 \
  sp-stockbot:latest
```

## Testing with ngrok (Local)

```bash
# Terminal 1: Start bot
python SP-StockBot/main.py

# Terminal 2: Start ngrok tunnel
ngrok http 8000

# Terminal 3: Get your URL and set in Line Console
# Copy: https://xxx.ngrok.io
# Go to: Line Channel → Messaging API → Webhook URL
# Set: https://xxx.ngrok.io/callback
```

## Verify Setup

```bash
# Check health endpoint
curl http://localhost:8000/health

# Should return:
# {"status":"ok","timestamp":"2025-03-03T...","memory_mb":...,"cpu_percent":...}
```

## Get Line Credentials

### 1. Line Channel Secret & Access Token

1. Visit: https://developers.line.biz/en/
2. Create New Channel (or use existing one)
3. Go to Settings → Channel access token → Generate
4. Copy to `.env`: `LINE_CHANNEL_ACCESS_TOKEN=...`
5. Go to Basic settings → Copy Channel Secret
6. Copy to `.env`: `LINE_CHANNEL_SECRET=...`

### 2. Get Your Line User ID

1. Add bot as a friend
2. Check bot's response logs or send a message
3. Bot logs will show your `user_id`
4. Copy to `.env`: `LINE_SUPER_ADMIN_ID=U...`

### 3. Groq API Key

1. Visit: https://console.groq.com
2. Sign up (free account)
3. Go to API Keys → Create New API Key
4. Copy to `.env`: `GROQ_API_KEY=gq_...`

## Set Line Webhook URL

After bot is running with ngrok or deployed:

1. Line Channel → Messaging API → Webhook URL
2. Set: `https://your-domain.com/callback`
3. Toggle "Use webhook" to ON
4. Save

## Create Database (Auto)

Database is created automatically on first run:
- Location: `stock_bot.db` (SQLite)
- Tables: `users`, `inventory`, `anomalies`, `groq_cache`

## Basic Commands (After Setup)

### Employee (to bot)
```
สตอก ทรายอ่อน
ใช้ ทรายอ่อน 5.5
สถานะ
ช่วย
```

### Admin (requires PIN at end)
```
Add user ไผท(โป๊น) PIN:7482
List users PIN:7482
System stats PIN:7482
Help PIN:7482
```

## Troubleshooting

### Bot not responding
- Check webhook URL in Line Console
- Verify `LINE_CHANNEL_ACCESS_TOKEN` is correct
- Check `logs/agent_activity.log` for errors

### "ModuleNotFoundError: No module named..."
- Make sure venv is activated: `source venv/bin/activate`
- Reinstall: `pip install -r requirements.txt`

### Groq API errors
- Verify `GROQ_API_KEY` is set and valid
- Check Groq console for quota/usage
- Logs show detailed error messages

### Excel parsing fails
- Check sheet name: must be `เดือน[M]-[YY]`
- Verify employee names in Excel match registered names
- Check log: `logs/agent_activity.log`

## Logs

All activity logged to `logs/agent_activity.log`:

```bash
# View recent logs
tail -f SP-StockBot/logs/agent_activity.log

# Find errors
grep "ERROR" SP-StockBot/logs/agent_activity.log
```

## Performance Monitor

Bot includes built-in health check:

```bash
curl http://localhost:8000/health

# Response includes:
# - Memory usage (MB)
# - CPU usage (%)
# - Timestamp
```

## Documentation

- **Full Docs**: See [README.md](README.md)
- **Architecture**: See SP-StockBot/*.py files
- **API Endpoints**: See main.py

## Support

1. Check logs first: `logs/agent_activity.log`
2. Verify .env configuration
3. Test health endpoint: `/health`
4. Review command syntax in README.md

## File Structure

```
d:\stock-monitor-line\
├── SETUP.bat                    (Quick setup script)
├── README.md                    (Full documentation)
├── DEPLOYMENT.md                (This file)
└── SP-StockBot/
    ├── main.py                  (FastAPI server)
    ├── config.py                (Configuration)
    ├── database.py              (SQLite)
    ├── logger.py                (Logging)
    ├── groq_agent.py            (LLM integration)
    ├── drive_handler.py         (Google Drive)
    ├── xlsx_parser.py           (Excel parsing)
    ├── anomaly_detector.py      (Statistics)
    ├── requirements.txt         (Dependencies)
    ├── .env.example             (Config template)
    ├── logs/                    (Activity logs)
    └── commands/
        ├── admin_commands.py
        └── employee_commands.py
```

---

**Version**: 1.0.0  
**Last Updated**: March 3, 2025  
**Status**: Production Ready ✓
