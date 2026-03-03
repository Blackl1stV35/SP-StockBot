"""
Employee commands for SP-StockBot.
Non-admin queries: check stock, report usage, help.
"""

from typing import Dict, Tuple, Optional, List
from datetime import datetime

from database import Database
from anomaly_detector import AnomalyDetector
from logger import activity_logger


class EmployeeCommands:
    """Handler for employee commands."""

    def __init__(self, db: Database):
        """Initialize employee handler."""
        self.db = db
        self.detector = AnomalyDetector(db)

    def check_inventory(
        self,
        user_id: str,
        material_name: Optional[str] = None,
        months: int = 3,
    ) -> str:
        """
        Check current inventory for employee.
        If material_name is None, show all materials.
        """
        try:
            user = self.db.get_user(user_id)
            if not user:
                return "👤 User not found in system"

            # Get inventory for all materials or specific one
            if material_name:
                records = self.db.get_employee_inventory(
                    user_id, material_name, months=months
                )

                if not records:
                    return (
                        f"No inventory records for {material_name}\n"
                        f"Try: สตอก [material name]"
                    )

                reply = f"📊 {user['display_name']} - {material_name}:\n"
                for record in sorted(
                    records, key=lambda x: (x["year"], x["month"])
                ):
                    qty = record.get("quantity", "-")
                    unit = record.get("unit", "")
                    reply += (
                        f"  {record['year']}-{record['month']:02d}: "
                        f"{qty} {unit}\n"
                    )

                return reply

            else:
                # Show summary for all materials
                all_materials = set()
                latest_records = {}

                # This would require a different query - for now, return summary
                return (
                    f"📊 {user['display_name']}'s Inventory:\n"
                    f"(Use: สตอก [material] for details)\n"
                    f"Contact admin for full inventory list"
                )

        except Exception as e:
            activity_logger.log_error(
                f"Error checking inventory for {user_id}: {e}",
                error_type="check_inventory_error",
            )
            return "Error retrieving inventory"

    def report_usage(
        self,
        user_id: str,
        material_name: str,
        quantity: float,
    ) -> str:
        """
        Report material usage by employee.
        Stores record and checks for anomalies.
        """
        try:
            user = self.db.get_user(user_id)
            if not user:
                return "👤 User not found in system"

            # Get current year/month (Thai calendar)
            now = datetime.now()
            year = now.year + 543  # Convert CE to Thai year
            month = now.month

            # Record usage
            success = self.db.set_inventory(
                employee_line_id=user_id,
                material_name=material_name,
                year=year,
                month=month,
                quantity=quantity,
                unit="units",
            )

            if not success:
                return f"❌ Failed to record usage for {material_name}"

            reply = (
                f"✓ Recorded {quantity} units of {material_name}\n"
                f"Employee: {user['display_name']}\n"
                f"Date: {year}-{month:02d}\n"
            )

            # Check for anomalies
            anomalies = self.detector.detect_for_employee(user_id)
            high_anomalies = [
                a for a in anomalies if a.get("severity") == "High"
            ]

            if high_anomalies:
                reply += "\n⚠️ Anomaly detected:\n"
                for anom in high_anomalies[:2]:
                    reply += f"  • {anom['description']}\n"

            activity_logger.log_admin_action(
                admin_line_id=user_id,
                action="report_usage",
                parameters={
                    "material": material_name,
                    "quantity": quantity,
                },
                success=True,
            )

            return reply

        except Exception as e:
            activity_logger.log_error(
                f"Error reporting usage for {user_id}: {e}",
                error_type="usage_report_error",
            )
            return "Error recording usage"

    def get_status(self, user_id: str) -> str:
        """Get employee's current status."""
        try:
            user = self.db.get_user(user_id)
            if not user:
                return "👤 Unknown user. Please add yourself to system."

            # Check for recent anomalies
            anomalies = self.detector.detect_for_employee(user_id)

            reply = f"👤 {user['display_name']}\n"
            reply += f"📍 Role: {user['role']}\n"

            if anomalies:
                reply += f"\n⚠️ Active anomalies: {len(anomalies)}\n"
                for anom in anomalies[:3]:
                    reply += (
                        f"  • {anom['material_name']}: "
                        f"{anom['deviation_percent']:.0f}% above baseline\n"
                    )
            else:
                reply += "\n✓ No anomalies detected\n"

            return reply

        except Exception as e:
            activity_logger.log_error(
                f"Error getting status for {user_id}: {e}",
                error_type="status_error",
            )
            return "Error retrieving status"

    def extract_command_details(
        self, message: str
    ) -> Tuple[Optional[str], Dict[str, str]]:
        """
        Extract employee command and parameters from message.
        Returns (command_name, parameters_dict)
        """
        msg_lower = message.lower().strip()
        params = {}

        if msg_lower.startswith("สตอก"):
            # Thai: "สตอก [material]" -> check stock
            parts = message.split(maxsplit=1)
            if len(parts) > 1:
                params["material_name"] = parts[1].strip()
            return "check_inventory", params

        elif msg_lower.startswith("check"):
            # English variation
            parts = message.split(maxsplit=1)
            if len(parts) > 1:
                params["material_name"] = parts[1].strip()
            return "check_inventory", params

        elif msg_lower.startswith("ใช้"):
            # Thai: "ใช้ [material] [qty]" -> report usage
            parts = message.split()
            if len(parts) >= 2:
                # Try to parse quantity
                try:
                    qty = float(parts[-1])
                    material = " ".join(parts[1:-1])
                    params["material_name"] = material
                    params["quantity"] = qty
                    return "report_usage", params
                except ValueError:
                    # Last part isn't a number, treat all as material
                    params["material_name"] = " ".join(parts[1:])
                    return "report_usage", params

        elif msg_lower.startswith("usage"):
            # English variation
            parts = message.split()
            if len(parts) >= 2:
                try:
                    qty = float(parts[-1])
                    material = " ".join(parts[1:-1])
                    params["material_name"] = material
                    params["quantity"] = qty
                    return "report_usage", params
                except ValueError:
                    params["material_name"] = " ".join(parts[1:])
                    return "report_usage", params

        elif msg_lower.startswith("status"):
            return "get_status", params

        elif "help" in msg_lower:
            return "help", params

        return None, params

    def get_help_text(self) -> str:
        """Get help text for employees."""
        reply = (
            "📖 Help - Available Commands:\n\n"
            "**Thai Commands:**\n"
            "• สตอก [material] - Check stock levels\n"
            "• ใช้ [material] [qty] - Report usage\n"
            "• สถานะ - Show my status\n"
            "• ช่วย - Show help\n\n"
            "**English Commands:**\n"
            "• check [material] - Check stock\n"
            "• usage [material] [qty] - Report usage\n"
            "• status - Show my status\n"
            "• help - Show this message\n"
        )
        return reply


if __name__ == "__main__":
    # Test employee commands
    db = Database()
    emp = EmployeeCommands(db)

    # Add test employee
    db.add_user(
        line_user_id="U_test_emp",
        display_name="ไผท(โป๊น)",
        excel_name="ไผท(โป๊น)",
        role="employee",
    )

    # Test check inventory
    print("Check inventory:")
    print(emp.check_inventory("U_test_emp", "ทรายอ่อน"))

    # Test report usage
    print("\nReport usage:")
    print(emp.report_usage("U_test_emp", "ทรายอ่อน", 10.5))

    # Test extract command
    print("\nExtract command:")
    cmd, params = emp.extract_command_details("สตอก ทรายอ่อน")
    print(f"Command: {cmd}, Params: {params}")
