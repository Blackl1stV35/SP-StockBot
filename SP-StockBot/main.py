"""
SP-StockBot Main Application
FastAPI webhook for Line Bot + Background task scheduler.
Optimized for 8GB RAM, CPU-only (no local GPU).
Includes vector DB (chromadb), embeddings, and Grafana integration.
"""

import gc
import logging
import sys
import os
import re
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
import tempfile
import torch

import psutil
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

# Vector DB and embeddings
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

# Line Bot SDK v3
from linebot.v3.messaging import MessagingApi, ApiClient, TextMessage, ReplyMessageRequest, FlexMessage
from linebot.v3.webhook import WebhookHandler, MessageEvent
from linebot.v3.webhooks import TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from database import Database
from local_llm_agent import LocalLLMAgent  # LOCAL SHIFT 2026-03-12: Replace Groq with local Ollama
from drive_handler import DriveHandler
from xlsx_parser import XlsxParser
from anomaly_detector import AnomalyDetector
from logger import activity_logger
from commands.admin_commands import AdminCommands
from commands.employee_commands import EmployeeCommands

# Background scheduler (initialized before app for use in lifespan)
scheduler = BackgroundScheduler()

# LOCAL OLLAMA FIXED 2026-03-12: Bangkok timezone constant
BKK_TZ = timezone(timedelta(hours=7))

# ==================== VECTOR DB & EMBEDDINGS INITIALIZATION ====================
# Initialize vector DB
vector_db_path = os.getenv('VECTOR_DB_PATH', './vector_db')
vector_client = PersistentClient(path=vector_db_path)

# Get or create collections
inventory_collection = vector_client.get_or_create_collection("inventory")
user_collection = vector_client.get_or_create_collection("users")
behavior_collection = vector_client.get_or_create_collection("behaviors")

# Initialize embedding model with GPU detection
device = 'cuda' if torch.cuda.is_available() else 'cpu'
model_name = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
embedding_model = SentenceTransformer(model_name).to(device)

activity_logger.logger.info(f"Vector DB initialized at {vector_db_path}")
activity_logger.logger.info(f"Embeddings model: {model_name} on device: {device}")
activity_logger.logger.info(f"[LOCAL SHIFT 2026-03-12] Using local LLM (Ollama) instead of Groq cloud")

# ==================== HELPER FUNCTIONS FOR VECTOR OPERATIONS ====================

# ==================== LOCAL AI FUNCTIONS ====================

def embed_message(text: str, user_id: str, metadata: Dict[str, Any]) -> bool:
    """
    Always embed user message as internal AI assistant observation.
    Captures full context: user message, timestamp, intent, metadata.
    
    LOCAL SHIFT 2026-03-12: Every message becomes a learning point.
    
    Args:
        text: User message text (original)
        user_id: Line user ID
        metadata: Dict with intent, material, qty, timestamp, etc.
        
    Returns:
        True if embedded, False if failed
    """
    try:
        # Embed in behavior collection (internal observations)
        doc_id = f"message_{user_id}_{metadata.get('timestamp', '')}"
        embed_and_upsert(
            text=text,
            doc_id=doc_id,
            collection_ref=behavior_collection,
            metadata={
                'user_id': user_id,
                'type': 'message',
                'intent': metadata.get('intent', ''),
                'material': metadata.get('material', ''),
                'quantity': metadata.get('quantity', 0),
                'timestamp': metadata.get('timestamp', datetime.now(tz=BKK_TZ).isoformat())
            }
        )
        return True
    except Exception as e:
        activity_logger.logger.warning(f"Failed to embed message: {e}")
        return False


def suggest_interaction(user_id: str, intent: str, confidence: float) -> bool:
    """
    RL policy stub: Suggest follow-up if user message was ambiguous.
    
    Simple rule-based approach (no heavy ML):
    - If confidence < 0.6: suggest clarification
    - If intent='other': suggest help menu
    - Mechanics are busy: no aggressive follow-up
    
    Reward model (future DQN):
      +1.0: user confirms clarification
      +0.5: user completes action (report/check)
       0.0: user ignores suggestion (OK - they're busy)
      -0.5: user negative feedback (avoid pattern)
    
    LOCAL SHIFT 2026-03-12: Observational + non-intrusive
    
    Args:
        user_id: Line user ID
        intent: Classified intent from LLM
        confidence: Confidence score 0.0-1.0
        
    Returns:
        True if suggestion should be sent, False if stay silent
    """
    # For now: only suggest if very ambiguous (confidence < 0.5)
    if confidence < 0.5 and intent == 'other':
        return True
    # Never be aggressive - mechanics are busy
    return False


