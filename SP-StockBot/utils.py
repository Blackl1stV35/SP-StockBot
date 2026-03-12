"""
SP-StockBot Utilities
Helper functions for file extraction, vector embeddings, and Flex message templates.
"""

import os
import re
import json
import io
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from PIL import Image

# Optional imports (graceful fallback if not installed)
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

from logger import activity_logger

# LOCAL OLLAMA FIXED 2026-03-12: Bangkok timezone for all timestamps
BANGKOK_TZ = timezone(timedelta(hours=7))


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


def split_into_chunks(text: str, max_tokens: int = 512) -> List[str]:
    """
    Split text into chunks suitable for embedding (~4 chars per token).
    
    Args:
        text: Input text to chunk
        max_tokens: Maximum tokens per chunk (default 512)
        
    Returns:
        List of text chunks
    """
    if not text or not text.strip():
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


def extract_file_content(file_path: str, file_type: str) -> str:
    """
    Dynamically extract text content from various file types.
    
    Supported formats:
    - .xlsx: Excel spreadsheets (extracts all sheets)
    - .pdf: PDF documents (extracts text from all pages)
    - .docx: Word documents (extracts paragraph text)
    - .png/.jpeg: Images (OCR with tesseract)
    
    Args:
        file_path: Path to the file
        file_type: File type ('xlsx', 'pdf', 'docx', 'image')
        
    Returns:
        Extracted text content
    """
    try:
        if file_type == 'xlsx':
            dfs = pd.read_excel(file_path, sheet_name=None)
            result = {}
            for sheet_name, df in dfs.items():
                result[sheet_name] = df.to_dict(orient='records')
            return json.dumps(result, default=str)
        
        elif file_type == 'pdf':
            if not HAS_PYPDF2:
                activity_logger.logger.warning("PyPDF2 not installed, skipping PDF extraction")
                return ""
            text = ""
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        
        elif file_type == 'docx':
            if not HAS_DOCX:
                activity_logger.logger.warning("python-docx not installed, skipping DOCX extraction")
                return ""
            doc = Document(file_path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            return text
        
        elif file_type == 'image':
            if not HAS_TESSERACT:
                activity_logger.logger.warning("pytesseract not installed, skipping OCR")
                return ""
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img)
            return text
        
        else:
            activity_logger.logger.warning(f"Unsupported file type: {file_type}")
            return ""
    
    except Exception as e:
        activity_logger.logger.error(f"Error extracting {file_path} ({file_type}): {e}")
        return ""


