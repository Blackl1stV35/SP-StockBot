"""
Local LLM inference layer for SP-StockBot (Ollama-based).
Replaces cloud Groq calls with local llama3.1:3b inference.
Optimized for 8GB RAM + GTX 1650 GPU.

LOCAL SHIFT 2026-03-12: Fixed timezone, subprocess UTF-8 encoding, timeout increases
"""

import json
import hashlib
from typing import Optional, Dict, Any
import subprocess
import logging
import time
import re
import torch

from config import Config
from logger import activity_logger


class LocalLLMAgent:
    """Local Ollama-based intent classification and response generation."""

    OLLAMA_MODEL = "llama3.1:3b"
    OLLAMA_ENDPOINT = "http://localhost:11434"

    def __init__(self):
        """Initialize local LLM agent with device detection and warm-up."""
        self.model = self.OLLAMA_MODEL
        self.cache = {}
        
        # Detect device
        try:
            if torch.cuda.is_available():
                self.inference_device = f"cuda ({torch.cuda.get_device_name(0)})"
                activity_logger.logger.info(f"[LocalLLM] CUDA available: {torch.cuda.get_device_name(0)}")
            else:
                self.inference_device = "cpu"
                activity_logger.logger.warning("[LocalLLM] CUDA not available, using CPU")
        except Exception as e:
            self.inference_device = "cpu"
            activity_logger.logger.warning(f"[LocalLLM] GPU detection failed: {e}, using CPU")
        
        activity_logger.logger.info(
            f"[LocalLLM] Initialized | Model: {self.model} | Device: {self.inference_device}"
        )
        
        # Warm-up: run a dummy inference to load model into memory/VRAM
        self._warmup_model()

    def _warmup_model(self):
        """Pre-load model into VRAM on startup to avoid timeout on first request."""
        activity_logger.logger.info("[LocalLLM] Starting model warm-up...")
        try:
            start = time.time()
            response = self._call_ollama("say 'ready'", timeout_secs=90, log_timing=False)
            elapsed = time.time() - start
            if response:
                activity_logger.logger.info(f"[LocalLLM] Warm-up successful ({elapsed:.1f}s)")
            else:
                activity_logger.logger.warning("[LocalLLM] Warm-up failed but continuing...")
        except Exception as e:
            activity_logger.logger.warning(f"[LocalLLM] Warm-up exception (non-fatal): {e}")

    def _call_ollama(self, prompt: str, temperature: float = 0.3, timeout_secs: int = 60, log_timing: bool = True) -> Optional[str]:
        """
        Call local Ollama model via subprocess with UTF-8 encoding support.
        Falls back gracefully if Ollama not running.
        
        Args:
            prompt: Input prompt for model
            temperature: Creativity level (0.0 = deterministic, 1.0 = creative)
            timeout_secs: Timeout in seconds (default 60 for initial load, can go to 90)
            log_timing: Whether to log inference timing
            
        Returns:
            Model response or None if failed
        """
        try:
            cmd = [
                "ollama", "run", self.model,
                prompt
            ]
            
            start = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',        # LOCAL OLLAMA FIXED: Explicitly set UTF-8
                errors='replace',         # Replace any invalid UTF-8 chars instead of crashing
                timeout=timeout_secs,
                shell=False
            )
            elapsed = time.time() - start
            
            if result.returncode == 0:
                response = result.stdout.strip()
                if log_timing:
                    activity_logger.logger.debug(
                        f"[LocalLLM] Response OK ({len(response)} chars, {elapsed:.2f}s, device={self.inference_device})"
                    )
                return response
            else:
                err_msg = result.stderr[:200] if result.stderr else "Unknown error"
                activity_logger.logger.warning(
                    f"[LocalLLM] Ollama error (code {result.returncode}): {err_msg}"
                )
                return None
        
        except subprocess.TimeoutExpired:
            activity_logger.logger.warning(
                f"[LocalLLM] Inference timeout (>{timeout_secs}s) - model may be loading or Ollama overloaded"
            )
            return None
        except FileNotFoundError:
            activity_logger.logger.error(
                "[LocalLLM] Ollama not found at PATH. Install is required: https://ollama.ai/download"
            )
            return None
        except UnicodeDecodeError as e:
            activity_logger.logger.error(f"[LocalLLM] Unicode decode error (UTF-8 fix applied): {e}")
            return None
        except Exception as e:
            activity_logger.logger.error(f"[LocalLLM] Unexpected error: {type(e).__name__}: {e}")
            return None

    def classify_intent(
        self,
        user_message: str,
        user_name: str = "User",
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """
        Classify user intent and extract parameters using local LLM.
        Falls back to rule-based parsing if Ollama fails.
        
        Args:
            user_message: User's text input
            user_name: User's display name
            is_admin: Is user admin
            
        Returns:
            {
                "intent": "report_usage" | "check_stock" | "help" | "other",
                "parameters": {"material": "...", "quantity": N, ...},
                "reply_text": "...",
                "confidence": 0.0-1.0
            }
        """
        # Check cache first
        msg_hash = hashlib.md5(user_message.encode()).hexdigest()
        if msg_hash in self.cache:
            activity_logger.logger.debug(f"[Intent] Cache hit for: {user_message[:50]}")
            return self.cache[msg_hash]

        # Build prompt for Thai mechanic context
        prompt = f"""You are an assistant for a car repair shop inventory system.
Classify the user's intent from Thai or English text.

User: {user_name}
Is Admin: {is_admin}
Message: {user_message}

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "intent": "report_usage" | "check_stock" | "help" | "other",
  "material": "extracted material name or empty string",
  "quantity": 0,
  "confidence": 0.5 to 1.0
}}

Rules:
- If message has numbers like "5+5+" or "3 ชิ้น", extract as quantity
- If message mentions material (oil, filter, spray, Thai material names), extract material
- intent="report_usage" if user mentions เบิก/ใช้ (withdraw/use)
- intent="check_stock" if user mentions สต็อก/ตรวจสอบ (stock/check)
- intent="help" if user asks for help
- intent="other" for unclear messages
- confidence=1.0 if message is very clear, 0.5 if ambiguous

Respond only with the JSON object."""

        activity_logger.logger.debug(f"[Intent] Classifying: {user_message[:50]}")
        
        response_text = self._call_ollama(prompt, temperature=0.2, timeout_secs=60)
        
        if not response_text:
            # Fallback to simple rule-based intent parsing
            activity_logger.logger.warning("[Intent] Ollama failed, using rule-based fallback")
            return self._fallback_intent_parsing(user_message, user_name)

        # Parse JSON response
        try:
            # Clean response (remove markdown code blocks if present)
            json_str = response_text.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            
            data = json.loads(json_str)
            
            result = {
                "intent": data.get("intent", "other"),
                "parameters": {
                    "material": data.get("material", ""),
                    "quantity": int(data.get("quantity", 0)) if data.get("quantity") else 0
                },
                "reply_text": "",  # Generated by command handlers
                "confidence": float(data.get("confidence", 0.5))
            }
            
            activity_logger.logger.info(
                f"[Intent] {user_message[:30]} → {result['intent']} "
                f"(conf: {result['confidence']:.1f}, device={self.inference_device})"
            )
            
            # Cache result
            self.cache[msg_hash] = result
            
            return result
        
        except json.JSONDecodeError as e:
            activity_logger.logger.warning(f"[Intent] JSON parse failed: {e}, using fallback")
            activity_logger.logger.debug(f"  Response was: {response_text[:200]}")
            return self._fallback_intent_parsing(user_message, user_name)

    def _fallback_intent_parsing(self, user_message: str, user_name: str) -> Dict[str, Any]:
        """
        Fallback rule-based intent parsing when Ollama fails.
        Uses regex patterns to identify Thai keywords.
        """
        msg_lower = user_message.lower()
        msg_thai = user_message  # Keep original for Thai pattern matching
        
        # Check for Thai keywords (report/withdraw)
        if any(kw in msg_thai for kw in ["เบิก", "ใช้", "บริหาร", "ถอน"]):
            intent = "report_usage"
            confidence = 0.7
        # Check for stock/check keywords
        elif any(kw in msg_thai for kw in ["สต็อก", "ตรวจสอบ", "มีเท่าไหร่", "เหลือ"]):
            intent = "check_stock"
            confidence = 0.7
        # Check for help keywords
        elif any(kw in msg_lower for kw in ["help", "assist", "guide", "วิธี", "ช่วย", "คำสั่ง"]):
            intent = "help"
            confidence = 0.8
        else:
            intent = "other"
            confidence = 0.4
        
        # Simple quantity extraction (look for numbers)
        qty_match = re.search(r'(\d+)', user_message)
        quantity = int(qty_match.group(1)) if qty_match else 0
        
        result = {
            "intent": intent,
            "parameters": {
                "material": "",
                "quantity": quantity
            },
            "reply_text": "",
            "confidence": confidence
        }
        
        activity_logger.logger.info(
            f"[Intent] {user_message[:30]} → {result['intent']} "
            f"(conf: {result['confidence']:.1f}, fallback/regex)"
        )
        
        return result

    def generate_daily_summary(self, anomalies: list) -> str:
        """
        Generate natural language summary of daily anomalies.
        
        Args:
            anomalies: List of anomaly dicts
            
        Returns:
            Natural language summary
        """
        if not anomalies:
            return "ไม่พบความผิดปกติ (No anomalies detected)"

        # Format anomalies for prompt
        anom_text = "\n".join([
            f"- {a.get('material', 'Unknown')}: {a.get('deviation_percent', 0):.0f}% deviation "
            f"(Severity: {a.get('severity', 'Low')})"
            for a in anomalies[:10]  # Limit to 10
        ])

        prompt = f"""Summarize these inventory anomalies briefly in Thai (3-4 sentences):

{anom_text}

Focus on: which materials have unusual usage patterns, severity."""

        start = time.time()
        response = self._call_ollama(prompt, temperature=0.3, timeout_secs=60)
        elapsed = time.time() - start
        
        if response:
            activity_logger.logger.info(f"[Anomaly Summary] Generated ({len(response)} chars, {elapsed:.2f}s)")
            return response
        else:
            return f"Found {len(anomalies)} anomalies - review in dashboard"

    def extract_pin_from_message(self, message: str) -> Optional[str]:
        """Extract PIN from message like 'add user John PIN:7482'."""
        import re
        match = re.search(r'PIN[:\s]+(\d+)', message.upper())
        if match:
            return match.group(1)
        return None

    def verify_pin(self, provided_pin: str, correct_pin: str) -> bool:
        """Verify PIN matches."""
        return provided_pin == correct_pin


if __name__ == "__main__":
    # Manual test
    print("[LocalLLM] Starting test...")
    agent = LocalLLMAgent()
    
    test_messages = [
        "เบิก กดทห80 5+5+",
        "สต็อก น้ำมัน",
        "help",
    ]
    
    for msg in test_messages:
        result = agent.classify_intent(msg)
        print(f"\nMessage: {msg}")
        print(f"Intent: {result['intent']} (conf: {result['confidence']})")
        print(f"Parameters: {result['parameters']}")