def get_inference_device() -> str:
    """
    Get current inference device (Ollama chooses GPU or CPU).
    LOCAL SHIFT 2026-03-12
    """
    try:
        # Check if torch CUDA available (for embeddings)
        if torch.cuda.is_available():
            return f"cuda ({torch.cuda.get_device_name(0)})"
        else:
            return "cpu"
    except:
        return "cpu"


def parse_quantity(text: str) -> int:
    """
    Extract and sum numbers from the quantity part of a message.
    Handles common mechanic reporting patterns:
    - "เบิก กดทห80 5+5+"
    - "กดทห100 10+"
    - "ใช้ สเปย์ 3 ชิ้น"
    - "5+10+2" (standalone)
    - "เบิก นวม1000 5+3+2"
    Focuses on the last number group(s) to avoid summing material codes like 80, 100.
    
    Args:
        text: String containing quantity info (e.g., "เบิก กดทห80 5+5+", "5+10+2")
        
    Returns:
        Sum of extracted numbers from quantity part, or 0 if parsing fails
    """
    if not text or not str(text).strip():
        return 0

    text = str(text).strip()
    
    try:
        # Step 1: Look for pattern with + signs (highest confidence - actual quantities)
        # Matches: "5+5+" or "10+2+" or "5+3+2" or "10+2"
        # This regex finds: digit(s) followed by (+digit)+ and optional trailing +
        match_plus = re.search(r'(\d+(?:\s*\+\s*\d+)+\+?)$', text)
        if match_plus:
            qty_part = match_plus.group(1)
            numbers = re.findall(r'\d+', qty_part)
            if numbers:
                return sum(int(x) for x in numbers)
        
        # Step 2: If no + pattern found, look for the last standalone number in text
        # (which might not be the last token if followed by unit words like "pieces" or "ชิ้น")
        # Scan from right to left for numbers, skipping Thai material codes
        tokens = text.split()
        
        # Iterate through tokens in reverse order
        for i in range(len(tokens) - 1, -1, -1):
            token = tokens[i]
            # Does this token contain digits?
            if re.search(r'\d', token):
                numbers = re.findall(r'\d+', token)
                if numbers:
                    # Check if this token is preceded by Thai text (material code indicator)
                    if i > 0:
                        prev_token = tokens[i - 1]
                        has_thai_prefix = any(ord(c) > 127 for c in prev_token)
                        max_num = max(int(x) for x in numbers)
                        if has_thai_prefix and max_num >= 50:
                            # Skip this - likely a material code like "กดทห80"
                            continue
                    
                    # Accept this number
                    return sum(int(x) for x in numbers)
        
        return 0
    
    except Exception as e:
        activity_logger.logger.warning(f"Error parsing quantity '{text}': {e}")
        return 0


def embed_and_upsert(text: str, doc_id: str, collection_ref, metadata: Dict[str, Any]):
    """Embed text and upsert to vector collection."""
    try:
        if not text or not text.strip():
            return
        embedding = embedding_model.encode(text)
        collection_ref.upsert(
            ids=[doc_id],
            embeddings=[embedding.tolist()],
            documents=[text],
            metadatas=[metadata]
        )
    except Exception as e:
        activity_logger.logger.error(f"Error embedding and upserting {doc_id}: {e}")


def split_into_chunks(text: str, max_tokens: int = 512) -> list:
    """Split text into chunks by word count (~4 chars per token)."""
    if not text:
        return []
    
    max_length = max_tokens * 4
    words = text.split()
    chunks = []
    current = []
    
    for word in words:
        current.append(word)
        if len(' '.join(current)) >= max_length:
            chunks.append(' '.join(current))
            current = []
    
    if current:
        chunks.append(' '.join(current))
    
    return chunks if chunks else [text]


