"""
SP-StockBot Main Application
FastAPI webhook for Line Bot + Background task scheduler.
Optimized for 8GB RAM, CPU-only (no local GPU).
"""

import gc
import logging
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

# Line Bot SDK v3
from linebot.v3.messaging import MessagingApi, ApiClient, TextMessage
from linebot.v3.webhook import WebhookHandler, MessageEvent
from linebot.v3.exceptions import InvalidSignatureError

from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from database import Database
from groq_agent import GroqAgent
from drive_handler import DriveHandler
from xlsx_parser import XlsxParser
from anomaly_detector import AnomalyDetector
from logger import activity_logger
from commands.admin_commands import AdminCommands
from commands.employee_commands import EmployeeCommands

# Background scheduler (initialized before app for use in lifespan)
scheduler = BackgroundScheduler()


# Lifespan context manager for FastAPI startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events with asynccontextmanager."""
    # ==================== STARTUP ====================
    try:
        # Run startup validation first
        if not validate_startup():
            activity_logger.log_error(
                "Startup validation failed. Server cannot start.",
                error_type="startup_validation_error",
            )
            sys.exit(1)

        # Initialize components
        get_db()
        get_groq_agent()
        get_admin_commands()
        get_employee_commands()
        get_drive_handler()

        # Start scheduler
        if not scheduler.running:
            scheduler.add_job(
                daily_anomaly_check,
                "cron",
                hour=8,
                minute=0,
                id="daily_anomaly_check",
            )
            scheduler.add_job(
                memory_cleanup,
                "interval",
                minutes=30,
                id="memory_cleanup",
            )
            scheduler.add_job(
                check_drive_for_new_files,
                "interval",
                minutes=15,
                id="check_drive_files",
            )
            scheduler.start()

        activity_logger.logger.info("✓ SP-StockBot started successfully")

    except Exception as e:
        activity_logger.log_error(
            f"Startup error: {e}",
            error_type="startup_error",
        )
        sys.exit(1)

    # Server is running - yield control back to FastAPI
    yield

    # ==================== SHUTDOWN ====================
    try:
        if scheduler.running:
            scheduler.shutdown()

        db_instance = get_db()
        if db_instance:
            db_instance.close()

        gc.collect()
        activity_logger.logger.info("✓ SP-StockBot shutdown gracefully")

    except Exception as e:
        activity_logger.log_error(
            f"Shutdown error: {e}",
            error_type="shutdown_error",
        )


# Initialize FastAPI app
app = FastAPI(
    title="SP-StockBot",
    description="Internal Line Bot for Automobile Repair Shop Inventory",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Line Bot SDK v3
api_client = ApiClient(access_token=Config.LINE_CHANNEL_ACCESS_TOKEN)
messaging_api = MessagingApi(api_client)
webhook_handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)

# Initialize components (lazy loaded)
db: Optional[Database] = None
groq_agent: Optional[GroqAgent] = None
drive_handler: Optional[DriveHandler] = None
xlsx_parser: Optional[XlsxParser] = None
anomaly_detector: Optional[AnomalyDetector] = None
admin_commands: Optional[AdminCommands] = None
employee_commands: Optional[EmployeeCommands] = None


def get_db() -> Database:
    """Get or initialize database instance."""
    global db
    if db is None:
        db = Database()
    return db


def get_groq_agent() -> GroqAgent:
    """Get or initialize Groq agent."""
    global groq_agent
    if groq_agent is None:
        groq_agent = GroqAgent(get_db())
    return groq_agent


def get_drive_handler() -> DriveHandler:
    """Get or initialize Drive handler."""
    global drive_handler
    if drive_handler is None:
        try:
            drive_handler = DriveHandler()
        except Exception as e:
            activity_logger.log_error(
                f"Failed to initialize Drive handler: {e}",
                error_type="drive_init_error",
            )
            drive_handler = None
    return drive_handler


def get_xlsx_parser() -> XlsxParser:
    """Get or initialize XLSX parser."""
    global xlsx_parser
    if xlsx_parser is None:
        xlsx_parser = XlsxParser(get_db())
    return xlsx_parser


def get_anomaly_detector() -> AnomalyDetector:
    """Get or initialize anomaly detector."""
    global anomaly_detector
    if anomaly_detector is None:
        anomaly_detector = AnomalyDetector(get_db())
    return anomaly_detector


