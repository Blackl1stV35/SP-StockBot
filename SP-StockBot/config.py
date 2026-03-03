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


class Config:
    """Application configuration."""

    # ==================== LINE MESSAGING API ====================
    LINE_CHANNEL_SECRET: str = os.getenv(
        "LINE_CHANNEL_SECRET", ""
    )
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv(
        "LINE_CHANNEL_ACCESS_TOKEN", ""
    )
    LINE_SUPER_ADMIN_ID: str = os.getenv(
        "LINE_SUPER_ADMIN_ID", ""
    )

    # ==================== SECURITY ====================
    SUPER_ADMIN_PIN: str = os.getenv("SUPER_ADMIN_PIN", "7482")

    # ==================== GROQ CLOUD ====================
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = "llama-3.1-8b-instant"  # Fast & low token usage

    # ==================== GOOGLE DRIVE ====================
    GOOGLE_SERVICE_ACCOUNT_PATH: str = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_PATH", "./service_account.json"
    )
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON", None
    )
    GOOGLE_DRIVE_FOLDER_ID: str = os.getenv(
        "GOOGLE_DRIVE_FOLDER_ID", ""
    )

    # ==================== APPLICATION ====================
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "false").lower() == "true"
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    APP_WORKERS: int = int(os.getenv("APP_WORKERS", "1"))

    # ==================== DATABASE ====================
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH", "./data/stockbot.db"
    )

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
    DAILY_SUMMARY_HOUR: int = int(
        os.getenv("DAILY_SUMMARY_HOUR", "17")
    )
    WEEKLY_SUMMARY_DAY: int = int(
        os.getenv("WEEKLY_SUMMARY_DAY", "0")
    )  # 0 = Monday
    WEEKLY_SUMMARY_HOUR: int = int(
        os.getenv("WEEKLY_SUMMARY_HOUR", "17")
    )

    @classmethod
    def get_google_service_account(cls) -> dict:
        """
        Get Google service account credentials.
        Supports both JSON file and JSON string in .env.
        """
        if cls.GOOGLE_SERVICE_ACCOUNT_JSON:
            try:
                return json.loads(cls.GOOGLE_SERVICE_ACCOUNT_JSON)
            except json.JSONDecodeError:
                raise ValueError(
                    "Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON"
                )

        if Path(cls.GOOGLE_SERVICE_ACCOUNT_PATH).exists():
            try:
                with open(cls.GOOGLE_SERVICE_ACCOUNT_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                raise ValueError(
                    f"Failed to load service account from "
                    f"{cls.GOOGLE_SERVICE_ACCOUNT_PATH}: {e}"
                )

        raise ValueError(
            "Google service account credentials not found. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_PATH"
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
        if not cls.GROQ_API_KEY:
            errors.append("GROQ_API_KEY is required")
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