def register_user_with_vector_profile(user_id: str, display_name: str) -> bool:
    """
    Register a new user with vector profile.
    Creates per-user Drive folder and embeds profile in vector DB.
    
    Args:
        user_id: Line user ID
        display_name: User's display name
        
    Returns:
        True if registration successful, False otherwise
    """
    try:
        activity_logger.logger.info(f"Registering user: {user_id} ({display_name})")
        
        # Create per-user Drive folder
        try:
            drive = get_drive_handler()
            if drive and Config.GOOGLE_DRIVE_FOLDER_ID:
                folder_result = drive.service.files().create(
                    body={
                        'name': f'Users/{user_id}',
                        'mimeType': 'application/vnd.google-apps.folder',
                        'parents': [Config.GOOGLE_DRIVE_FOLDER_ID]
                    },
                    fields='id'
                ).execute()
                
                user_folder_id = folder_result.get('id')
                activity_logger.logger.info(f"Created Drive folder for {user_id}: {user_folder_id}")
        except Exception as e:
            activity_logger.logger.warning(f"Could not create Drive folder for {user_id}: {e}")
        
        # Embed user profile in vector DB
        profile_text = f"User: {display_name} (ID: {user_id}), registered {datetime.now(tz=BKK_TZ).isoformat()}"
        embed_and_upsert(
            text=profile_text,
            doc_id=f"user_profile_{user_id}",
            collection_ref=user_collection,
            metadata={
                'user_id': user_id,
                'type': 'profile',
                'display_name': display_name,
                'registered_at': datetime.now(tz=BKK_TZ).isoformat()
            }
        )
        
        # Log registration in behavior collection
        from utils import format_notification_message
        notification = format_notification_message('registration', display_name, {})
        embed_and_upsert(
            text=notification,
            doc_id=f"behavior_registration_{user_id}_{datetime.now().timestamp()}",
            collection_ref=behavior_collection,
            metadata={
                'user_id': user_id,
                'type': 'registration',
                'timestamp': datetime.now(tz=BKK_TZ).isoformat()
            }
        )
        
        activity_logger.logger.info(f"✓ User {user_id} registered successfully with vector profile")
        return True
    
    except Exception as e:
        activity_logger.logger.error(f"Error registering user {user_id}: {e}")
        return False


def handle_inventory_report(user_id: str, display_name: str, material: str, quantity_str: str) -> int:
    """
    Handle inventory report: parse quantity, embed narrative in vector DB.
    
    Args:
        user_id: Line user ID
        display_name: User's display name
        material: Material/item name
        quantity_str: Quantity string (e.g., "5+5+")
        
    Returns:
        Parsed quantity as integer
    """
    try:
        qty = parse_quantity(quantity_str)
        
        # Create narrative for embedding
        narrative = f"{display_name} reported {qty} of {material} at {datetime.now(tz=BKK_TZ).isoformat()}"
        
        # Embed in inventory collection
        doc_id = f"report_{user_id}_{material}_{datetime.now().timestamp()}"
        embed_and_upsert(
            text=narrative,
            doc_id=doc_id,
            collection_ref=inventory_collection,
            metadata={
                'user_id': user_id,
                'type': 'report',
                'material': material,
                'quantity': qty,
                'reported_at': datetime.now(tz=BKK_TZ).isoformat()
            }
        )
        
        # Log in behavior collection
        from utils import format_notification_message
        notification = format_notification_message('report', display_name, {'material': material, 'qty': qty})
        embed_and_upsert(
            text=notification,
            doc_id=f"behavior_report_{user_id}_{datetime.now().timestamp()}",
            collection_ref=behavior_collection,
            metadata={
                'user_id': user_id,
                'type': 'report',
                'material': material,
                'quantity': qty,
                'timestamp': datetime.now(tz=BKK_TZ).isoformat()
            }
        )
        
        activity_logger.logger.info(f"✓ Report embedded: {display_name} reported {qty} of {material}")
        return qty
    
    except Exception as e:
        activity_logger.logger.error(f"Error handling inventory report: {e}")
        return 0


