"""
Configuration management for SP-StockBot.
Loads settings from .env file with sensible defaults.
"""

import os
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(ENV_FILE)


def _auto_detect_service_account() -> Optional[str]:
    """Auto-detect service account JSON file location."""
    candidate_paths = [
        Path("./nth-station-489109-s1-6c5ccb8ccef4.json"),
        Path("./SP-StockBot/nth-station-489109-s1-6c5ccb8ccef4.json"),
        Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "./service_account.json")),
    ]

    for path in candidate_paths:
        if path.exists() and path.is_file():
            abs_path = str(path.resolve())
            # Delayed import to avoid circular import issues
            try:
                from logger import activity_logger
                activity_logger.logger.info(f"[OK] Auto-detected service account at {abs_path}")
            except ImportError:
                print(f"[OK] Auto-detected service account at {abs_path} (logger not available yet)")
            return abs_path

    # Fallback
    fallback = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", None)
    if fallback and Path(fallback).exists():
        return fallback

    return None


class Config:
    """Application configuration."""

    # ==================== LINE MESSAGING API ====================
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_SUPER_ADMIN_ID: str = os.getenv("LINE_SUPER_ADMIN_ID", "")

    # ==================== SECURITY ====================
    SUPER_ADMIN_PIN: str = os.getenv("SUPER_ADMIN_PIN", "7482")

    # ==================== GROQ CLOUD (DEPRECATED - Using local Ollama instead) ====================
    # GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")  # LOCAL OLLAMA FIXED 2026-03-12: No longer used
    # GROQ_MODEL: str = "llama-3.1-8b-instant"  # Deprecated

    # ==================== GEMINI API (FREE TIER - INTEGRATED 2026-03-12) ====================
    # Free: 1M context window, 15 RPM, 1500 RPD, 1M TPM
    # Models: gemini-1.5-flash (cheaper), gemini-2.0-flash (faster)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # ==================== GOOGLE DRIVE ====================
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON", None
    )
    GOOGLE_DRIVE_FOLDER_ID: str = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

    # Auto-detected path (computed once at module level)
    GOOGLE_SERVICE_ACCOUNT_PATH: str = _auto_detect_service_account() or ""

    # ==================== APPLICATION ====================
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "false").lower() == "true"
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    APP_WORKERS: int = int(os.getenv("APP_WORKERS", "1"))

    # ==================== DATABASE ====================
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/stockbot.db")

    # Create data directory if it doesn't exist
    DB_DIR = Path(DATABASE_PATH).parent
    DB_DIR.mkdir(parents=True, exist_ok=True)

    # ==================== LOGGING ====================
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")
    ACTIVITY_LOG: str = os.path.join(LOG_DIR, "agent_activity.log")

    # Create logs directory if it doesn't exist
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

    # ==================== ANOMALY DETECTION ====================
    ANOMALY_THRESHOLD_MULTIPLIER: float = float(
        os.getenv("ANOMALY_THRESHOLD_MULTIPLIER", "3.0")
    )
    ANOMALY_LOOKBACK_MONTHS: int = int(
        os.getenv("ANOMALY_LOOKBACK_MONTHS", "3")
    )

    # ==================== BACKGROUND TASKS ====================
    ENABLE_DAILY_SUMMARY: bool = (
        os.getenv("ENABLE_DAILY_SUMMARY", "true").lower() == "true"
    )
    DAILY_SUMMARY_HOUR: int = int(os.getenv("DAILY_SUMMARY_HOUR", "17"))
    WEEKLY_SUMMARY_DAY: int = int(os.getenv("WEEKLY_SUMMARY_DAY", "0"))  # 0 = Monday
    WEEKLY_SUMMARY_HOUR: int = int(os.getenv("WEEKLY_SUMMARY_HOUR", "17"))

    @classmethod
    def get_google_service_account(cls) -> dict:
        """
        Get Google service account credentials.
        Supports both JSON file and JSON string in .env.
        """
        # First try JSON string in environment
        if cls.GOOGLE_SERVICE_ACCOUNT_JSON:
            try:
                from logger import activity_logger
                result = json.loads(cls.GOOGLE_SERVICE_ACCOUNT_JSON)
                activity_logger.logger.info("✓ Loaded service account from GOOGLE_SERVICE_ACCOUNT_JSON env var")
                return result
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # Then try to load from file (auto-detected or configured path)
        service_account_path = cls.GOOGLE_SERVICE_ACCOUNT_PATH
        if service_account_path and Path(service_account_path).exists():
            try:
                with open(service_account_path, encoding="utf-8") as f:
                    result = json.load(f)
                from logger import activity_logger
                activity_logger.logger.info(f"✓ Loaded service account from {service_account_path}")
                return result
            except (json.JSONDecodeError, IOError) as e:
                raise ValueError(
                    f"Failed to load service account from {service_account_path}: {e}"
                )

        # Not found
        from logger import activity_logger
        activity_logger.logger.warning(
            "Google service account credentials not found. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON env var or place JSON file at one of the auto-detected locations."
        )
        raise ValueError(
            "Google service account credentials not found. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON or ensure the JSON file exists."
        )

    @classmethod
    def validate(cls) -> list[str]:
        """
        Validate critical configuration.
        Returns list of validation errors (empty if all OK).
        """
        errors = []

        if not cls.LINE_CHANNEL_SECRET:
            errors.append("LINE_CHANNEL_SECRET is required")
        if not cls.LINE_CHANNEL_ACCESS_TOKEN:
            errors.append("LINE_CHANNEL_ACCESS_TOKEN is required")
        if not cls.LINE_SUPER_ADMIN_ID:
            errors.append("LINE_SUPER_ADMIN_ID is required")
        # LOCAL OLLAMA FIXED 2026-03-12: GROQ no longer required (using local Ollama)
        # if not cls.GROQ_API_KEY:
        #     errors.append("GROQ_API_KEY is required")
        if len(cls.SUPER_ADMIN_PIN) < 4 or len(cls.SUPER_ADMIN_PIN) > 6:
            errors.append("SUPER_ADMIN_PIN must be 4-6 digits")

        return errors


if __name__ == "__main__":
    # Test configuration
    errors = Config.validate()
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("Configuration is valid ✓")
        print(f"ENV: {Config.APP_ENV}")
        print(f"Debug: {Config.APP_DEBUG}")
        print(f"Database: {Config.DATABASE_PATH}")
        print(f"Workers: {Config.APP_WORKERS}")
        print(f"Service Account Path: {Config.GOOGLE_SERVICE_ACCOUNT_PATH or '(not found)'}")