def get_admin_commands() -> AdminCommands:
    """Get or initialize admin commands handler."""
    global admin_commands
    if admin_commands is None:
        admin_commands = AdminCommands(get_db(), get_groq_agent())
    return admin_commands


def get_employee_commands() -> EmployeeCommands:
    """Get or initialize employee commands handler."""
    global employee_commands
    if employee_commands is None:
        employee_commands = EmployeeCommands(get_db())
    return employee_commands


# Background tasks
def daily_anomaly_check():
    """Run daily anomaly detection and notify admin."""
    try:
        activity_logger.logger.info("▶ Starting daily anomaly check...")
        detector = get_anomaly_detector()
        db_instance = get_db()
        agent = get_groq_agent()

        # Run batch anomaly detection
        anomalies = detector.detect_batch()
        unnotified = [a for a in anomalies if not a.get("notified", False)]

        if unnotified:
            # Generate summary
            summary = agent.generate_daily_summary(unnotified)

            # Mark as notified
            for anom in unnotified:
                db_instance.mark_anomaly_notified(anom.get("id"))

            # Send to super admin
            try:
                message = TextMessage(
                    text=f"📋 Daily Anomaly Report:\n\n{summary}"
                )
                messaging_api.push_message(
                    Config.LINE_SUPER_ADMIN_ID, {"messages": [message.as_json_dict()]}
                )
                activity_logger.logger.info(
                    f"✓ Sent anomaly report to admin: {len(unnotified)} anomalies"
                )
            except Exception as e:
                activity_logger.log_error(
                    f"Failed to send anomaly report: {e}",
                    error_type="anomaly_push_error",
                )

        else:
            activity_logger.logger.info("✓ No new anomalies detected")

    except Exception as e:
        activity_logger.log_error(
            f"Error in daily anomaly check: {e}",
            error_type="scheduler_error",
        )


def memory_cleanup():
    """Periodic garbage collection and memory cleanup."""
    try:
        gc.collect()
        process = psutil.Process()
        mem_info = process.memory_info()
        activity_logger.logger.debug(
            f"Memory cleanup: {mem_info.rss / 1024 / 1024:.1f}MB RSS"
        )
    except Exception as e:
        activity_logger.logger.warning(f"Memory cleanup error: {e}")


def check_drive_for_new_files():
    """Check Drive for new inventory files and parse them."""
    try:
        activity_logger.logger.info("▶ Checking Drive for new files...")

        if not Config.GOOGLE_DRIVE_FOLDER_ID:
            activity_logger.logger.warning(
                "GOOGLE_DRIVE_FOLDER_ID not configured"
            )
            return

        drive = get_drive_handler()
        if not drive:
            return

        # Find latest XLSX file
        latest_file = drive.find_latest_xlsx(Config.GOOGLE_DRIVE_FOLDER_ID)

        if not latest_file:
            activity_logger.logger.info("No XLSX files found in Drive")
            return

        file_id = latest_file.get("id")
        file_name = latest_file.get("name")

        # Check if we've already processed this file
        db_instance = get_db()
        processed = db_instance.get_processed_file(file_id)
        if processed:
            activity_logger.logger.info(
                f"File {file_name} already processed"
            )
            return

        # Download and parse
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp_path = tmp.name

        success = drive.download_file(file_id, tmp_path)
        if not success:
            activity_logger.logger.error(f"Failed to download {file_name}")
            return

        parser = get_xlsx_parser()
        result = parser.parse_file(tmp_path)

        # Mark file as processed
        db_instance.mark_file_processed(
            file_id=file_id,
            file_name=file_name,
            records_count=result.get("records_added") + result.get(
                "records_updated"
            ),
        )

        # Notify admin
        reply = (
            f"✓ Processed inventory file: {file_name}\n"
            f"Sheets: {result['sheets_processed']}\n"
            f"Records added: {result['records_added']}\n"
            f"Records updated: {result['records_updated']}\n"
        )

        if result["errors"]:
            reply += f"Errors: {len(result['errors'])}\n"

        message = TextMessage(text=reply)
        messaging_api.push_message(Config.LINE_SUPER_ADMIN_ID, {"messages": [message.as_json_dict()]})

        activity_logger.logger.info(f"✓ Processed {file_name}")

        # Clean up
        import os
        try:
            os.remove(tmp_path)
        except:
            pass

    except Exception as e:
        activity_logger.log_error(
            f"Error checking Drive files: {e}",
            error_type="drive_check_error",
        )