def query_user_inventory_reports(user_id: str, limit: int = 5) -> list:
    """
    Query vector DB for user's recent inventory reports.
    
    Args:
        user_id: Line user ID
        limit: Maximum number of results
        
    Returns:
        List of dicts with 'material', 'qty', 'timestamp'
    """
    try:
        results = inventory_collection.query(
            query_texts=["inventory report"],
            n_results=limit,
            where={"user_id": user_id, "type": "report"}
        )
        
        materials = []
        if results['metadatas']:
            for metadata in results['metadatas'][0]:
                materials.append({
                    'material': metadata.get('material', 'Unknown'),
                    'qty': metadata.get('quantity', 0),
                    'timestamp': metadata.get('reported_at', '')
                })
        
        return materials
    
    except Exception as e:
        activity_logger.logger.error(f"Error querying user reports: {e}")
        return []


def send_report_flex_message(user_id: str, display_name: str):
    """
    Send personalized inventory report Flex message to user.
    Queries vector DB for user's recent reports.
    
    Args:
        user_id: Line user ID
        display_name: User's display name
    """
    try:
        from utils import get_report_flex
        
        # Query user's recent reports
        materials = query_user_inventory_reports(user_id, limit=5)
        
        if not materials:
            # No reports found, send notification
            msg = TextMessage(text="📊 No recent inventory reports found. Start reporting!")
            messaging_api.push_message(to=user_id, messages=[msg])
            return
        
        # Generate Flex message
        flex_content = get_report_flex(display_name, materials)
        flex_message = FlexMessage(
            alt_text="Inventory Report",
            contents=flex_content
        )
        
        messaging_api.push_message(to=user_id, messages=[flex_message])
        activity_logger.logger.info(f"✓ Sent report Flex to {user_id}")
    
    except Exception as e:
        activity_logger.logger.error(f"Error sending report Flex: {e}")


def send_alert_flex_message(user_id: str, alert_title: str, alert_message: str, severity: str = "warning"):
    """
    Send anomaly/system alert Flex message.
    
    Args:
        user_id: Line user ID to receive alert
        alert_title: Alert title
        alert_message: Alert message text
        severity: 'warning', 'error', or 'info'
    """
    try:
        from utils import get_alert_flex
        
        flex_content = get_alert_flex(alert_title, alert_message, severity)
        flex_message = FlexMessage(
            alt_text=alert_title,
            contents=flex_content
        )
        
        messaging_api.push_message(to=user_id, messages=[flex_message])
        activity_logger.logger.info(f"✓ Sent {severity} alert Flex to {user_id}")
    
    except Exception as e:
        activity_logger.logger.error(f"Error sending alert Flex: {e}")


def send_stock_check_flex_message(user_id: str, display_name: str, materials: list):
    """
    Send stock level check Flex message.
    
    Args:
        user_id: Line user ID
        display_name: User's name
        materials: List of dicts with material info
    """
    try:
        from utils import get_stock_check_flex
        
        flex_content = get_stock_check_flex(materials, display_name)
        flex_message = FlexMessage(
            alt_text="Stock Check",
            contents=flex_content
        )
        
        messaging_api.push_message(to=user_id, messages=[flex_message])
        activity_logger.logger.info(f"✓ Sent stock check Flex to {user_id}")
    
    except Exception as e:
        activity_logger.logger.error(f"Error sending stock check Flex: {e}")


# Lifespan context manager for FastAPI startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-register super admin if not exists
    db = get_db()
    super_admin_id = Config.LINE_SUPER_ADMIN_ID
    if not db.get_user(super_admin_id):
        db.add_user(
            line_user_id=super_admin_id,
            display_name="Super Admin (Auto)",
            excel_name="Super Admin (Auto)",
            role="super_admin"
        )
        activity_logger.logger.info(f"Auto-registered super admin: {super_admin_id}")
    
    # Load saved Google Drive folder ID from database
    saved_folder_id = db.get_setting("GOOGLE_DRIVE_FOLDER_ID")
    if saved_folder_id:
        Config.GOOGLE_DRIVE_FOLDER_ID = saved_folder_id
        activity_logger.logger.info(f"Loaded GOOGLE_DRIVE_FOLDER_ID from DB: {saved_folder_id}")
    
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
        get_local_llm_agent()  # LOCAL SHIFT 2026-03-12: Local Ollama instead of Groq
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

