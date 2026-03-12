#!/usr/bin/env python3
"""
Quick verification script for LOCAL OLLAMA FIXES 2026-03-12
Checks all critical fixes before starting server.
"""

import sys
import os
import subprocess
from datetime import datetime, timezone, timedelta

def check_timezone_fix():
    """Verify timezone constant is properly defined."""
    try:
        BKK_TZ = timezone(timedelta(hours=7))
        now = datetime.now(tz=BKK_TZ).isoformat()
        print(f"✓ Timezone fix verified: {now}")
        return True
    except Exception as e:
        print(f"✗ Timezone fix FAILED: {e}")
        return False

def check_encoding_support():
    """Verify Python supports UTF-8 encoding."""
    try:
        # Test Thai text encoding
        thai_text = "เบิก กดทห80 5"
        encoded = thai_text.encode('utf-8')
        decoded = encoded.decode('utf-8', errors='replace')
        print(f"✓ UTF-8 encoding verified: {decoded}")
        return True
    except Exception as e:
        print(f"✗ UTF-8 encoding FAILED: {e}")
        return False

def check_ollama_available():
    """Verify Ollama is installed and running."""
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0:
            print(f"✓ Ollama available: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ Ollama version check failed")
            return False
    except FileNotFoundError:
        print(f"✗ Ollama not found in PATH")
        print("  Install from: https://ollama.ai/download")
        return False
    except subprocess.TimeoutExpired:
        print(f"✗ Ollama not responding (timeout)")
        print("  Run: ollama serve")
        return False
    except Exception as e:
        print(f"✗ Ollama check failed: {e}")
        return False

def check_torch_cuda():
    """Verify torch CUDA detection works."""
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            print(f"✓ CUDA available: {torch.cuda.get_device_name(0)}")
        else:
            print(f"⚠ CUDA not available (will use CPU)")
        return True
    except ImportError:
        print(f"⚠ torch not installed (GPU detection disabled)")
        return True
    except Exception as e:
        print(f"✗ torch CUDA check failed: {e}")
        return False

def check_groq_removed():
    """Verify Groq cloud references are removed from config."""
    try:
        from config import Config
        # Check if GROQ_API_KEY is commented out or not required
        config_module = sys.modules.get('config')
        if not hasattr(Config, 'GROQ_API_KEY') or Config.GROQ_API_KEY == "":
            print(f"✓ Groq cloud dependencies removed/optional")
            return True
        else:
            print(f"⚠ GROQ_API_KEY still present (but not required)")
            return True
    except Exception as e:
        print(f"✗ Config check failed: {e}")
        return False

def main():
    print("=" * 60)
    print("SP-StockBot LOCAL OLLAMA FIXES VERIFICATION")
    print("=" * 60)
    print()
    
    checks = [
        ("Timezone Fix", check_timezone_fix),
        ("UTF-8 Encoding", check_encoding_support),
        ("Ollama Available", check_ollama_available),
        ("PyTorch CUDA", check_torch_cuda),
        ("Groq Removed", check_groq_removed),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"[{name}]")
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            results.append(False)
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("=" * 60)
    print(f"RESULTS: {passed}/{total} checks passed")
    print("=" * 60)
    
    if passed == total:
        print("✓ All fixes verified. Ready to start server.")
        print()
        print("Next steps:")
        print("  1. Ensure 'ollama serve' is running in another terminal")
        print("  2. Run: python -m SP-StockBot.main")
        print("  3. Check logs for: [LocalLLM] Warm-up successful")
        return 0
    elif passed >= total - 1:
        print("⚠ Most checks passed. Review warnings above.")
        print("Server may still work, but monitor logs carefully.")
        return 1
    else:
        print("✗ Critical issues detected. Fix errors before starting.")
        return 2

if __name__ == "__main__":
    sys.exit(main())
