#!/usr/bin/env python3
"""
Setup GPU/CUDA support for SP-StockBot.
Verifies NVIDIA GPU availability and installs PyTorch with CUDA if needed.
Fallback to CPU if no GPU detected.

Hardware: NVIDIA GeForce GTX 1650 4GB (Turing arch, CUDA 11.6+)

Usage:
    python setup_gpu.py
"""

import sys
import subprocess
import importlib
from pathlib import Path


def check_nvidia_gpu():
    """Check if NVIDIA GPU is available via nvidia-smi."""
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Parse output for GPU info
            lines = result.stdout.split("\n")
            for line in lines:
                if "GeForce" in line or "Tesla" in line or "RTX" in line:
                    gpu_info = line.strip()
                    print(f"✓ NVIDIA GPU detected: {gpu_info}")
                    return True
            # Also check if nvidia-smi ran (even if GPU name not found)
            if "NVIDIA" in result.stdout or "Driver Version" in result.stdout:
                print("✓ NVIDIA GPU detected (driver found)")
                return True
        return False
    except FileNotFoundError:
        print("✗ nvidia-smi not found (NVIDIA drivers not installed)")
        return False
    except subprocess.TimeoutExpired:
        print("✗ nvidia-smi timeout")
        return False
    except Exception as e:
        print(f"✗ GPU check error: {e}")
        return False


def check_torch_cuda():
    """Check if PyTorch has CUDA support."""
    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            device_name = torch.cuda.get_device_name(0) if device_count > 0 else "Unknown"
            print(f"✓ PyTorch CUDA enabled | Devices: {device_count} | GPU: {device_name}")
            
            # Check VRAM
            if hasattr(torch.cuda, "mem_get_info"):
                free, total = torch.cuda.mem_get_info()
                print(f"  VRAM: {free/1e9:.1f}GB free / {total/1e9:.1f}GB total")
            
            return True
        else:
            print("✗ PyTorch CUDA not available (CPU mode)")
            return False
    except ImportError:
        print("✗ PyTorch not installed")
        return False
    except Exception as e:
        print(f"✗ PyTorch check error: {e}")
        return False


def install_torch_cuda():
    """Install PyTorch with CUDA 11.8 support for Windows."""
    print("\n[PyTorch] Installing PyTorch with CUDA 11.8 support...")
    print("This may take 2-5 minutes.\n")
    
    # Use pip to install torch with CUDA
    # Official command from pytorch.org for Windows + CUDA 11.8
    try:
        cmd = [
            sys.executable, "-m", "pip", "install",
            "torch", "torchvision", "torchaudio",
            "--index-url", "https://download.pytorch.org/whl/cu118"
        ]
        
        result = subprocess.run(cmd, timeout=300)  # 5 min timeout
        
        if result.returncode == 0:
            print("\n✓ PyTorch with CUDA installed successfully")
            return True
        else:
            print("\n✗ PyTorch installation failed")
            return False
    
    except subprocess.TimeoutExpired:
        print("\n✗ PyTorch installation timeout")
        return False
    except Exception as e:
        print(f"\n✗ Installation error: {e}")
        return False


def main():
    """Main GPU setup flow."""
    print("\n" + "=" * 70)
    print("  SP-StockBot GPU/CUDA Setup")
    print("=" * 70)
    
    print("\n[Step 1] Checking NVIDIA GPU...")
    has_gpu = check_nvidia_gpu()
    
    print("\n[Step 2] Checking PyTorch CUDA support...")
    has_cuda = check_torch_cuda()
    
    if has_gpu and not has_cuda:
        print("\n[Step 3] Installing PyTorch with CUDA support...")
        if install_torch_cuda():
            check_torch_cuda()  # Re-verify
        else:
            print("\n⚠ PyTorch install failed. Continuing in CPU mode.")
    
    elif has_gpu and has_cuda:
        print("\n✓ GPU acceleration ready!")
    
    else:
        print("\n⚠ No NVIDIA GPU detected. Bot will use CPU (still fast enough).")
    
    print("\n" + "=" * 70)
    print("✓ GPU SETUP COMPLETE")
    print("=" * 70)
    print("""
Summary:
  • Ollama will handle LLM inference (uses GPU automatically if available)
  • SentenceTransformer embeddings will use GPU (if CUDA enabled)
  • Fallback to CPU is automatic and works fine
  
Next: python setup_multimodal.py
""")
    print("=" * 70)


if __name__ == "__main__":
    main()
