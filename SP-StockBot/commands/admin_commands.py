"""
Administrative commands for SP-StockBot.
Requires PIN verification. Commands: add_user, bulk_add, set_drive, etc.
FULL MULTIMODAL + DRIVE FINAL + GIT CLEAN 2026-03-12
"""

from typing import Dict, List, Optional, Tuple
import json
import re

from config import Config
from database import Database
from groq_agent import GroqAgent
from logger import activity_logger
from drive_handler import DriveHandler


class AdminCommands:
    """Handler for admin-only commands."""

    def __init__(self, db: Database, groq_agent: GroqAgent, drive_handler: Optional[DriveHandler] = None):
        """Initialize admin handler."""
        self.db = db
        self.groq_agent = groq_agent
        self.drive_handler = drive_handler

    def verify_super_admin(self, user_id: str) -> bool:
        """Check if user is super admin."""
        return user_id == Config.LINE_SUPER_ADMIN_ID

    def verify_pin(self, provided_pin: str) -> bool:
        """Verify PIN matches configured super admin PIN."""
        return self.groq_agent.verify_pin(
            provided_pin, Config.SUPER_ADMIN_PIN
        )

    def add_user(
        self,
        display_name: str,
        excel_name: Optional[str] = None,
        role: str = "employee",
        line_user_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Add new user to system and create /Users/[line_user_id]/ folder in Drive.
        
        Args:
            display_name: Thai name (e.g. "ไผท(โป๊น)")
            excel_name: Name as appears in Excel files
            role: "employee" or "super_admin"
            line_user_id: Line user ID (if available from Line webhook)
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            if not display_name:
                return False, "Display name required"

            if role not in ("employee", "super_admin"):
                return False, "Invalid role"

            # Use provided Line ID or generate placeholder
            if not line_user_id:
                # In production, this would come from Line webhook
                line_user_id = f"U_{display_name.replace(' ', '')[:20]}_{int(__import__('time').time())}"

            success = self.db.add_user(
                line_user_id=line_user_id,
                display_name=display_name,
                excel_name=excel_name or display_name,
                role=role,
            )

            if not success:
                return False, "Failed to add user to database"
            
            # Create user folder in Drive
            folder_created = False
            if self.drive_handler and Config.GOOGLE_DRIVE_FOLDER_ID:
                try:
                    folder_name = f"Users/{line_user_id}"
                    folder_id = self.drive_handler.create_user_folder(
                        parent_folder_id=Config.GOOGLE_DRIVE_FOLDER_ID,
                        user_id=line_user_id
                    )
                    if folder_id:
                        activity_logger.logger.info(
                            f"✓ Created Drive folder for user {display_name}: {folder_id}"
                        )
                        folder_created = True
                    else:
                        activity_logger.logger.warning(
                            f"Could not create Drive folder for user {display_name}"
                        )
                except Exception as e:
                    activity_logger.logger.warning(
                        f"[Drive] Error creating user folder for {display_name}: {e}"
                    )
            
            reply = f"✓ User added: {display_name} (Role: {role}, ID: {line_user_id})"
            if folder_created:
                reply += f"\n✓ Drive folder created: /Users/{line_user_id}/"
            
            return True, reply

        except Exception as e:
            activity_logger.log_error(
                f"Error adding user: {e}",
                error_type="add_user_error",
            )
            return False, f"Error: {str(e)}"

    def bulk_add_users(
        self,
        users_data: List[Dict[str, str]],
    ) -> Tuple[int, int, List[str]]:
        """
        Bulk add users from list.
        users_data: [{"display_name": "...", "excel_name": "...", "role": "..."}, ...]
        Returns: (added_count, failed_count, error_list)
        """
        added = 0
        failed = 0
        errors = []

        try:
            for user_data in users_data:
                display_name = user_data.get("display_name", "").strip()
                excel_name = user_data.get("excel_name", display_name).strip()
                role = user_data.get("role", "employee")

                if not display_name:
                    errors.append("Empty display name")
                    failed += 1
                    continue

                success, msg = self.add_user(
                    display_name=display_name,
                    excel_name=excel_name,
                    role=role,
                )

                if success:
                    added += 1
                else:
                    failed += 1
                    errors.append(f"{display_name}: {msg}")

            activity_logger.log_admin_action(
                admin_line_id=Config.LINE_SUPER_ADMIN_ID,
                action="bulk_add_users",
                parameters={
                    "count": len(users_data),
                    "added": added,
                    "failed": failed,
                },
                pin_verified=True,
                success=(failed == 0),
            )

            return added, failed, errors

        except Exception as e:
            activity_logger.log_error(
                f"Error in bulk add: {e}",
                error_type="bulk_add_error",
            )
            return added, failed, [str(e)]

    def list_users(self, role: Optional[str] = None) -> str:
        """List all users, optionally filtered by role."""
        try:
            users = self.db.get_all_users(role=role)

            if not users:
                return "No users found"

            reply = f"📋 Users ({len(users)}):\n"
            for user in users:
                reply += (
                    f"• {user['display_name']} "
                    f"({user.get('excel_name', '-')}) "
                    f"[{user['role']}]\n"
                )

            return reply

        except Exception as e:
            activity_logger.log_error(
                f"Error listing users: {e}",
                error_type="list_users_error",
            )
            return "Error retrieving user list"

    def delete_user(self, user_id: str) -> Tuple[bool, str]:
        """Delete user from system."""
        try:
            user = self.db.get_user(user_id)
            if not user:
                return False, "User not found"

            success = self.db.delete_user(user_id)

            if success:
                activity_logger.log_admin_action(
                    admin_line_id=Config.LINE_SUPER_ADMIN_ID,
                    action="delete_user",
                    target_user=user_id,
                    pin_verified=True,
                )
                return True, f"✓ Deleted user: {user['display_name']}"
            else:
                return False, "Failed to delete user"

        except Exception as e:
            activity_logger.log_error(
                f"Error deleting user: {e}",
                error_type="delete_user_error",
            )
            return False, f"Error: {str(e)}"

    def set_drive_folder(
        self,
        drive_folder_input: str,
    ) -> Tuple[bool, str]:
        """
        Set primary Google Drive folder for uploads.
        Accepts full URL or folder ID.
        Admin should share the folder with bot's service account first.
        Saves to both DB and Config for persistence.
        """
        try:
            if not drive_folder_input:
                return False, "❌ Drive folder URL or ID required"

            # Parse folder ID from URL or bare ID
            folder_id = self._extract_drive_id_from_url(drive_folder_input.strip())
            
            if not folder_id:
                return False, "❌ Invalid Drive folder URL or ID format"

            # Validate folder ID format (Google Drive IDs are typically 33 chars, alphanumeric + - and _)
            if not re.match(r'^[a-zA-Z0-9\-_]{20,}$', folder_id):
                return False, f"❌ Invalid folder ID format: {folder_id}"

            # Save to database (persistent)
            success_db = self.db.set_setting(
                key="GOOGLE_DRIVE_FOLDER_ID",
                value=folder_id,
                description="Primary Google Drive folder for inventory file uploads",
                updated_by=Config.LINE_SUPER_ADMIN_ID,
            )

            if not success_db:
                return False, "❌ Failed to save folder ID to database"

            # Update Config in-memory
            Config.GOOGLE_DRIVE_FOLDER_ID = folder_id

            # Log the action
            activity_logger.log_admin_action(
                admin_line_id=Config.LINE_SUPER_ADMIN_ID,
                action="set_drive_folder",
                parameters={"folder_id": folder_id},
                pin_verified=True,
                success=True,
            )

            return (
                True,
                f"✓ Drive folder SAVED:\n"
                f"Folder ID: {folder_id}\n\n"
                f"✅ Persistent storage: Database\n"
                f"✅ Memory: Config.GOOGLE_DRIVE_FOLDER_ID\n\n"
                f"Bot will now scan this folder every 15 minutes."
            )

        except Exception as e:
            activity_logger.log_error(
                f"Error setting drive folder: {e}",
                error_type="set_drive_error",
            )
            return False, f"❌ Error: {str(e)}"

    def get_system_stats(self) -> str:
        """Get system statistics."""
        try:
            users = self.db.get_all_users()
            employees = [u for u in users if u["role"] == "employee"]
            admins = [u for u in users if u["role"] == "super_admin"]

            reply = (
                "📊 System Statistics:\n"
                f"• Total Users: {len(users)}\n"
                f"• Employees: {len(employees)}\n"
                f"• Super Admins: {len(admins)}\n"
            )

            return reply

        except Exception as e:
            activity_logger.log_error(
                f"Error getting system stats: {e}",
                error_type="stats_error",
            )
            return "Error retrieving statistics"

    def extract_command_details(
        self, message: str
    ) -> Tuple[Optional[str], Dict[str, str]]:
        """
        Extract admin command and parameters from message.
        Returns (command_name, parameters_dict)
        Examples:
        - "Add user ไผท(โป๊น) PIN:7482" -> ("add_user", {"display_name": "ไผท(โป๊น)", "pin": "7482"})
        - "List users" -> ("list_users", {})
        - "Set drive https://drive.google.com/... PIN:7482" -> ("set_drive", {"url": "...", "pin": "7482"})
        """
        msg_lower = message.lower().strip()
        params = {}

        # Extract PIN if present
        pin = self.groq_agent.extract_pin_from_message(message)
        if pin:
            params["pin"] = pin

        # Determine command
        if msg_lower.startswith("add user"):
            params["display_name"] = message.replace("Add user", "").replace(
                "add user", ""
            ).split("PIN:")[0].strip()
            return "add_user", params

        elif msg_lower.startswith("list users"):
            return "list_users", params

        elif msg_lower.startswith("list employees"):
            params["role"] = "employee"
            return "list_users", params

        elif msg_lower.startswith("delete user"):
            params["user_id"] = message.replace("Delete user", "").replace(
                "delete user", ""
            ).split("PIN:")[0].strip()
            return "delete_user", params

        elif msg_lower.startswith("set drive"):
            # Extract URL (rough parsing)
            url_match = message[message.find("http") :]
            url = url_match.split()[0] if "http" in url_match else ""
            if url:
                params["drive_folder_id"] = self._extract_drive_id_from_url(url)
            return "set_drive", params

        elif "help" in msg_lower:
            return "help", params

        return None, params

    def _extract_drive_id_from_url(self, url: str) -> Optional[str]:
        """
        Extract Drive folder ID from sharing link with regex.
        Supports formats:
        - https://drive.google.com/drive/folders/1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2?usp=sharing
        - https://drive.google.com/drive/folders/1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2
        - 1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2 (bare ID)
        """
        if not url:
            return None
        
        # If it looks like a folder ID already (alphanumeric with - and _)
        if re.match(r'^[a-zA-Z0-9\-_]{20,}$', url.strip()):
            return url.strip()
        
        # Try regex patterns for different Google Drive URL formats
        patterns = [
            r'/folders/([a-zA-Z0-9\-_]+)',  # /folders/{ID}
            r'/drive/folders/([a-zA-Z0-9\-_]+)',  # /drive/folders/{ID}
            r'[?&]id=([a-zA-Z0-9\-_]+)',  # ?id={ID}
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                folder_id = match.group(1)
                if len(folder_id) >= 20:  # Google Drive folder IDs are typically 33 chars
                    return folder_id
        
        # Fallback: return the original if it seems to be an ID
        if url.strip() and len(url.strip()) > 10:
            return url.strip()
        
        return None

    def get_help_text(self, is_admin: bool = False) -> str:
        """Get help text for user."""
        reply = "📖 Help - Available Commands:\n\n"

        if not is_admin:
            reply += "**Employee Commands:**\n"
            reply += "• สตอก [material] - Check current stock\n"
            reply += "• ใช้ [material] [qty] - Report usage\n"
            reply += "• Help - Show this message\n"
        else:
            reply += "**Admin Commands** (require PIN):\n"
            reply += "• Add user [name] PIN:[code] - Add employee\n"
            reply += "• List users - List all users\n"
            reply += "• Delete user [id] PIN:[code] - Remove user\n"
            reply += "• Set drive [URL] PIN:[code] - Configure Drive folder\n"
            reply += "• System stats - Show statistics\n"
            reply += "• Help - Show this message\n"

        return reply


if __name__ == "__main__":
    # Test admin commands
    from groq_agent import get_groq_agent

    db = Database()
    agent = get_groq_agent(db)
    admin = AdminCommands(db, agent)

    # Test add user
    success, msg = admin.add_user(
        display_name="ไผท(โป๊น)",
        excel_name="ไผท(โป๊น)",
        role="employee",
    )
    print(f"Add user: {msg}")

    # Test list users
    print(admin.list_users())

    # Test stats
    print(admin.get_system_stats())
