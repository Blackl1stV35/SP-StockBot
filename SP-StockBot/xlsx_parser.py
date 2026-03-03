"""
Excel (.xlsx) parser for SP-StockBot inventory files.
Handles multi-sheet parsing, data validation, and employee mapping.
Memory-optimized with chunking and garbage collection.
"""

import gc
import re
from typing import Optional, List, Dict, Tuple, Any
from pathlib import Path
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
import pandas as pd

from config import Config
from database import Database
from logger import activity_logger


class XlsxParser:
    """Excel file parser for inventory data."""

    # Common Thai material names (can be extended)
    KNOWN_MATERIALS = [
        "ทรายอ่อน",  # sandpaper
        "น้ำมันเครื่อง",  # engine oil
        "คำเตอร์",  # color
        "สนิม",  # rust
        "แว็กซ์",  # wax
        "สไปรย์",  # spray
        "เชื้อเพลิง",  # fuel
    ]

    def __init__(self, db: Database):
        """Initialize parser with database reference."""
        self.db = db

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse XLSX file and update database.
        Returns summary of parsing results.
        """
        try:
            if not Path(file_path).exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Load workbook
            wb = openpyxl.load_workbook(file_path, data_only=True)

            summary = {
                "file_name": Path(file_path).name,
                "sheets_processed": 0,
                "records_added": 0,
                "records_updated": 0,
                "errors": [],
                "employee_mappings": {},
            }

            # Process each sheet
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                if self._is_valid_sheet(ws, sheet_name):
                    result = self._parse_sheet(ws, sheet_name)
                    summary["sheets_processed"] += 1
                    summary["records_added"] += result["added"]
                    summary["records_updated"] += result["updated"]
                    summary["errors"].extend(result["errors"])
                    summary["employee_mappings"].update(
                        result["employee_mappings"]
                    )

            wb.close()

            # Force garbage collection after processing
            gc.collect()

            activity_logger.log_inventory_update(
                user_id="system",
                file_name=summary["file_name"],
                sheets_processed=summary["sheets_processed"],
                records_added=summary["records_added"],
                records_updated=summary["records_updated"],
            )

            return summary

        except Exception as e:
            activity_logger.log_error(
                f"Failed to parse Excel file: {e}",
                error_type="xlsx_parse_error",
            )
            return {
                "file_name": Path(file_path).name,
                "sheets_processed": 0,
                "records_added": 0,
                "records_updated": 0,
                "errors": [str(e)],
                "employee_mappings": {},
            }

    def _is_valid_sheet(self, ws: Worksheet, sheet_name: str) -> bool:
        """Check if sheet follows expected format (month sheet)."""
        # Expected format: "เดือน1-69", "เดือน2-69", etc.
        month_pattern = r"เดือน\d+[-–]\d{2,4}"
        return bool(re.match(month_pattern, sheet_name))

    def _parse_sheet(
        self, ws: Worksheet, sheet_name: str
    ) -> Dict[str, Any]:
        """Parse single sheet."""
        result = {
            "added": 0,
            "updated": 0,
            "errors": [],
            "employee_mappings": {},
        }

        try:
            # Extract year/month from sheet name
            match = re.search(r"เดือน(\d+)[-–](\d{2,4})", sheet_name)
            if not match:
                result["errors"].append(f"Invalid sheet name: {sheet_name}")
                return result

            month = int(match.group(1))
            year = int(match.group(2))

            # Convert Thai year to CE (simplistic)
            if year >= 2400:
                year = year - 543

            # Convert to pandas for easier manipulation
            df = pd.read_excel(
                io.BytesIO(
                    open(ws.parent.filename, "rb").read()
                ),  # Better: use proper Excel read
                sheet_name=sheet_name,
                header=None,
            )

            if df.empty:
                return result

            # Find header row (usually first row with meaningful data)
            material_row, employee_col_start = self._find_headers(df, ws)
            if material_row is None:
                result["errors"].append(
                    f"Could not find headers in {sheet_name}"
                )
                return result

            # Extract materials (columns)
            materials = self._extract_materials(df, material_row)

            # Extract employees (rows below header)
            for row_idx in range(material_row + 1, df.shape[0]):
                employee_name = df.iloc[row_idx, 0]

                if not employee_name or pd.isna(employee_name):
                    continue

                employee_name = str(employee_name).strip()

                # Look up employee in database
                user = self.db.get_user(employee_name)
                if not user:
                    # Try matching by excel_name
                    users = self.db.get_all_users()
                    user = next(
                        (
                            u
                            for u in users
                            if u.get("excel_name") == employee_name
                        ),
                        None,
                    )

                if not user:
                    result["errors"].append(
                        f"Employee not found: {employee_name}"
                    )
                    continue

                employee_line_id = user["line_user_id"]
                result["employee_mappings"][employee_name] = (
                    employee_line_id
                )

                # Process material quantities for this employee
                for col_idx, material_name in enumerate(
                    materials, start=employee_col_start
                ):
                    quantity = df.iloc[row_idx, col_idx]

                    # Parse quantity (handle "5+" format)
                    parsed_qty = self._parse_quantity(quantity)
                    if parsed_qty is None:
                        continue

                    # Update database
                    success = self.db.set_inventory(
                        employee_line_id=employee_line_id,
                        material_name=material_name,
                        year=year,
                        month=month,
                        quantity=parsed_qty,
                        unit="units",
                    )

                    if success:
                        result["updated"] += 1
                    else:
                        result["added"] += 1

            gc.collect()
            return result

        except Exception as e:
            result["errors"].append(f"Error parsing sheet {sheet_name}: {e}")
            return result

    def _find_headers(
        self, df: pd.DataFrame, ws: Worksheet
    ) -> Tuple[Optional[int], int]:
        """
        Find material header row and first employee column.
        Returns (header_row_index, employee_col_start) or (None, 0).
        """
        # Usually first row with data, or first row with Thai text
        for idx in range(min(5, df.shape[0])):
            row_data = df.iloc[idx].astype(str)

            # Check if row has material names (Thai or English)
            thai_count = sum(
                1
                for cell in row_data
                if any(
                    ord(c) >= 0x0E00 and ord(c) <= 0x0E7F
                    for c in str(cell)
                )
            )

            if thai_count > 2:  # At least 3 Thai characters indicate materials
                return idx, 1  # Assume first column is employee name

        return None, 0

    def _extract_materials(
        self, df: pd.DataFrame, header_row: int
    ) -> List[str]:
        """Extract material names from header row."""
        materials = []
        for col_idx in range(1, df.shape[1]):
            cell = str(df.iloc[header_row, col_idx]).strip()
            if cell and cell != "nan":
                materials.append(cell)

        return materials

    def _parse_quantity(self, value: Any) -> Optional[float]:
        """
        Parse quantity value.
        Handles:
        - "5" -> 5.0
        - "5.5" -> 5.5
        - "5+" -> 5.0
        - "10 units" -> 10.0
        - None, NaN -> None
        """
        if value is None or pd.isna(value):
            return None

        value_str = str(value).strip()

        if not value_str or value_str == "nan":
            return None

        try:
            # Remove non-numeric characters except dot
            cleaned = re.sub(r"[^\d.]", "", value_str)

            if not cleaned:
                return None

            return float(cleaned)

        except ValueError:
            return None


def parse_excel_file(file_path: str, db: Database) -> Dict[str, Any]:
    """Convenience function to parse Excel file."""
    parser = XlsxParser(db)
    return parser.parse_file(file_path)


if __name__ == "__main__":
    # Test parser
    db = Database()
    parser = XlsxParser(db)

    # Test with sample file if exists
    test_file = Path(__file__).parent / "test_inventory.xlsx"
    if test_file.exists():
        result = parser.parse_file(str(test_file))
        print("Parse result:")
        print(f"Sheets: {result['sheets_processed']}")
        print(f"Records added: {result['records_added']}")
        print(f"Records updated: {result['records_updated']}")
        if result["errors"]:
            print("Errors:")
            for error in result["errors"]:
                print(f"  - {error}")
    else:
        print("No test file found")
