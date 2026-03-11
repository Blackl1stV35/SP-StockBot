"""
Database layer for SP-StockBot.
SQLite schema and CRUD operations for users, inventory, anomalies, drive files, etc.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any
from config import Config


class Database:
    """SQLite database manager with schema initialization and CRUD operations."""

    def __init__(self, db_path: str = Config.DATABASE_PATH):
        """Initialize database connection and create tables if needed."""
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory for dict-like rows."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create all required tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # ==================== USERS TABLE ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                line_user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                excel_name TEXT,
                role TEXT NOT NULL CHECK(role IN ('super_admin', 'employee')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== INVENTORY TABLE ====================
        # Tracks material usage per employee per month
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_line_id TEXT NOT NULL,
                material_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                quantity REAL,
                unit TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_line_id) REFERENCES users(line_user_id),
                UNIQUE(employee_line_id, material_name, year, month)
            )
        """)

        # ==================== ANOMALIES TABLE ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_line_id TEXT NOT NULL,
                material_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                deviation_percent REAL,
                severity TEXT CHECK(severity IN ('Low', 'Medium', 'High')),
                description TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_line_id) REFERENCES users(line_user_id)
            )
        """)

        # ==================== DRIVE FILES LOG ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drive_files (
                file_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                uploaded_by TEXT,
                folder_id TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                parsed_at TIMESTAMP,
                parsed_successfully BOOLEAN DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== GROQ CACHE ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groq_cache (
                message_hash TEXT PRIMARY KEY,
                intent TEXT,
                parameters TEXT,
                reply_text TEXT,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)

        # ==================== ADMIN ACTIONS LOG ====================
        # ==================== SETTINGS TABLE ====================
        # Store application settings like Google Drive folder ID
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                description TEXT,
                updated_by TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== ADMIN ACTIONS LOG ====================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_line_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                parameters TEXT,
                pin_verified BOOLEAN,
                success BOOLEAN,
                error_message TEXT,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_line_id) REFERENCES users(line_user_id)
            )
        """)

        conn.commit()
        conn.close()

    # ==================== USER CRUD ====================

    def add_user(
        self,
        line_user_id: str,
        display_name: str,
        excel_name: Optional[str] = None,
        role: str = "employee",
    ) -> bool:
        """Add or update a user."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO users (line_user_id, display_name, excel_name, role)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(line_user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    excel_name = excluded.excel_name,
                    role = excluded.role,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (line_user_id, display_name, excel_name, role),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Error adding user: {e}")
            return False
        finally:
            conn.close()

    def get_user(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by Line ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE line_user_id = ?", (line_user_id,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users ORDER BY display_name")
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    # ==================== INVENTORY CRUD ====================

    def log_usage(
        self,
        employee_line_id: str,
        material_name: str,
        year: int,
        month: int,
        quantity: float,
        unit: str = "ชิ้น",
    ) -> bool:
        """Log material usage."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO inventory (
                    employee_line_id, material_name, year, month, quantity, unit
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_line_id, material_name, year, month) DO UPDATE SET
                    quantity = excluded.quantity,
                    unit = excluded.unit,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (employee_line_id, material_name, year, month, quantity, unit),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error logging usage: {e}")
            return False
        finally:
            conn.close()

    # ==================== DRIVE FILES LOG ====================

    def log_drive_file(
        self,
        file_name: str,
        file_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> bool:
        """Log newly detected Drive file."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO drive_files (file_id, file_name, uploaded_by, folder_id)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, file_name, uploaded_by, folder_id),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error logging drive file: {e}")
            return False
        finally:
            conn.close()

    def get_processed_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Check if file has already been processed."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drive_files WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def mark_file_parsed(
        self,
        file_id: str,
        success: bool,
        error_message: Optional[str] = None,
    ) -> bool:
        """Mark file as parsed (success or failed)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE drive_files SET 
                    parsed_at = CURRENT_TIMESTAMP,
                    parsed_successfully = ?,
                    error_message = ?
                WHERE file_id = ?
                """,
                (success, error_message, file_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"Error marking file parsed: {e}")
            return False
        finally:
            conn.close()

    # ==================== ADMIN ACTIONS LOG ====================

    def log_admin_action(
        self,
        admin_line_id: str,
        action: str,
        target: Optional[str] = None,
        parameters: Optional[Dict] = None,
        pin_verified: bool = False,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """Log admin action (with optional target and parameters)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO admin_actions (
                    admin_line_id, action, target, parameters, pin_verified, success, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin_line_id,
                    action,
                    target,
                    json.dumps(parameters or {}),
                    pin_verified,
                    success,
                    error_message,
                ),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error logging admin action: {e}")
            return False
        finally:
            conn.close()

    # ==================== GROQ CACHE ====================

    def cache_groq_response(
        self,
        message_hash: str,
        result: Dict[str, Any],
        ttl_seconds: int = 3600,  # 1 hour
    ) -> bool:
        """Cache Groq intent result."""
        conn = self._get_connection()
        cursor = conn.cursor()

        expires_at = datetime.utcnow().timestamp() + ttl_seconds

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO groq_cache (
                    message_hash, intent, parameters, reply_text, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message_hash,
                    result.get("intent"),
                    json.dumps(result.get("parameters", {})),
                    result.get("reply_text"),
                    expires_at,
                ),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error caching Groq response: {e}")
            return False
        finally:
            conn.close()

    def get_cached_groq_response(self, message_hash: str) -> Optional[Dict[str, Any]]:
        """Get cached Groq result if not expired."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT intent, parameters, reply_text
            FROM groq_cache
            WHERE message_hash = ? AND expires_at > ?
            """,
            (message_hash, datetime.utcnow().timestamp()),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "intent": row["intent"],
                "parameters": json.loads(row["parameters"]),
                "reply_text": row["reply_text"],
            }
        return None

    # ==================== SETTINGS MANAGEMENT ====================

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting by key."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                return row["value"]
            return default

        except Exception as e:
            conn.close()
            return default

    def set_setting(
        self,
        key: str,
        value: str,
        description: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> bool:
        """Set a setting (create or update)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO settings (key, value, description, updated_by, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (key, value, description, updated_by)
            )
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            conn.close()
            return False

    def delete_setting(self, key: str) -> bool:
        """Delete a setting."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            conn.close()
            return False

    def get_all_settings(self) -> Dict[str, str]:
        """Get all settings as a dictionary."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            conn.close()

            return {row["key"]: row["value"] for row in rows}

        except Exception as e:
            conn.close()
            return {}


if __name__ == "__main__":
    # Test database
    db = Database()
    print("Database initialized successfully ✓")

    # Add test super admin if not exists
    from config import Config
    if not db.get_user(Config.LINE_SUPER_ADMIN_ID):
        db.add_user(
            line_user_id=Config.LINE_SUPER_ADMIN_ID,
            display_name="Super Admin",
            excel_name="SuperAdmin",
            role="super_admin",
        )
        print(f"Super admin added: {Config.LINE_SUPER_ADMIN_ID}")
    else:
        print(f"Super admin already exists: {Config.LINE_SUPER_ADMIN_ID}")

    # Test logging drive file
    db.log_drive_file(
        file_name="เอสพี--สถิติเบิกวัสดุสิ้นเปลือง(69).xlsx",
        file_id="1abc123def456",
        folder_id="1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2",
    )
    print("Test drive file logged")

    # Test get_processed_file
    processed = db.get_processed_file("1abc123def456")
    print("Processed file check:", processed)