def validate_startup() -> bool:
    """
    Validate all dependencies before startup.
    Returns True if all checks pass, False otherwise.
    """
    from pathlib import Path
    
    print("\n" + "=" * 60)
    print("[STARTUP] SP-StockBot Startup Validation")
    print("=" * 60)

    checks_passed = 0
    checks_failed = 0

    # 0. Check Python version
    print("\n[0/7] Checking Python version...")
    py_version = sys.version_info
    print(f"  Running on Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    activity_logger.logger.info(f"Python version: {sys.version}")
    if py_version.major >= 3 and py_version.minor >= 10:
        print("  OK Python 3.10+ ✓")
        checks_passed += 1
    else:
        print(f"  FAIL Python 3.10+ required, got {py_version.major}.{py_version.minor}")
        checks_failed += 1

    # 0.5. Check service account file
    print("\n[0.5/7] Checking Google service account file...")
    candidate_paths = [
        Path("./nth-station-489109-s1-6c5ccb8ccef4.json"),
        Path("./SP-StockBot/nth-station-489109-s1-6c5ccb8ccef4.json"),
    ]
    service_account_found = False
    for path in candidate_paths:
        if path.exists():
            print(f"  OK Found service account at {path.resolve()} ✓")
            activity_logger.logger.info(f"Service account detected: {path.resolve()}")
            service_account_found = True
            checks_passed += 1
            break
    if not service_account_found:
        print("  SKIP Service account not found (Drive will be unavailable)")

    # 1. Check imports
    print("\n[1/7] Checking critical imports...")
    try:
        import fastapi
        print("  OK fastapi")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL fastapi: {e}")
        checks_failed += 1

    try:
        import linebot
        print("  OK line-bot-sdk")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL line-bot-sdk: {e}")
        checks_failed += 1

    try:
        import groq
        print("  OK groq")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL groq: {e}")
        checks_failed += 1

    try:
        import googleapiclient.discovery
        print("  OK googleapiclient")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL googleapiclient: {e}")
        print(f"    -> Suggestion: pip install google-api-python-client>=2.100")
        checks_failed += 1

    try:
        import google.oauth2.service_account
        print("  OK google-auth")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL google-auth: {e}")
        checks_failed += 1

    try:
        import pandas
        print("  OK pandas")
        checks_passed += 1
    except ImportError as e:
        print(f"  FAIL pandas: {e}")
        checks_failed += 1

    # 2. Check configuration
    print("\n[2/7] Checking configuration...")
    config_errors = Config.validate()
    if config_errors:
        print("  FAIL Configuration validation failed:")
        for error in config_errors:
            print(f"    -> {error}")
        checks_failed += len(config_errors)
    else:
        print("  OK All required config keys set")
        checks_passed += 1

    # 3. Check database
    print("\n[3/7] Checking database...")
    try:
        test_db = Database()
        # Try to create a test table
        test_db.get_all_users()
        print("  OK SQLite database connected")
        checks_passed += 1
    except Exception as e:
        print(f"  FAIL Database error: {e}")
        checks_failed += 1

    # 4. Check Groq client
    print("\n[4/7] Checking Groq API client...")
    try:
        test_groq = GroqAgent(test_db)
        print(f"  OK Groq client initialized (model: {Config.GROQ_MODEL})")
        checks_passed += 1
    except Exception as e:
        print(f"  WARN Groq client warning: {e}")
        print(f"    -> This will be retried at startup")

    # 5. Check Line Bot handler
    print("\n[5/7] Checking Line Bot configuration...")
    try:
        assert Config.LINE_CHANNEL_SECRET, "LINE_CHANNEL_SECRET not set"
        assert Config.LINE_CHANNEL_ACCESS_TOKEN, "LINE_CHANNEL_ACCESS_TOKEN not set"
        # Verify API client initialization
        _ = MessagingApi(ApiClient(access_token=Config.LINE_CHANNEL_ACCESS_TOKEN))
        print("  OK Line Bot SDK v3 handler configured")
        checks_passed += 1
    except AssertionError as e:
        print(f"  FAIL Line Bot config: {e}")
        checks_failed += 1

    # 6. Check Drive service (optional)
    print("\n[6/7] Checking Google Drive service...")
    try:
        if Config.GOOGLE_DRIVE_FOLDER_ID or Config.GOOGLE_SERVICE_ACCOUNT_JSON:
            test_drive = DriveHandler()
            print("  OK Google Drive service initialized")
            checks_passed += 1
        else:
            print("  SKIP Drive integration not configured (optional)")
    except Exception as e:
        print(f"  WARN Drive service warning: {e}")
        print("    -> (Drive features will be disabled, but bot will continue)")

    # Summary
    print("\n" + "=" * 60)
    print(f"  PASS: {checks_passed}")
    print(f"  FAIL: {checks_failed}")
    print("=" * 60)

    if checks_failed == 0:
        print("SUCCESS: STARTUP VALIDATION PASSED - Ready to start!")
        print("=" * 60 + "\n")
        return True
    else:
        print("FAILED: STARTUP VALIDATION FAILED - Fix errors above before starting")
        print("=" * 60 + "\n")
        return False


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    try:
        process = psutil.Process()
        mem_info = process.memory_info()

        return ORJSONResponse({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "memory_mb": mem_info.rss / 1024 / 1024,
            "cpu_percent": process.cpu_percent(interval=0.1),
        })
    except Exception as e:
        return ORJSONResponse(
            {"status": "error", "error": str(e)},
            status_code=500,
        )


# Line webhook callback
@app.post("/callback", tags=["Line Bot"])
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Line Bot webhook endpoint.
    Handles all incoming Line messages.
    """
    signature = request.headers.get("X-Line-Signature", "")

    try:
        body = await request.body()

        # Verify signature
        try:
            webhook_handler.handle(body.decode("utf-8"), signature)
        except InvalidSignatureError:
            activity_logger.log_error(
                "Invalid Line signature",
                error_type="line_signature_error",
            )
            raise HTTPException(status_code=401, detail="Unauthorized")

        return ORJSONResponse({"status": "ok"})

    except Exception as e:
        activity_logger.log_error(
            f"Webhook error: {e}",
            error_type="webhook_error",
        )
        raise HTTPException(status_code=500, detail="Internal error")


@webhook_handler.add(MessageEvent, message=TextMessage)
def handle_message(event: MessageEvent):
    """Handle text message from Line."""
    try:
        # Type check for text messages
        if not isinstance(event.message, TextMessage):
            return
        
        user_id = event.source.user_id
        user_message = event.message.text.strip()

        # Log incoming message
        activity_logger.log_message_received(
            user_id=user_id,
            raw_message=user_message,
        )

        # Initialize components
        db_instance = get_db()
        agent = get_groq_agent()
        admin_cmd = get_admin_commands()
        emp_cmd = get_employee_commands()

        # Check if user exists and get role
        user = db_instance.get_user(user_id)
        is_admin = user is not None and user.get("role") == "super_admin"
        is_registered = user is not None

        # If not registered, offer to register
        if not is_registered:
            reply_text = (
                "👋 Welcome to SP-StockBot!\n\n"
                "Please ask the admin to add you to the system.\n"
                "Admin: Use 'Add user [name] PIN:[code]' to register employees."
            )
            messaging_api.reply_message(
                event.reply_token,
                {"messages": [{"type": "text", "text": reply_text}]},
            )
            return

        # Classify intent using Groq
        intent_result = agent.classify_intent(
            user_message=user_message,
            user_name=user.get("display_name", "User"),
            is_admin=is_admin,
        )

        intent = intent_result.get("intent", "other")
        requires_pin = intent_result.get("requires_pin", False)
        reply_text = intent_result.get("reply_text", "")

        # Route to appropriate handler
        if intent == "admin_command" or (is_admin and intent != "help"):
            # Admin command - check PIN first
            provided_pin = agent.extract_pin_from_message(user_message)

            if requires_pin and not provided_pin:
                reply_text = (
                    "🔐 PIN required for this command.\n"
                    "Usage: [command] PIN:xxxx"
                )
                messaging_api.reply_message(
                    event.reply_token,
                    {"messages": [{"type": "text", "text": reply_text}]},
                )
                return

            if provided_pin and not agent.verify_pin(
                provided_pin, Config.SUPER_ADMIN_PIN
            ):
                reply_text = "❌ PIN incorrect. Command rejected."
                messaging_api.reply_message(
                    event.reply_token,
                    {"messages": [{"type": "text", "text": reply_text}]},
                )
                activity_logger.log_admin_action(
                    admin_line_id=user_id,
                    action="pin_attempt",
                    pin_verified=False,
                )
                return

            # Extract command details
            cmd_name, params = admin_cmd.extract_command_details(
                user_message
            )

            if cmd_name == "add_user":
                display_name = params.get("display_name", "")
                success, msg = admin_cmd.add_user(
                    display_name=display_name,
                    excel_name=params.get("excel_name", display_name),
                    role="employee",
                )
                reply_text = msg

            elif cmd_name == "list_users":
                reply_text = admin_cmd.list_users(
                    role=params.get("role")
                )

            elif cmd_name == "delete_user":
                user_id_del = params.get("user_id", "")
                success, msg = admin_cmd.delete_user(user_id_del)
                reply_text = msg

            elif cmd_name == "set_drive":
                folder_id = params.get("drive_folder_id", "")
                success, msg = admin_cmd.set_drive_folder(folder_id)
                reply_text = msg

            elif cmd_name == "help":
                reply_text = admin_cmd.get_help_text(is_admin=True)

            else:
                reply_text = admin_cmd.get_help_text(is_admin=True)

            activity_logger.log_admin_action(
                admin_line_id=user_id,
                action=cmd_name or "unknown",
                pin_verified=bool(provided_pin),
                success=True,
            )

        elif intent == "check_stock":
            material = intent_result.get("parameters", {}).get("material", "")
            reply_text = emp_cmd.check_inventory(user_id, material)

        elif intent == "report_usage":
            material = intent_result.get("parameters", {}).get("material", "")
            qty = intent_result.get("parameters", {}).get("quantity", 0)
            if material and qty:
                reply_text = emp_cmd.report_usage(user_id, material, qty)
            else:
                reply_text = (
                    "Please specify material and quantity.\n"
                    "Usage: ใช้ [material] [qty]"
                )

        elif intent == "help":
            if is_admin:
                reply_text = admin_cmd.get_help_text(is_admin=True)
            else:
                reply_text = emp_cmd.get_help_text()

        else:
            reply_text = (
                "❓ Unknown command.\n"
                "Use: Help / ช่วย\n\n"
                "Or ask: สตอก [item] / ใช้ [item] [qty]"
            )

        # Send reply
        messaging_api.reply_message(
            event.reply_token,
            {"messages": [{"type": "text", "text": reply_text}]},
        )

        # Log action
        activity_logger.log_message_processed(
            user_id=user_id,
            intent=intent,
            action_result="success",
        )

    except Exception as e:
        activity_logger.log_error(
            f"Error handling message: {e}",
            error_type="message_handler_error",
        )

        try:
            messaging_api.reply_message(
                event.reply_token,
                {"messages": [{"type": "text", "text": "⚠️ Error processing message. Please try again."}]},
            )
        except:
            pass


@webhook_handler.add(MessageEvent)
def handle_other_message(event: MessageEvent):
    """Handle non-text messages."""
    try:
        messaging_api.reply_message(
            event.reply_token,
            {"messages": [{"type": "text", "text": "📝 Please send text messages only."}]},
        )
    except Exception as e:
        activity_logger.log_error(
            f"Error handling non-text message: {e}",
            error_type="non_text_handler_error",
        )


# Admin API endpoints (optional, for debugging)
@app.get("/api/anomalies", tags=["Admin"])
async def get_anomalies() -> Dict[str, Any]:
    """Get current anomalies (admin only - should add auth)."""
    try:
        detector = get_anomaly_detector()
        stats = detector.get_summary_stats()
        return ORJSONResponse(stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/users", tags=["Admin"])
async def list_all_users() -> Dict[str, Any]:
    """List all users (admin only - should add auth)."""
    try:
        db_instance = get_db()
        users = db_instance.get_all_users()
        return ORJSONResponse({"users": users, "count": len(users)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        log_level="info",
    )