def get_report_flex(user_name: str, materials: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate Flex message JSON for inventory report.
    
    Args:
        user_name: Name of the user generating the report
        materials: List of dicts with 'material' and 'qty' keys
        
    Returns:
        Flex message JSON for Carousel or Bubble
    """
    try:
        # Limit to top 5 materials
        top_materials = materials[:5]
        
        contents = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": f"📊 Stock Report",
                        "weight": "bold",
                        "size": "xl",
                        "color": "#FFFFFF"
                    }
                ],
                "backgroundColor": "#2E7D32"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": f"User: {user_name}",
                        "size": "sm",
                        "color": "#666666"
                    },
                    {
                        "type": "text",
                        "text": f"Time: {datetime.now(BANGKOK_TZ).strftime('%d/%m/%Y %H:%M')}",
                        "size": "sm",
                        "color": "#999999"
                    },
                    {"type": "divider"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "baseline",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"{m['material']}",
                                "flex": 6,
                                "size": "sm"
                            },
                            {
                                "type": "text",
                                "text": f"{m.get('qty', 0)} units",
                                "flex": 4,
                                "size": "sm",
                                "align": "end",
                                "color": "#FF6B6B",
                                "weight": "bold"
                            }
                        ]
                    }
                    for m in top_materials
                ]
            }
        }
        
        return contents
    
    except Exception as e:
        activity_logger.logger.error(f"Error generating report Flex: {e}")
        return {"type": "text", "text": "Error generating report"}


def get_alert_flex(alert_title: str, alert_message: str, severity: str = "warning") -> Dict[str, Any]:
    """
    Generate Flex message JSON for anomaly/system alerts.
    
    Args:
        alert_title: Title of the alert
        alert_message: Alert message text
        severity: 'warning', 'error', 'info' (determines color)
        
    Returns:
        Flex message JSON for alert
    """
    try:
        color_map = {
            "warning": "#FF9800",
            "error": "#F44336",
            "info": "#2196F3"
        }
        color = color_map.get(severity, "#FF9800")
        emoji_map = {
            "warning": "⚠️",
            "error": "❌",
            "info": "ℹ️"
        }
        emoji = emoji_map.get(severity, "⚠️")
        
        contents = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{emoji} {alert_title}",
                        "weight": "bold",
                        "size": "lg",
                        "color": color
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "text",
                        "text": alert_message,
                        "wrap": True,
                        "size": "sm",
                        "color": "#666666"
                    },
                    {
                        "type": "text",
                        "text": f"Time: {datetime.now(BANGKOK_TZ).strftime('%d/%m/%Y %H:%M')}",
                        "size": "xs",
                        "color": "#999999",
                        "margin": "lg"
                    }
                ]
            }
        }
        
        return contents
    
    except Exception as e:
        activity_logger.logger.error(f"Error generating alert Flex: {e}")
        return {"type": "text", "text": "System Alert"}


def get_stock_check_flex(materials: List[Dict[str, Any]], user_name: str) -> Dict[str, Any]:
    """
    Generate Flex message JSON for stock level check (table-like format).
    
    Args:
        materials: List of dicts with 'material', 'qty', 'status' keys
        user_name: Name of requesting user
        
    Returns:
        Flex message JSON
    """
    try:
        contents = {
            "type": "bubble",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "📦 Stock Level Check",
                        "weight": "bold",
                        "size": "xl",
                        "color": "#FFFFFF"
                    }
                ],
                "backgroundColor": "#1976D2"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": f"Requested by: {user_name}",
                        "size": "sm",
                        "color": "#666666"
                    },
                    {"type": "divider"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "baseline",
                                "contents": [
                                    {
                                        "type": "text",
                                        "text": m['material'],
                                        "flex": 5,
                                        "size": "sm",
                                        "weight": "bold"
                                    },
                                    {
                                        "type": "text",
                                        "text": f"{m.get('qty', 0)}",
                                        "flex": 2,
                                        "size": "sm",
                                        "align": "center"
                                    },
                                    {
                                        "type": "text",
                                        "text": m.get('status', 'normal'),
                                        "flex": 3,
                                        "size": "sm",
                                        "align": "end",
                                        "color": "#4CAF50" if m.get('status') == 'OK' else "#FF6B6B"
                                    }
                                ]
                            }
                            for m in materials[:10]
                        ]
                    }
                ]
            }
        }
        
        return contents
    
    except Exception as e:
        activity_logger.logger.error(f"Error generating stock check Flex: {e}")
        return {"type": "text", "text": "Error generating stock check"}


def detect_file_type(mime_type: str) -> str:
    """
    Map MIME type to file type string.
    
    Args:
        mime_type: MIME type string
        
    Returns:
        File type: 'xlsx', 'pdf', 'docx', 'image', or 'unknown'
    """
    mapping = {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
        'application/vnd.ms-excel': 'xlsx',
        'application/pdf': 'pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'application/msword': 'docx',
        'image/png': 'image',
        'image/jpeg': 'image',
        'image/jpg': 'image',
    }
    return mapping.get(mime_type, 'unknown')


def format_notification_message(event_type: str, user_name: str, details: Dict[str, Any]) -> str:
    """
    Format notification message for behavior tracking.
    
    Args:
        event_type: Type of event ('report', 'check', 'anomaly', etc.)
        user_name: Name of user
        details: Event details dict
        
    Returns:
        Formatted notification message
    """
    timestamp = datetime.now(BANGKOK_TZ).strftime('%d/%m/%Y %H:%M:%S')
    
    messages = {
        'report': f"📊 {user_name} reported {details.get('material', 'item')} (qty: {details.get('qty', 0)}) at {timestamp}",
        'check': f"🔍 {user_name} checked stock level at {timestamp}",
        'anomaly': f"⚠️ Anomaly detected: {details.get('message', '')} at {timestamp}",
        'registration': f"👤 {user_name} registered at {timestamp}",
    }
    
    return messages.get(event_type, f"📝 {user_name} event at {timestamp}")
