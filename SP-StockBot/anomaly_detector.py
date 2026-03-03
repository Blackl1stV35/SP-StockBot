"""
Anomaly detection for SP-StockBot.
Detects unusual material consumption patterns using statistical analysis.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import statistics

from config import Config
from database import Database
from logger import activity_logger


class AnomalyDetector:
    """Detect anomalies in material consumption patterns."""

    def __init__(self, db: Database):
        """Initialize detector."""
        self.db = db
        self.threshold_multiplier = Config.ANOMALY_THRESHOLD_MULTIPLIER
        self.lookback_months = Config.ANOMALY_LOOKBACK_MONTHS

    def detect_for_employee(
        self,
        employee_line_id: str,
    ) -> List[Dict]:
        """
        Detect anomalies for a specific employee.
        Returns list of anomaly dictionaries.
        """
        anomalies = []

        try:
            # Get all materials for this employee
            user = self.db.get_user(employee_line_id)
            if not user:
                return anomalies

            # Get inventory history
            inventory = self.db.get_employee_inventory(
                employee_line_id, "%", months=self.lookback_months
            )

            # Group by material
            materials_data: Dict[str, List[float]] = {}
            for record in inventory:
                material = record["material_name"]
                quantity = record["quantity"]

                if quantity is not None:
                    if material not in materials_data:
                        materials_data[material] = []
                    materials_data[material].append(quantity)

            # Analyze each material
            for material_name, quantities in materials_data.items():
                if len(quantities) < 2:
                    continue  # Need at least 2 data points

                anomaly = self._detect_anomaly(
                    employee_line_id, material_name, quantities
                )

                if anomaly:
                    anomalies.append(anomaly)
                    activity_logger.log_anomaly_detection(
                        employee_line_id,
                        material_name,
                        anomaly["severity"],
                        anomaly["deviation_percent"],
                    )

            return anomalies

        except Exception as e:
            activity_logger.log_error(
                f"Error detecting anomalies for {employee_line_id}: {e}",
                error_type="anomaly_detection_error",
            )
            return anomalies

    def _detect_anomaly(
        self,
        employee_line_id: str,
        material_name: str,
        quantities: List[float],
    ) -> Optional[Dict]:
        """
        Detect anomaly in time series data.
        Uses mean + std deviation for threshold.
        """
        try:
            if not quantities or len(quantities) < 2:
                return None

            # Calculate baseline from all but last value
            baseline_values = quantities[:-1]
            current_value = quantities[-1]

            baseline_mean = statistics.mean(baseline_values)
            baseline_std = (
                statistics.stdev(baseline_values)
                if len(baseline_values) > 1
                else baseline_mean * 0.1
            )

            # Threshold: mean + (std * multiplier)
            threshold = baseline_mean + (
                baseline_std * self.threshold_multiplier
            )

            # Check for anomaly
            if current_value > threshold:
                deviation_percent = (
                    (current_value - baseline_mean) / baseline_mean * 100
                )

                # Determine severity
                if deviation_percent > 100:
                    severity = "High"
                elif deviation_percent > 50:
                    severity = "Medium"
                else:
                    severity = "Low"

                # Get employee name
                user = self.db.get_user(employee_line_id)
                employee_name = user.get("display_name", "Unknown")

                description = (
                    f"{employee_name} used {deviation_percent:.0f}% more "
                    f"{material_name} than baseline"
                )

                anomaly = {
                    "employee_line_id": employee_line_id,
                    "employee_name": employee_name,
                    "material_name": material_name,
                    "anomaly_type": "high_usage",
                    "severity": severity,
                    "description": description,
                    "current_value": current_value,
                    "baseline_value": baseline_mean,
                    "baseline_std": baseline_std,
                    "deviation_percent": deviation_percent,
                    "threshold": threshold,
                }

                # Store in database
                self.db.record_anomaly(
                    employee_line_id=employee_line_id,
                    material_name=material_name,
                    anomaly_type="high_usage",
                    severity=severity,
                    description=description,
                    current_value=current_value,
                    baseline_value=baseline_mean,
                    deviation_percent=deviation_percent,
                )

                return anomaly

            return None

        except Exception as e:
            activity_logger.log_error(
                f"Error in anomaly calculation: {e}",
                error_type="anomaly_calc_error",
            )
            return None

    def detect_batch(self) -> List[Dict]:
        """
        Detect anomalies for all employees.
        Returns list of all anomalies found.
        """
        all_anomalies = []

        try:
            users = self.db.get_all_users(role="employee")

            for user in users:
                anomalies = self.detect_for_employee(user["line_user_id"])
                all_anomalies.extend(anomalies)

            return all_anomalies

        except Exception as e:
            activity_logger.log_error(
                f"Error in batch anomaly detection: {e}",
                error_type="batch_anomaly_error",
            )
            return []

    def get_unnotified_anomalies(self) -> List[Dict]:
        """Get anomalies not yet notified to admin."""
        try:
            anomalies = self.db.get_unnotified_anomalies()
            return [dict(anom) for anom in anomalies]

        except Exception as e:
            activity_logger.log_error(
                f"Error retrieving unnotified anomalies: {e}",
                error_type="retrieve_anomaly_error",
            )
            return []

    def get_summary_stats(self) -> Dict:
        """Get anomaly summary statistics."""
        try:
            all_anomalies = self.get_unnotified_anomalies()

            return {
                "total_count": len(all_anomalies),
                "high_count": sum(
                    1 for a in all_anomalies if a.get("severity") == "High"
                ),
                "medium_count": sum(
                    1 for a in all_anomalies if a.get("severity") == "Medium"
                ),
                "low_count": sum(
                    1 for a in all_anomalies if a.get("severity") == "Low"
                ),
                "top_anomalies": sorted(
                    all_anomalies,
                    key=lambda x: x.get("deviation_percent", 0),
                    reverse=True,
                )[:5],
            }

        except Exception as e:
            activity_logger.log_error(
                f"Error calculating summary stats: {e}",
                error_type="stats_error",
            )
            return {
                "total_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "top_anomalies": [],
            }


if __name__ == "__main__":
    # Test anomaly detection
    db = Database()
    detector = AnomalyDetector(db)

    print("Running anomaly detection...")
    all_anomalies = detector.detect_batch()

    print(f"Found {len(all_anomalies)} anomalies")
    for anom in all_anomalies[:5]:
        print(f"  - {anom['description']} ({anom['severity']})")

    # Get summary
    stats = detector.get_summary_stats()
    print(f"\nSummary:")
    print(f"  High: {stats['high_count']}")
    print(f"  Medium: {stats['medium_count']}")
    print(f"  Low: {stats['low_count']}")
