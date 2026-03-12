#!/usr/bin/env python3
"""
Setup local LLM via Ollama for SP-StockBot.
Downloads and configures llama3.1:8b (quantized Q4_K_M for 4GB VRAM).
Includes fallback to CPU if no GPU available.

Usage:
    python setup_local_llm.py
"""

import os
import sys
import subprocess
import time
from pathlib import Path


def check_ollama_installed():
    """Check if Ollama is installed and accessible."""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ Ollama installed: {result.stdout.strip()}")
            return True
        return False
    except FileNotFoundError:
        return False


def install_ollama_windows():
    """Download and guide user to install Ollama on Windows."""
    print("\n" + "=" * 70)
    print("OLLAMA NOT FOUND - Installation Required")
    print("=" * 70)
    print("""
Ollama is a local LLM runtime. Please install it:

1. Download: https://ollama.ai/download/windows
2. Run the installer: OllamaSetup.exe
3. Follow installation wizard (default settings OK)
4. Restart this script

After installation, Ollama will run as a background service.
You can verify with: ollama --version
""")
    print("=" * 70)
    input("\nPress ENTER after installing Ollama...")
    return check_ollama_installed()


def start_ollama_service():
    """Start Ollama background service (already runs as Windows service)."""
    print("\n[Ollama] Ensuring background service is running...")
    # Ollama runs as Windows service, but we can call it to wake it up
    try:
        subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        print("✓ Ollama service is active")
        return True
    except subprocess.TimeoutExpired:
        print("⚠ Ollama service may be slow to start, waiting 10 seconds...")
        time.sleep(10)
        return True
    except Exception as e:
        print(f"✗ Failed to connect to Ollama: {e}")
        return False


def pull_llama_model():
    """Pull llama3.1:8b (quantized) model."""
    model_name = "llama3.1:8b"
    
    print(f"\n[Ollama] Checking model: {model_name}...")
    
    # Check if already exists
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if model_name in result.stdout:
        print(f"✓ Model already present: {model_name}")
        return True
    
    print(f"\n[Ollama] Pulling {model_name} (quantized for 4GB VRAM)...")
    print("This may take 5-10 minutes on first run. Please wait...\n")
    
    try:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            timeout=900,  # 15 min timeout
            text=True
        )
        
        if result.returncode == 0:
            print(f"✓ Model pulled successfully: {model_name}")
            return True
        else:
            print(f"✗ Failed to pull model: {result.stderr}")
            return False
    
    except subprocess.TimeoutExpired:
        print(f"✗ Model pull timeout (>15 min). Try manually: ollama pull {model_name}")
        return False
    except Exception as e:
        print(f"✗ Error pulling model: {e}")
        return False


def test_inference():
    """Test local inference with simple prompt."""
    print("\n[Ollama] Testing inference...")
    
    prompt = "สวัสดี (Hello in Thai). Respond in one word."
    
    try:
        result = subprocess.run(
            ["ollama", "run", "llama3.1:8b", prompt],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            response = result.stdout.strip()
            print(f"✓ Test inference successful")
            print(f"  Prompt: {prompt}")
            print(f"  Response: {response[:100]}...")
            return True
        else:
            print(f"✗ Inference test failed: {result.stderr}")
            return False
    
    except subprocess.TimeoutExpired:
        print("✗ Inference timeout (>30 sec). Model may be loading. Try again in 1 minute.")
        return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def main():
    """Main setup flow."""
    print("\n" + "=" * 70)
    print("  SP-StockBot Local LLM Setup (Ollama)")
    print("=" * 70)
    
    # Step 1: Check/Install Ollama
    if not check_ollama_installed():
        if not install_ollama_windows():
            print("\n✗ Ollama installation required. Exiting.")
            sys.exit(1)
    
    # Step 2: Start service
    if not start_ollama_service():
        print("\n⚠ Warning: Could not verify Ollama service. Continuing anyway...")
    
    # Step 3: Pull model
    if not pull_llama_model():
        print("\n✗ Failed to setup model. Please check Ollama manually:")
        print("  Start PowerShell and run: ollama pull llama3.1:8b")
        sys.exit(1)
    
    # Step 4: Test inference
    if not test_inference():
        print("\n⚠ Inference test failed, but model may still work. Try again in 1 minute.")
    
    print("\n" + "=" * 70)
    print("✓ SETUP COMPLETE")
    print("=" * 70)
    print("""
Next steps:
  1. Run: python setup_gpu.py       (verify CUDA/GPU support)
  2. Run: python setup_multimodal.py (install EasyOCR models)
  3. Run: python launch_local.bat    (start bot servers)
  
Test in Line app with: "เบิก กดทห80 5+"
Check logs: tail -f logs/agent_activity.log
""")
    print("=" * 70)


if __name__ == "__main__":
    main()
