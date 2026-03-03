#!/usr/bin/env python
"""
SP-StockBot Startup Validation Test
Run without starting the actual server to verify all dependencies.
"""

import sys
from pathlib import Path

# Add SP-StockBot to path
sp_stockbot_path = Path(__file__).parent / "SP-StockBot"
sys.path.insert(0, str(sp_stockbot_path))

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("[TEST] SP-StockBot Startup Validation Test")
    print("=" * 60)

    # Import main module (this will trigger imports)
    print("\n[IMPORTS] Importing SP-StockBot modules...")
    try:
        # Import all modules to test for import errors
        from config import Config
        print("  OK config")
        
        from logger import activity_logger
        print("  OK logger")
        
        from database import Database
        print("  OK database")
        
        from groq_agent import GroqAgent
        print("  OK groq_agent")
        
        from drive_handler import DriveHandler
        print("  OK drive_handler (Google API imports fixed!)")
        
        from xlsx_parser import XlsxParser
        print("  OK xlsx_parser")
        
        from anomaly_detector import AnomalyDetector
        print("  OK anomaly_detector")
        
        from commands.admin_commands import AdminCommands
        print("  OK admin_commands")
        
        from commands.employee_commands import EmployeeCommands
        print("  OK employee_commands")
        
        print("\nSUCCESS: All imports successful!")
        
    except ImportError as e:
        print(f"\nERROR: Import error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Run startup validation from main module
    print("\n[VALIDATION] Running startup validation...")
    try:
        from main import validate_startup
        
        # Run the validation
        validation_passed = validate_startup()
        
        if validation_passed:
            print("\n" + "=" * 60)
            print("SUCCESS: VALIDATION PASSED!")
            print("=" * 60)
            print("\nYou can now start the bot:")
            print("  python SP-StockBot/main.py")
            print("  OR")
            print("  uvicorn SP-StockBot.main:app --reload")
            print("\n" + "=" * 60 + "\n")
            sys.exit(0)
        else:
            print("\n" + "=" * 60)
            print("FAILED: VALIDATION FAILED")
            print("=" * 60)
            print("\nFix the errors above and try again.\n")
            sys.exit(1)
            
    except Exception as e:
        print(f"\nERROR: Validation error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
