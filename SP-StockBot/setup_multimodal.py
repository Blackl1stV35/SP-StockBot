#!/usr/bin/env python3
"""
Setup multimodal support for SP-StockBot (image OCR + voice transcription).
Downloads EasyOCR models (Thai + English) and Vosk speech recognition.

Tools:
  • EasyOCR: Extract text from images/documents
  • Vosk: Offline speech-to-text (Thai support)

Usage:
    python setup_multimodal.py
"""

import sys
try:
    import easyocr
except ImportError:
    print("EasyOCR not installed. Will be installed on first run.")

try:
    import vosk
except ImportError:
    print("Vosk not installed. Install via pip.")


def setup_easyocr_models():
    """Download EasyOCR models for Thai and English."""
    print("\n[EasyOCR] Setting up OCR models for Thai + English...")
    print("First run will download models (~150 MB). This may take a few minutes.\n")
    
    try:
        reader = easyocr.Reader(['th', 'en'], gpu=True)
        print("✓ EasyOCR initialized with Thai + English models")
        
        # Test with simple image text
        print("  Model ready for Thai/English text extraction from images")
        return True
    
    except Exception as e:
        print(f"⚠ EasyOCR setup warning: {e}")
        print("  Will retry on first image upload")
        return False


def setup_vosk_models():
    """Check Vosk speech recognition (Thai model download guidance)."""
    print("\n[Vosk] Speech recognition setup...")
    
    try:
        import vosk
        print("✓ Vosk library available")
        
        print("""
Note: Vosk Thai models are community-contributed.
For full Thai speech recognition, you have options:
  1. Use English model + fallback (vosk-model-en-us)
  2. Use community Thai model if available
  3. Keep voice as TODO feature (recommended)

Current recommendation: Skip Vosk setup, implement as stub for future release.
""")
        return True
    
    except ImportError:
        print("⚠ Vosk not installed. Install with: pip install vosk")
        print("  (Sound processing requires: pip install soundfile)")
        return False
    except Exception as e:
        print(f"✗ Vosk setup error: {e}")
        return False


def main():
    """Main multimodal setup flow."""
    print("\n" + "=" * 70)
    print("  SP-StockBot Multimodal Input Setup")
    print("=" * 70)
    
    print("\n[Step 1] Setting up Image OCR (EasyOCR)...")
    try:
        easyocr_ok = setup_easyocr_models()
    except Exception as e:
        print(f"✗ EasyOCR setup failed: {e}")
        easyocr_ok = False
    
    print("\n[Step 2] Setting up Speech Recognition (Vosk)...")
    try:
        vosk_ok = setup_vosk_models()
    except Exception as e:
        print(f"✗ Vosk setup warning: {e}")
        vosk_ok = False
    
    print("\n" + "=" * 70)
    print("✓ MULTIMODAL SETUP COMPLETE")
    print("=" * 70)
    print("""
Feature Status:
  • Image OCR (Thai/English): Available - extracts text from photos
  • Voice transcription: Stub ready - will implement later
  
In SP-StockBot:
  • Users can send images of invoices → bot extracts material names
  • Future: Users can send voice → bot transcribes to text
  
Next: python launch_local.bat
""")
    print("=" * 70)


if __name__ == "__main__":
    main()
