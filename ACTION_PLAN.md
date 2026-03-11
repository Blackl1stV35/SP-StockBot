## SP-StockBot Fix Action Plan - March 5, 2026

### ⚠️ CRITICAL BLOCKER: Invalid Groq API Key

The bot cannot classify intents until this is fixed.

---

## IMMEDIATE ACTION REQUIRED

### Step 1: Get a New Groq API Key (5 minutes)

1. Open: https://console.groq.com/keys
2. Sign in (or create account)
3. Click **Create API Key** (or **Create New Key**)
4. Copy the key (should look like: `gq_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)
5. Go to: `SP-StockBot/.env`
6. Replace the GROQ_API_KEY line:
   ```
   GROQ_API_KEY=gq_YOUR_NEW_KEY_HERE
   ```
7. Save the file

### Step 2: Verify the Key Works (2 minutes)

Run the diagnostic:
```bash
cd d:\stock-monitor-line
python check_groq_setup.py
```

Expected output:
```
[OK] GROQ_API_KEY is set
[OK] Groq API is working!
[SUCCESS] All checks passed!
```

If you see `[OK] Key doesn't start with 'gq_'` warning, try:
- Check that you copied the entire key
- Make sure you're using the NEWEST key from console.groq.com
- Old keys starting with `gsk_` don't work anymore

### Step 3: Restart Bot

```bash
cd d:\stock-monitor-line
python SP-StockBot/main.py
```

Or for development:
```bash
uvicorn SP-StockBot.main:app --reload
```

---

## OPTIONAL: Enable Google Drive File Scanning (5 minutes)

After Groq works, the bot can auto-detect inventory files:

1. Go to: https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project=739402046175
2. Click **Enable**
3. Wait 30 seconds for activation
4. Bot will now scan Drive every 15 minutes

---

## TESTING AFTER GROQ KEY IS FIXED

### Test 1: Send "Help" Command
```
User sends: "Help" or "ช่วย"
Bot replies: Show help menu ✓
```

### Test 2: Send "Get Stock"
```
User sends: "Check sandpaper" or "สตอก ทรายอ่อน"
Bot replies: Material stock info ✓
```

### Test 3: Set Google Drive Folder
```
User sends: Set drive https://drive.google.com/drive/folders/1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2 PIN:7482
Bot replies: ✓ Drive folder SAVED (to DB)
```

Wait 10 seconds, restart bot → Check logs:
```
Expected: "Loaded GOOGLE_DRIVE_FOLDER_ID from DB:" ✓
```

### Test 4: Random Message
```
User sends: "Random gibberish text xyz abc"
Bot replies: (nothing - silent ignore) ✓
```

### Test 5: Admin Stats
```
User sends: System stats PIN:7482
Bot replies: System statistics ✓
```

### Test 6: Drive Scan (if Google Drive API enabled)
```
Wait 15 minutes for background scan
Check logs for: "[Drive Scan] Found file:"
You should see the XLSX file from your Drive folder ✓
```

---

## WHAT WAS FIXED

### ✓ Groq API Debugging
- Added comprehensive logging to see exactly what's happening
- Can now diagnose authentication issues
- Shows response content and error details

### ✓ "Set Drive" Command Now Persists
- Folder ID saved to database
- Survives bot restarts
- Loads automatically on startup

### ✓ Intent Classification Errors Handled Gracefully
- Unclassified messages don't show errors
- Silent ignore unless classification succeeds
- Reduces spam for unclear inputs

### ✓ Drive Scanning More Robust
- Better logging of queries and results
- Shows exact folder ID being checked
- Clearer error messages if Drive API not enabled

---

## TROUBLESHOOTING

### Problem: "Invalid API Key" 401 Error
**Fix**: Get a NEW key from https://console.groq.com/keys
- Old keys starting with `gsk_` don't work
- New keys start with `gq_`

### Problem: "403 accessNotConfigured" when Drive scans
**Fix**: Enable Google Drive API at the link above

### Problem: "Help menu appears for every message"
**Fix**: Already fixed! Random messages now silently ignored

### Problem: "Set drive command doesn't save"
**Fix**: Already fixed! Now saves to database and persists

### Problem: Messages aren't being classified at all
**Fix**: Check Groq API key - run `python check_groq_setup.py`

---

## FILES CHANGED

| File | Change |
|------|--------|
| `groq_agent.py` | Enhanced debug logging, better errors |
| `database.py` | Added settings table + CRUD methods |
| `admin_commands.py` | Save folder ID to DB, better parsing |
| `main.py` | Load folder ID from DB on startup, fix intent errors |
| `drive_handler.py` | Better logging of Drive queries |
| `check_groq_setup.py` | NEW - Diagnostic tool |
| `FIXES_MARCH_5.md` | Detailed change documentation |

---

## WHAT TO DO NOW

1. **[5 min]** Get new Groq API key from https://console.groq.com/keys
2. **[2 min]** Update `.env` with new key
3. **[2 min]** Run diagnostic: `python check_groq_setup.py`
4. **[1 min]** Restart bot
5. **[5 min]** Test commands above
6. **[5 min]** (Optional) Enable Drive API & wait for scan

---

## EXPECTED BOTBEHAVIOR AFTER FIXES

- ✓ Intent classification works (requires valid Groq key)
- ✓ Help commands return help menu
- ✓ "Set drive" saves folder ID permanently
- ✓ Random messages silently ignored (no error reply)
- ✓ Drive scan finds XLSX files (if API enabled)
- ✓ All logging clear and detailed

---

**Start with: Get new Groq API key from https://console.groq.com/keys**

Questions? Check logs in `./logs/agent_activity.log`
