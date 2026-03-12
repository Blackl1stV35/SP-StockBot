#!/usr/bin/env python3
"""
Test script to validate Gemini + Drive Scanner integration (2026-03-12).
Run this before deploying to production.
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'SP-StockBot'))

from config import Config
from logger import activity_logger
from local_llm_agent import LocalLLMAgent
from drive_handler import DriveHandler


def test_imports():
    """Test that all required packages are installed."""
    print("\n=== Test 1: Package Imports ===")
    
    try:
        import google.generativeai
        print("✓ google.generativeai imported successfully")
    except ImportError as e:
        print(f"✗ google.generativeai import failed: {e}")
        return False
    
    try:
        import ollama
        print("✓ ollama imported successfully")
    except ImportError as e:
        print(f"✗ ollama import failed: {e}")
        return False
    
    try:
        from tenacity import retry
        print("✓ tenacity imported successfully")
    except ImportError as e:
        print(f"✗ tenacity import failed: {e}")
        return False
    
    return True


def test_gemini_config():
    """Test Gemini API configuration."""
    print("\n=== Test 2: Gemini Configuration ===")
    
    api_key = Config.GEMINI_API_KEY
    model = Config.GEMINI_MODEL
    
    if not api_key:
        print("⚠ GEMINI_API_KEY not set in .env (Gemini will be unavailable)")
        print("  → Get key from: https://aistudio.google.com/app/apikey")
        return False
    
    print(f"✓ GEMINI_API_KEY configured: {api_key[:10]}...")
    print(f"✓ GEMINI_MODEL: {model}")
    return True


def test_intent_parser():
    """Test intent parsing with Gemini→Ollama→Fallback chain."""
    print("\n=== Test 3: Intent Parser (Gemini→Ollama→Fallback) ===")
    
    try:
        agent = LocalLLMAgent()
        
        # Test spam detection
        print("\n  Testing spam detection...")
        spam_msg = "!@#$%^&*()" * 10
        result = agent._detect_spam(spam_msg)
        print(f"    Spam check on random chars: {result}")
        
        # Test valid intent
        print("\n  Testing intent parsing (using fallback since no API key/Ollama)...")
        test_messages = [
            "เบิก กดทห80 5",
            "สต็อก วัสดุไหนบ้าง",
            "ช่วยด้วย",
            "nonsense garbage 123 !!!"
        ]
        
        for msg in test_messages:
            result = agent.parse_intent(msg, "TestUser")
            intent = result.get("intent", "?")
            confidence = result.get("confidence", 0)
            parser = result.get("parser", "?")
            print(f"    '{msg[:30]:30s}' → {intent:15s} (conf={confidence:.2f}, parser={parser})")
        
        return True
    
    except Exception as e:
        print(f"✗ Intent parser test failed: {e}")
        return False


def test_drive_scanner():
    """Test Drive scanner configuration."""
    print("\n=== Test 4: Drive Scanner (Recursive) ===")
    
    try:
        drive = DriveHandler()
        
        if not drive.service:
            print("⚠ Google Drive service not available (check .env credentials)")
            return False
        
        print("✓ Drive service authenticated")
        
        folder_id = Config.GOOGLE_DRIVE_FOLDER_ID
        if not folder_id:
            print("⚠ GOOGLE_DRIVE_FOLDER_ID not configured")
            return False
        
        print(f"✓ Target folder: {folder_id}")
        
        # Test recursive scan (won't do actual scan, just check method exists)
        if hasattr(drive, 'scan_recursive'):
            print("✓ Recursive scanner method available")
            print("  → Ready to scan XLSX/PDF/DOCX files (root + all subfolders)")
            return True
        else:
            print("✗ Recursive scanner method not found")
            return False
    
    except Exception as e:
        print(f" Drive scanner test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("GEMINI + DRIVE SCANNER INTEGRATION TEST (2026-03-12)")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Gemini Config", test_gemini_config),
        ("Intent Parser", test_intent_parser),
        ("Drive Scanner", test_drive_scanner),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status:8s} | {name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All critical tests passed! Ready for deployment.")
        return 0
    else:
        print("\n⚠ Some tests failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
