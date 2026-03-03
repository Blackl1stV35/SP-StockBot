"""
Verbose activity logging for SP-StockBot.
JSON Lines format + readable console output.
Includes memory monitoring (psutil).
"""

import json
import logging
import psutil
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict
from config import Config


class JSONFormatter(logging.Formatter):
    """Custom formatter for JSON Lines output."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "raw_msg"):
            log_data["raw_msg"] = record.raw_msg
        if hasattr(record, "intent"):
            log_data["intent"] = record.intent
        if hasattr(record, "groq_input"):
            log_data["groq_input"] = record.groq_input
        if hasattr(record, "groq_output"):
            log_data["groq_output"] = record.groq_output
        if hasattr(record, "actions"):
            log_data["actions"] = record.actions
        if hasattr(record, "pin_result"):
            log_data["pin_result"] = record.pin_result
        if hasattr(record, "groq_status"):
            log_data["groq_status"] = record.groq_status
        if hasattr(record, "anomalies"):
            log_data["anomalies"] = record.anomalies
        if hasattr(record, "memory"):
            log_data["memory"] = record.memory

        return json.dumps(log_data, ensure_ascii=False)


class ActivityLogger:
    """Main activity logger with memory monitoring."""

    def __init__(self, name: str = __name__):
        """Initialize logger."""
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, Config.LOG_LEVEL))

        # Ensure logs directory exists
        Path(Config.LOG_DIR).mkdir(parents=True, exist_ok=True)

        # Console handler (readable format)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # File handler (JSON Lines format)
        file_handler = logging.FileHandler(Config.ACTIVITY_LOG, encoding="utf-8")
        file_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
        file_handler.setFormatter(JSONFormatter())
        self.logger.addHandler(file_handler)

    def _get_memory_info(self) -> Dict[str, Any]:
        """Get current memory usage."""
        process = psutil.Process(os.getpid())
        memory = process.memory_info()
        virtual_memory = psutil.virtual_memory()

        return {
            "process_rss_mb": round(memory.rss / (1024 * 1024), 2),
            "process_vms_mb": round(memory.vms / (1024 * 1024), 2),
            "system_used_gb": round(virtual_memory.used / (1024 ** 3), 2),
            "system_available_gb": round(virtual_memory.available / (1024 ** 3), 2),
            "system_percent": round(virtual_memory.percent, 1),
        }

    def log_user_message(
        self,
        user_id: str,
        raw_msg: str,
        intent: Optional[str] = None,
        groq_input: Optional[str] = None,
        groq_output: Optional[Dict[str, Any]] = None,
        actions: Optional[list] = None,
        pin_result: Optional[str] = None,
        groq_status: Optional[Dict[str, Any]] = None,
        anomalies: Optional[list] = None,
    ) -> None:
        """Log user message and bot processing."""
        extra = {
            "user_id": user_id,
            "raw_msg": raw_msg,
            "intent": intent,
            "groq_input": groq_input,
            "groq_output": groq_output,
            "actions": actions or [],
            "pin_result": pin_result,
            "groq_status": groq_status,
            "anomalies": anomalies or [],
            "memory": self._get_memory_info(),
        }

        self.logger.info(
            f"User message: {user_id} | Intent: {intent} | PIN: {pin_result}",
            extra=extra,
        )

    def log_message_received(
        self,
        user_id: str,
        raw_message: str,
    ) -> None:
        """Log incoming message received (simplified wrapper for log_user_message)."""
        extra = {
            "user_id": user_id,
            "raw_msg": raw_message,
            "memory": self._get_memory_info(),
        }
        self.logger.info(
            f"Message received: {user_id} | {raw_message[:50]}...",
            extra=extra,
        )

    def log_message_processed(
        self,
        user_id: str,
        intent: str,
        action_result: str = "success",
    ) -> None:
        """Log message processing completed."""
        extra = {
            "user_id": user_id,
            "intent": intent,
            "action_result": action_result,
            "memory": self._get_memory_info(),
        }
        self.logger.info(
            f"Message processed: {user_id} | Intent: {intent} | Result: {action_result}",
            extra=extra,
        )

    def log_error(
        self,
        error_msg: str,
        user_id: Optional[str] = None,
        error_type: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Log error with context."""
        extra = {
            "user_id": user_id,
            "error_type": error_type,
            "memory": self._get_memory_info(),
        }

        if exception:
            self.logger.exception(error_msg, extra=extra)
        else:
            self.logger.error(error_msg, extra=extra)

    def log_admin_action(
        self,
        admin_id: str,
        action: str,
        target: Optional[str] = None,
        pin_result: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """Log administrative action."""
        extra = {
            "user_id": admin_id,
            "action": action,
            "target": target,
            "pin_result": pin_result,
            "success": success,
            "memory": self._get_memory_info(),
        }

        status = "✓ Success" if success else "✗ Failed"
        self.logger.info(f"Admin action: {action} | {status}", extra=extra)

    def log_groq_api_call(
        self,
        user_id: Optional[str],
        model: str,
        tokens_used: Optional[int] = None,
        response_time_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log Groq API calls."""
        extra = {
            "user_id": user_id,
            "model": model,
            "tokens_used": tokens_used,
            "response_time_ms": response_time_ms,
            "error": error,
            "memory": self._get_memory_info(),
        }

        if error:
            self.logger.warning(f"Groq API error: {error}", extra=extra)
        else:
            self.logger.info(
                f"Groq API call: {model} | {tokens_used or '?'} tokens",
                extra=extra,
            )

    def log_inventory_update(
        self,
        user_id: str,
        file_name: str,
        sheets_processed: int,
        records_added: int,
        records_updated: int,
    ) -> None:
        """Log inventory file upload and processing."""
        extra = {
            "user_id": user_id,
            "file_name": file_name,
            "sheets_processed": sheets_processed,
            "records_added": records_added,
            "records_updated": records_updated,
            "memory": self._get_memory_info(),
        }

        self.logger.info(
            f"Inventory update: {file_name} | "
            f"{sheets_processed} sheets, "
            f"{records_added} new, {records_updated} updated",
            extra=extra,
        )

    def log_anomaly_detection(
        self,
        employee_id: str,
        material_name: str,
        severity: str,
        deviation: float,
    ) -> None:
        """Log anomaly detection."""
        extra = {
            "user_id": employee_id,
            "material": material_name,
            "severity": severity,
            "deviation_percent": deviation,
            "memory": self._get_memory_info(),
        }

        self.logger.warning(
            f"Anomaly detected: {employee_id} | {material_name} | "
            f"{severity} ({deviation:.1f}%)",
            extra=extra,
        )

    def log_background_task(
        self,
        task_name: str,
        status: str,
        duration_ms: Optional[float] = None,
        items_processed: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log background task execution."""
        extra = {
            "task_name": task_name,
            "status": status,
            "duration_ms": duration_ms,
            "items_processed": items_processed,
            "error": error,
            "memory": self._get_memory_info(),
        }

        if error:
            self.logger.error(f"Task '{task_name}' failed: {error}", extra=extra)
        else:
            self.logger.info(
                f"Task '{task_name}' completed ({status})", extra=extra
            )


# Global logger instance
activity_logger = ActivityLogger("SP-StockBot")


if __name__ == "__main__":
    # Test logging
    activity_logger.log_user_message(
        user_id="U123456",
        raw_msg="สตอก สั่ง",
        intent="check_inventory",
        pin_result="not_required",
    )
    activity_logger.log_admin_action(
        admin_id="U999",
        action="add_user",
        target="U123456",
        pin_result="verified",
    )
    activity_logger.log_groq_api_call(
        user_id="U123456",
        model="llama-3.1-8b-instant",
        tokens_used=125,
        response_time_ms=2300,
    )
    print("✓ Logging test completed")