# ==================== LINE BOT SDK v3 – Correct Initialization ====================
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi  # ensure Configuration is imported

configuration = Configuration(
    access_token=Config.LINE_CHANNEL_ACCESS_TOKEN
)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)

webhook_handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)

# Initialize components (lazy loaded)
db: Optional[Database] = None
local_llm_agent: Optional[LocalLLMAgent] = None  # LOCAL SHIFT 2026-03-12
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


def get_local_llm_agent() -> LocalLLMAgent:  # LOCAL SHIFT 2026-03-12: Replace Groq with local Ollama
    """Get or initialize local LLM agent (Ollama-based)."""
    global local_llm_agent
    if local_llm_agent is None:
        local_llm_agent = LocalLLMAgent()
    return local_llm_agent


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
        admin_commands = AdminCommands(get_db(), get_local_llm_agent())  # LOCAL SHIFT 2026-03-12
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
        agent = get_local_llm_agent()  # LOCAL SHIFT 2026-03-12

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
                    to=Config.LINE_SUPER_ADMIN_ID,
                    messages=[message]
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


def extract_and_embed_file(file_id: str, file_name: str, mime_type: str, user_id: str, drive_handler):
    """
    Dynamically extract and embed file content in vector DB.
    Supports: .xlsx, .pdf, .docx, .png, .jpeg
    
    Args:
        file_id: Google Drive file ID
        file_name: File name
        mime_type: MIME type
        user_id: User ID for metadata
        drive_handler: DriveHandler instance
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from utils import extract_file_content, split_into_chunks, detect_file_type
        
        file_type = detect_file_type(mime_type)
        
        if file_type == 'unknown':
            activity_logger.logger.warning(f"Unsupported file type: {mime_type}")
            return False
        
        # Download file
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        
        success = drive_handler.download_file(file_id, tmp_path)
        if not success:
            activity_logger.logger.error(f"Failed to download {file_name}")
            return False
        
        # Extract text from file
        activity_logger.logger.info(f"Extracting content from {file_name} ({file_type})...")
        text_content = extract_file_content(tmp_path, file_type)
        
        if not text_content:
            activity_logger.logger.warning(f"No content extracted from {file_name}")
            return False
        
        # Split into chunks and embed
        chunks = split_into_chunks(text_content, max_tokens=512)
        activity_logger.logger.info(f"Split into {len(chunks)} chunks for embedding")
        
        for i, chunk in enumerate(chunks):
            try:
                doc_id = f"{user_id}_{file_id}_{i}"
                embed_and_upsert(
                    text=chunk,
                    doc_id=doc_id,
                    collection_ref=inventory_collection,
                    metadata={
                        'user_id': user_id,
                        'file_type': file_type,
                        'file_name': file_name,
                        'file_id': file_id,
                        'extracted_at': datetime.now(tz=BKK_TZ).isoformat(),
                        'chunk_index': i
                    }
                )
            except Exception as e:
                activity_logger.logger.error(f"Error embedding chunk {i}: {e}")
        
        activity_logger.logger.info(f"✓ Embedded {len(chunks)} chunks from {file_name}")
        
        # Clean up
        try:
            os.remove(tmp_path)
        except:
            pass
        
        return True
    
    except Exception as e:
        activity_logger.logger.error(f"Error extracting file {file_name}: {e}")
        return False


def check_drive_for_new_files():
    """
    Check Drive for new inventory files in per-user folders.
    Supports dynamic extraction: .xlsx, .pdf, .docx, .png, .jpeg
    Deletes files after successful extraction.
    """
    try:
        activity_logger.logger.info(
            f"▶ [Drive Scan] Starting background file scan (with vector extraction) | "
            f"Folder ID: {Config.GOOGLE_DRIVE_FOLDER_ID}"
        )

        if not Config.GOOGLE_DRIVE_FOLDER_ID:
            activity_logger.logger.warning(
                "[Drive Scan] GOOGLE_DRIVE_FOLDER_ID not configured - skipping"
            )
            return

        drive = get_drive_handler()
        if not drive:
            activity_logger.logger.error(
                "[Drive Scan] Drive handler is None - service unavailable"
            )
            return

        # Query per-user folders (Users/*)
        try:
            user_folders_results = drive.service.files().list(
                q=f"'{Config.GOOGLE_DRIVE_FOLDER_ID}' in parents and name contains 'Users/' and mimeType='application/vnd.google-apps.folder'",
                spaces='drive',
                fields='files(id, name)',
                pageSize=50
            ).execute()
            
            user_folders = user_folders_results.get('files', [])
            activity_logger.logger.info(f"[Drive Scan] Found {len(user_folders)} user folders")
        except Exception as e:
            activity_logger.logger.warning(f"Error querying user folders: {e}")
            user_folders = []
        
        # Process each user folder
        for user_folder in user_folders:
            try:
                user_id = user_folder['name'].split('/')[-1]
                folder_id = user_folder['id']
                
                activity_logger.logger.debug(f"[Drive Scan] Processing user folder: {user_id}")
                
                # List files in user folder
                files_results = drive.service.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields='files(id, name, mimeType)',
                    pageSize=10
                ).execute()
                
                files = files_results.get('files', [])
                
                for file in files:
                    try:
                        file_id = file.get('id')
                        file_name = file.get('name')
                        mime_type = file.get('mimeType', '')
                        
                        # Check if already processed
                        db_instance = get_db()
                        processed = db_instance.get_processed_file(file_id)
                        if processed:
                            activity_logger.logger.debug(f"File already processed: {file_name}")
                            continue
                        
                        # Extract and embed
                        success = extract_and_embed_file(file_id, file_name, mime_type, user_id, drive)
                        
                        if success:
                            # Mark as processed
                            db_instance.mark_file_processed(
                                file_id=file_id,
                                file_name=file_name,
                                records_count=1
                            )
                            
                            # Delete file from Drive
                            try:
                                drive.service.files().delete(fileId=file_id).execute()
                                activity_logger.logger.info(f"✓ Deleted file after extraction: {file_name}")
                            except Exception as e:
                                activity_logger.logger.warning(f"Could not delete file {file_name}: {e}")
                            
                            # Notify user
                            user_display_name = db_instance.get_user(user_id)
                            if user_display_name:
                                display_name = user_display_name.get('display_name', user_id)
                                send_alert_flex_message(
                                    user_id,
                                    "File Processed",
                                    f"✓ Successfully extracted and embedded: {file_name}",
                                    "info"
                                )
                    
                    except Exception as e:
                        activity_logger.logger.error(f"Error processing file {file_name}: {e}")
            
            except Exception as e:
                activity_logger.logger.error(f"Error processing user folder: {e}")
        
        activity_logger.logger.info("✓ Drive scan completed")

    except Exception as e:
        activity_logger.log_error(
            f"Error checking Drive files: {e}",
            error_type="drive_check_error",
        )


def check_drive_for_new_files_legacy():
    """Legacy function for XLSX-only extraction. Kept for backward compatibility."""
    try:
        activity_logger.logger.info(
            f"▶ [Drive Scan Legacy] Starting XLSX-only scan | "
            f"Folder ID: {Config.GOOGLE_DRIVE_FOLDER_ID}"
        )

        if not Config.GOOGLE_DRIVE_FOLDER_ID:
            activity_logger.logger.warning(
                "[Drive Scan] GOOGLE_DRIVE_FOLDER_ID not configured - skipping"
            )
            return

        drive = get_drive_handler()
        if not drive:
            activity_logger.logger.error(
                "[Drive Scan] Drive handler is None - service unavailable"
            )
            return

        # Find latest XLSX file
        activity_logger.logger.debug(
            f"[Drive Scan] Querying folder: {Config.GOOGLE_DRIVE_FOLDER_ID}"
        )
        
        latest_file = drive.find_latest_xlsx(Config.GOOGLE_DRIVE_FOLDER_ID)

        if not latest_file:
            activity_logger.logger.info(
                f"[Drive Scan] No XLSX files found in folder {Config.GOOGLE_DRIVE_FOLDER_ID}"
            )
            return

        file_id = latest_file.get("id")
        file_name = latest_file.get("name")
        
        activity_logger.logger.info(
            f"[Drive Scan] Found file: {file_name} | ID: {file_id}"
        )

        # Check if we've already processed this file
        db_instance = get_db()
        processed = db_instance.get_processed_file(file_id)
        if processed:
            activity_logger.logger.info(
                f"[Drive Scan] File already processed: {file_name}"
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
        messaging_api.push_message(
            to=Config.LINE_SUPER_ADMIN_ID,
            messages=[message]
        )

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

    # LOCAL OLLAMA FIXED 2026-03-12: Groq no longer required (using local Ollama)
    # try:
    #     import groq
    #     print("  OK groq")
    #     checks_passed += 1
    # except ImportError as e:
    #     print(f"  FAIL groq: {e}")
    #     checks_failed += 1

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
        _ = messaging_api  # simple reference to confirm it's usable
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
        
        # LOCAL SHIFT 2026-03-12: Include inference device info
        inference_device = get_inference_device()
        llm_status = "ready" if get_local_llm_agent() else "error"

        return ORJSONResponse({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "memory_mb": mem_info.rss / 1024 / 1024,
            "cpu_percent": process.cpu_percent(interval=0.1),
            "inference_device": inference_device,  # e.g., "cuda (RTX 1650)" or "cpu"
            "llm_status": llm_status,  # Ollama connectivity
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
        body_str = body.decode("utf-8")
        
        # Debug logging
        activity_logger.logger.debug(f"[Webhook] Received body length: {len(body_str)} | Signature: {signature[:20]}")
        activity_logger.logger.debug(f"[Webhook] Body: {body_str[:200]}")

        # Verify signature
        try:
            webhook_handler.handle(body_str, signature)
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


# Official v3 pattern: TextMessageContent from webhooks + ReplyMessageRequest
@webhook_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    """Handle TEXT messages only (official v3 filter with TextMessageContent)"""
    try:
        user_id = event.source.user_id
        user_message = event.message.text.strip()

        activity_logger.log_message_received(
            user_id=user_id,
            raw_message=user_message,
        )

        db_instance = get_db()
        agent = get_local_llm_agent()  # LOCAL SHIFT 2026-03-12: Local LLM
        admin_cmd = get_admin_commands()
        emp_cmd = get_employee_commands()

        user = db_instance.get_user(user_id)
        is_admin = user is not None and user.get("role") == "super_admin"
        is_registered = user is not None

        if not is_registered:
            reply_text = (
                "👋 ยินดีต้อนรับสู่ SP-StockBot!\n\n"
                "กรุณาขอให้แอดมินเพิ่มคุณในระบบก่อนนะครับ\n"
                "แอดมินใช้คำสั่ง: Add user [ชื่อ] PIN:[รหัส]"
            )
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
            return

        # Classify intent using local LLM (Ollama) - LOCAL SHIFT 2026-03-12
        intent_result = agent.classify_intent(
            user_message=user_message,
            user_name=user.get("display_name", "User"),
            is_admin=is_admin,
        )

        intent = intent_result.get("intent", "other")
        confidence = intent_result.get("confidence", 0.0)
        requires_pin = intent_result.get("requires_pin", False)
        reply_text = intent_result.get("reply_text", "")

        # LOCAL SHIFT 2026-03-12: Embed all messages for internal AI learning
        embed_message(
            text=user_message,
            user_id=user_id,
            metadata={
                'intent': intent,
                'material': intent_result.get("parameters", {}).get("material", ""),
                'quantity': intent_result.get("parameters", {}).get("quantity", 0),
                'timestamp': datetime.now(tz=BKK_TZ).isoformat()
            }
        )

        # LOCAL SHIFT 2026-03-12: Check if we should suggest clarification (RL policy)
        if suggest_interaction(user_id, intent, confidence):
            # Send clarification suggestion (but not aggressively)
            activity_logger.logger.debug(f"[RL] Suggesting clarification for: {user_id}")
            # Could send help suggestions here, but mechanics are busy - stay silent

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
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
                return

            if provided_pin and not agent.verify_pin(
                provided_pin, Config.SUPER_ADMIN_PIN
            ):
                reply_text = "❌ PIN incorrect. Command rejected."
                messaging_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
                activity_logger.log_admin_action(
                    admin_id=user_id,
                    action="pin_attempt",
                    pin_result="failed",
                    success=False,
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
                admin_id=user_id,
                action=cmd_name or "unknown",
                pin_result="verified" if provided_pin else "not_required",
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

        elif intent in ("error", "other"):
            # Groq failed or couldn't classify intent
            # Log it but don't reply (silent ignore)
            activity_logger.logger.warning(
                f"[Intent] Unclassified message | User: {user_id} | Intent: {intent} | "
                f"Confidence: {intent_result.get('confidence', 0)}"
            )
            # Don't send a reply - just acknowledge silently
            activity_logger.log_message_processed(
                user_id=user_id,
                intent=intent,
                action_result="ignored",
            )
            return  # Exit early without reply

        else:
            # Unknown intent type (shouldn't reach here, but be defensive)
            activity_logger.logger.warning(
                f"[Intent] Unknown intent type: {intent} for user {user_id}"
            )
            activity_logger.log_message_processed(
                user_id=user_id,
                intent=intent,
                action_result="ignored",
            )
            return  # Exit early without reply

        # Final reply – ReplyMessageRequest wrapper pattern
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text or "ได้รับข้อความแล้วครับ")]
            )
        )

        activity_logger.log_message_processed(
            user_id=user_id,
            intent=intent,
            action_result="success",
        )

    except Exception as e:
        activity_logger.log_error(
            f"Error in text handler: {e}",
            error_type="text_handler_error",
        )
        try:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="⚠️ มีข้อผิดพลาดในการประมวลผล กรุณาลองใหม่นะครับ")]
                )
            )
        except:
            pass



def handle_image_message(event: MessageEvent) -> Optional[str]:
    """
    Stub: Handle image messages with OCR (Local Shift 2026-03-12).
    Extract text from images → embed → classify intent.
    
    Currently: Just acknowledge. Future: EasyOCR for Thai text extraction.
    """
    try:
        activity_logger.logger.info("[Image] Received image (stub - EasyOCR coming)")
        # TODO: Download image from Line → EasyOCR(Thai) → text → embed + intent
        return None  # Return extracted text or None if failed
    except Exception as e:
        activity_logger.logger.error(f"[Image] Error: {e}")
        return None


def handle_voice_message(event: MessageEvent) -> Optional[str]:
    """
    Stub: Handle voice messages with transcription (Local Shift 2026-03-12).
    Extract audio → Vosk transcribe → classify intent.
    
    Currently: Just acknowledge. Future: Vosk for offline Thai speech-to-text.
    """
    try:
        activity_logger.logger.info("[Voice] Received voice message (stub - Vosk coming)")
        # TODO: Download audio from Line → Vosk(Thai) → text → embed + intent
        return None  # Return transcribed text or None if failed
    except Exception as e:
        activity_logger.logger.error(f"[Voice] Error: {e}")
        return None


@webhook_handler.add(MessageEvent)
def handle_other_message(event: MessageEvent):
    """
    Catch-all for non-text messages (LOCAL SHIFT 2026-03-12).
    Image/voice are stubs for future release.
    """
    try:
        message_type = getattr(event.message, 'type', 'unknown')
        
        if message_type == "image":
            extracted_text = handle_image_message(event)
            if extracted_text:
                # Could process extracted_text here in future
                pass
            # For now, just acknowledge
            reply = "🖼️ ขอบคุณที่ส่งรูป! อยู่ระหว่างพัฒนาฟีเจอร์ (Image OCR coming soon)"
        
        elif message_type == "audio":
            extracted_text = handle_voice_message(event)
            if extracted_text:
                # Could process extracted_text here in future
                pass
            # For now, just acknowledge
            reply = "🎙️ ขอบคุณที่ส่งเสียง! อยู่ระหว่างพัฒนาฟีเจอร์ (Voice recognition coming soon)"
        
        else:
            # Unsupported type
            reply = f"📎 กรุณาส่งข้อความตัวหนังสือเท่านั้นนะครับ (รับยกเว้น: รูป, เสียง ในอนาคต)"
        
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )
    except Exception as e:
        activity_logger.log_error(
            f"Error in non-text handler: {e}",
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
