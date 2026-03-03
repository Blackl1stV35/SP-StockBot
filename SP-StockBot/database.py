"""
Database layer for SP-StockBot.
SQLite schema and CRUD operations for users, inventory, and anomalies.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any
from config import Config


class Database:
    """SQLite database manager with schema initialization."""

    def __init__(self, db_path: str = Config.DATABASE_PATH):
        """Initialize database connection and create tables if needed."""
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
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
        # Stores material usage per employee per month
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
        # Stored detected anomalies for reporting
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_line_id TEXT NOT NULL,
                material_name TEXT NOT NULL,
                anomaly_type TEXT,
                severity TEXT CHECK(severity IN ('Low', 'Medium', 'High')),
                description TEXT,
                current_value REAL,
                baseline_value REAL,
                deviation_percent REAL,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notified_at TIMESTAMP,
                FOREIGN KEY (employee_line_id) REFERENCES users(line_user_id)
            )
        """)

        # ==================== GROQ CACHE TABLE ====================
        # Cache LLM responses to reduce API calls
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groq_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_hash TEXT UNIQUE NOT NULL,
                intent TEXT,
                parameters TEXT,
                reply_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        """)

        # ==================== GOOGLE DRIVE MAPPINGS ====================
        # Track uploaded files and their metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drive_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                file_id TEXT UNIQUE,
                uploaded_by TEXT,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                parsed_at TIMESTAMP,
                parsed_successfully BOOLEAN,
                error_message TEXT,
                FOREIGN KEY (uploaded_by) REFERENCES users(line_user_id)
            )
        """)

        # ==================== ADMIN ACTIONS LOG ====================
        # Audit trail for administrative actions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_line_id TEXT NOT NULL,
                action_type TEXT,
                target_user TEXT,
                parameters TEXT,
                pin_verified BOOLEAN,
                status TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_line_id) REFERENCES users(line_user_id)
            )
        """)

        conn.commit()
        conn.close()

    # ==================== USER MANAGEMENT ====================

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
            return True
        except sqlite3.IntegrityError as e:
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

        if row:
            return dict(row)
        return None

    def get_all_users(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all users, optionally filtered by role."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if role:
            cursor.execute("SELECT * FROM users WHERE role = ?", (role,))
        else:
            cursor.execute("SELECT * FROM users")

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def delete_user(self, line_user_id: str) -> bool:
        """Delete a user."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM users WHERE line_user_id = ?", (line_user_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ==================== INVENTORY MANAGEMENT ====================

    def set_inventory(
        self,
        employee_line_id: str,
        material_name: str,
        year: int,
        month: int,
        quantity: Optional[float],
        unit: Optional[str] = None,
    ) -> bool:
        """Set inventory quantity for employee/material/month."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO inventory 
                (employee_line_id, material_name, year, month, quantity, unit)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_line_id, material_name, year, month) DO UPDATE SET
                    quantity = excluded.quantity,
                    unit = excluded.unit,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (employee_line_id, material_name, year, month, quantity, unit),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Error setting inventory: {e}")
            return False
        finally:
            conn.close()

    def get_inventory(
        self,
        employee_line_id: str,
        material_name: str,
        year: int,
        month: int,
    ) -> Optional[Dict[str, Any]]:
        """Get specific inventory record."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM inventory 
            WHERE employee_line_id = ? AND material_name = ? 
            AND year = ? AND month = ?
            """,
            (employee_line_id, material_name, year, month),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def get_employee_inventory(
        self,
        employee_line_id: str,
        material_name: str,
        months: int = 3,
    ) -> List[Dict[str, Any]]:
        """Get last N months of inventory for employee/material."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM inventory 
            WHERE employee_line_id = ? AND material_name = ?
            ORDER BY year DESC, month DESC
            LIMIT ?
            """,
            (employee_line_id, material_name, months),
        )
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    # ==================== ANOMALY MANAGEMENT ====================

    def record_anomaly(
        self,
        employee_line_id: str,
        material_name: str,
        anomaly_type: str,
        severity: str,
        description: str,
        current_value: float,
        baseline_value: float,
        deviation_percent: float,
    ) -> bool:
        """Record detected anomaly."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO anomalies 
                (employee_line_id, material_name, anomaly_type, severity, 
                 description, current_value, baseline_value, deviation_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_line_id,
                    material_name,
                    anomaly_type,
                    severity,
                    description,
                    current_value,
                    baseline_value,
                    deviation_percent,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Error recording anomaly: {e}")
            return False
        finally:
            conn.close()

    def get_unnotified_anomalies(self) -> List[Dict[str, Any]]:
        """Get anomalies that haven't been notified yet."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM anomalies 
            WHERE notified_at IS NULL
            ORDER BY severity DESC, detected_at DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def mark_anomaly_notified(self, anomaly_id: int) -> bool:
        """Mark anomaly as notified."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "UPDATE anomalies SET notified_at = CURRENT_TIMESTAMP WHERE id = ?",
                (anomaly_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ==================== GROQ CACHE ====================

    def get_cached_groq_response(self, message_hash: str) -> Optional[Dict[str, Any]]:
        """Get cached Groq response."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT intent, parameters, reply_text FROM groq_cache 
            WHERE message_hash = ? AND (expires_at IS NULL OR expires_at > datetime('now'))
            """,
            (message_hash,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "intent": row[0],
                "parameters": json.loads(row[1] or "{}"),
                "reply_text": row[2],
            }
        return None

    def cache_groq_response(
        self,
        message_hash: str,
        intent: str,
        parameters: dict,
        reply_text: str,
        ttl_hours: int = 24,
    ) -> bool:
        """Cache Groq response."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO groq_cache 
                (message_hash, intent, parameters, reply_text, expires_at)
                VALUES (?, ?, ?, ?, datetime('now', '+' || ? || ' hours'))
                ON CONFLICT(message_hash) DO UPDATE SET
                    intent = excluded.intent,
                    parameters = excluded.parameters,
                    reply_text = excluded.reply_text
                """,
                (message_hash, intent, json.dumps(parameters), reply_text, ttl_hours),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Error caching response: {e}")
            return False
        finally:
            conn.close()

    # ==================== ADMIN ACTIONS LOG ====================

    def log_admin_action(
        self,
        admin_line_id: str,
        action_type: str,
        target_user: Optional[str] = None,
        parameters: Optional[dict] = None,
        pin_verified: bool = False,
        status: str = "completed",
        error_message: Optional[str] = None,
    ) -> bool:
        """Log administrative action for audit trail."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO admin_actions 
                (admin_line_id, action_type, target_user, parameters, 
                 pin_verified, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admin_line_id,
                    action_type,
                    target_user,
                    json.dumps(parameters or {}),
                    pin_verified,
                    status,
                    error_message,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Error logging action: {e}")
            return False
        finally:
            conn.close()

    # ==================== DRIVE FILES LOG ====================

    def log_drive_file(
        self,
        file_name: str,
        file_id: Optional[str] = None,
        uploaded_by: Optional[str] = None,
    ) -> bool:
        """Log uploaded drive file."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO drive_files (file_name, file_id, uploaded_by)
                VALUES (?, ?, ?)
                """,
                (file_name, file_id, uploaded_by),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            print(f"Error logging drive file: {e}")
            return False
        finally:
            conn.close()

    def mark_file_parsed(
        self,
        file_id: str,
        success: bool,
        error_message: Optional[str] = None,
    ) -> bool:
        """Mark file as parsed."""
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
        finally:
            conn.close()


if __name__ == "__main__":
    # Test database initialization
    db = Database()
    print("Database initialized successfully ✓")

    # Add test super admin
    from config import Config
    db.add_user(
        line_user_id=Config.LINE_SUPER_ADMIN_ID,
        display_name="Super Admin",
        excel_name="SuperAdmin",
        role="super_admin",
    )
    print(f"Test user added: {Config.LINE_SUPER_ADMIN_ID}")

    # List all users
    users = db.get_all_users()
    print(f"Total users: {len(users)}")
