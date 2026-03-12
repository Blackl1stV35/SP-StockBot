#!/usr/bin/env python3
"""
Quick test script for Ollama Python client connection.
OLLAMA PYTHON CLIENT FIXED & 3B MODEL 2026-03-12
"""

import sys
import time
import json

def test_ollama_connection():
    """Test Ollama Python client connection."""
    print("=" * 70)
    print("OLLAMA PYTHON CLIENT CONNECTION TEST")
    print("=" * 70)
    print()
    
    # Step 1: Check ollama library
    print("[1/6] Checking ollama library...")
    try:
        import ollama
        print("✓ ollama library available")
    except ImportError:
        print("✗ ollama library NOT installed")
        print("   Fix: pip install ollama")
        return False
    
    # Step 2: Create client
    print("\n[2/6] Creating Ollama client...")
    try:
        client = ollama.Client(host='http://127.0.0.1:11434', timeout=120)
        print("✓ Client created | Host: http://127.0.0.1:11434 | Timeout: 120s")
    except Exception as e:
        print(f"✗ Failed to create client: {e}")
        return False
    
    # Step 3: Check server connectivity
    print("\n[3/6] Checking server connectivity (client.list())...")
    try:
        models = client.list()
        num_models = len(models.get('models', []))
        print(f"✓ Server reachable | Models: {num_models}")
        
        # List available models
        for model in models.get('models', [])[:5]:
            model_name = model.get('name', 'unknown')
            size = model.get('size', 0) / 1e9  # Convert to GB
            print(f"   - {model_name} ({size:.1f}GB)")
    except Exception as e:
        print(f"✗ Server unreachable: {e}")
        return False
    
    # Step 4: Check for llama3.2:3b model
    print("\n[4/6] Checking for llama3.2:3b model...")
    try:
        models_list = models.get('models', [])
        has_3b = any('llama3.2:3b' in m.get('name', '') for m in models_list)
        if has_3b:
            print("✓ Model llama3.2:3b found")
        else:
            print("⚠ Model llama3.2:3b NOT found (will try to pull on first use)")
            print("   Optional: ollama pull llama3.2:3b")
    except Exception as e:
        print(f"✗ Model check failed: {e}")
    
    # Step 5: Test inference
    print("\n[5/6] Testing inference (llama3.2:3b)...")
    try:
        start = time.time()
        response = client.generate(
            model='llama3.2:3b',
            prompt='Say "Ollama works" briefly.',
            options={'num_predict': 10},
            stream=False
        )
        elapsed = time.time() - start
        
        if response and 'response' in response:
            text = response['response'].strip()
            print(f"✓ Inference successful ({elapsed:.2f}s)")
            print(f"   Response: {text[:60]}...")
        else:
            print("✗ Empty response from inference")
            return False
    except Exception as e:
        print(f"✗ Inference failed: {e}")
        return False
    
    # Step 6: CUDA check
    print("\n[6/6] Checking GPU (torch.cuda)...")
    try:
        import torch
        if torch.cuda.is_available():
            print(f"✓ CUDA available: {torch.cuda.get_device_name(0)}")
        else:
            print("⚠ CUDA not available (will use CPU)")
    except ImportError:
        print("⚠ torch not installed (GPU detection disabled)")
    except Exception as e:
        print(f"⚠ GPU check failed: {e}")
    
    print()
    print("=" * 70)
    print("✓ ALL TESTS PASSED")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. cd SP-StockBot")
    print("  2. python main.py")
    print("  3. Check logs: tail -f ../logs/agent_activity.log")
    print("  4. Test: curl http://localhost:8000/api/ollama-test")
    print()
    return True


if __name__ == "__main__":
    success = test_ollama_connection()
    sys.exit(0 if success else 1)
