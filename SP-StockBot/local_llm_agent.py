"""
Local LLM inference layer for SP-StockBot (Multi-backend intent parsing).
Primary: Gemini API (Free tier: 1M context, 15 RPM) for reliability
Fallback: Ollama llama3.2:3b (local GPU)
Final fallback: Rule-based regex parsing

GEMINI INTEGRATED + DRIVE SCANNER FIXED 2026-03-12
- Gemini API as primary intent classifier (free tier, excellent Thai support)
- Ollama as offline backup (if Gemini down/rate-limited)
- Rule-based as final fallback
- Spam detection for nonsense inputs
- Recursive Drive scanning for all subfolders + root files
"""

import json
import hashlib
from typing import Optional, Dict, Any
import logging
import time
import re
import torch
import string

try:
    import ollama
except ImportError:
    ollama = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

from tenacity import retry, stop_after_attempt, wait_fixed
from config import Config
from logger import activity_logger


class LocalLLMAgent:
    """Multi-backend intent classification: Gemini (primary) → Ollama (backup) → Fallback."""

    OLLAMA_MODEL = "llama3.2:3b"  # Faster than 8b, uses ~2GB VRAM
    OLLAMA_HOST = "http://127.0.0.1:11434"
    OLLAMA_TIMEOUT = 120  # 2 min timeout for Ollama operations

    def __init__(self):
        """Initialize intent parser with Gemini + Ollama + fallback chain."""
        self.model = self.OLLAMA_MODEL
        self.cache = {}
        self.ollama_client = None
        self.ollama_healthy = False
        self.gemini_api_key = Config.GEMINI_API_KEY
        self.gemini_model = Config.GEMINI_MODEL
        
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
        
        # Initialize Gemini
        if self.gemini_api_key:
            try:
                genai.configure(api_key=self.gemini_api_key)
                activity_logger.logger.info(f"[Gemini] Configured with model: {self.gemini_model}")
            except Exception as e:
                activity_logger.logger.warning(f"[Gemini] Configuration failed: {e}")
        else:
            activity_logger.logger.warning("[Gemini] No API key found. Using Ollama + fallback only.")
        
        # Initialize Ollama client
        if ollama is None:
            activity_logger.logger.warning("[LocalLLM] ollama library not installed. Gemini will be primary.")
        else:
            try:
                self.ollama_client = ollama.Client(host=self.OLLAMA_HOST, timeout=self.OLLAMA_TIMEOUT)
                activity_logger.logger.info(
                    f"[LocalLLM] Ollama client created | Host: {self.OLLAMA_HOST} | Timeout: {self.OLLAMA_TIMEOUT}s"
                )
            except Exception as e:
                activity_logger.logger.error(f"[LocalLLM] Failed to create Ollama client: {e}")
        
        # Check Ollama connectivity
        self._check_ollama_server()
        
        # Warm-up Ollama if available
        if self.ollama_healthy:
            self._warmup_model()

    def _check_ollama_server(self):
        """Check if Ollama server is reachable."""
        if not self.ollama_client:
            activity_logger.logger.error("[LocalLLM] Ollama client not initialized")
            self.ollama_healthy = False
            return
        
        activity_logger.logger.info("[LocalLLM] Checking Ollama server connectivity...")
        try:
            models = self.ollama_client.list()
            activity_logger.logger.info(f"[LocalLLM] ✓ Ollama server reachable | Models available: {len(models.get('models', []))}")
            self.ollama_healthy = True
        except Exception as e:
            activity_logger.logger.error(f"[LocalLLM] ✗ Ollama server unreachable: {e}")
            self.ollama_healthy = False

    def _warmup_model(self):
        """Pre-load Ollama model into VRAM with retry logic."""
        activity_logger.logger.info("[LocalLLM] Starting Ollama model warm-up...")
        
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
        def warmup_with_retry():
            start = time.time()
            activity_logger.logger.debug("[LocalLLM] Warm-up attempt...")
            response = self._call_ollama_api("warm up test", timeout_secs=90, log_timing=False)
            elapsed = time.time() - start
            if response:
                activity_logger.logger.info(f"[LocalLLM] ✓ Warm-up successful ({elapsed:.1f}s)")
                return True
            else:
                raise Exception("Warm-up inference returned None")
        
        try:
            warmup_with_retry()
        except Exception as e:
            activity_logger.logger.warning(f"[LocalLLM] Warm-up failed after retries: {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def _call_ollama_api(self, prompt: str, timeout_secs: int = 60, log_timing: bool = True) -> Optional[str]:
        """
        Call Ollama API via Python client with automatic retry.
        
        Args:
            prompt: Input prompt
            timeout_secs: Timeout in seconds
            log_timing: Whether to log inference duration
            
        Returns:
            Model response or None if failed (max 3 retries)
        """
        if not self.ollama_client or not self.ollama_healthy:
            activity_logger.logger.error("[LocalLLM] Ollama client not ready or server unreachable")
            return None
        
        try:
            start = time.time()
            activity_logger.logger.debug(f"[LocalLLM] Calling Ollama: {self.model}")
            
            # Call Ollama API
            response = self.ollama_client.generate(
                model=self.model,
                prompt=prompt,
                options={
                    'num_predict': 100,          # Limit tokens for speed
                    'temperature': 0.3,           # Lower = more deterministic
                    'num_ctx': 512,               # Context window (smaller = faster)
                },
                stream=False
            )
            
            elapsed = time.time() - start
            
            if response and 'response' in response:
                text = response['response'].strip()
                if log_timing:
                    activity_logger.logger.debug(
                        f"[LocalLLM] Response OK ({len(text)} chars, {elapsed:.2f}s, device={self.inference_device})"
                    )
                return text
            else:
                activity_logger.logger.warning("[LocalLLM] Empty response from API")
                return None
                
        except Exception as e:
            activity_logger.logger.warning(f"[LocalLLM] API call attempt failed: {e}")
            raise  # Re-raise for tenacity retry

    def _detect_spam(self, user_message: str) -> tuple[bool, str]:
        """
        Detect spam/nonsense input.
        Returns: (is_spam, reason)
        """
        msg = user_message.strip()
        
        # Check message length
        if len(msg) > 200:
            return True, "Message too long (>200 chars)"
        
        # Check for random characters (entropy)
        if len(msg) > 10:
            unique_chars = len(set(msg))
            entropy_ratio = unique_chars / len(msg)
            if entropy_ratio > 0.8:  # Very high char diversity = random
                return True, "High entropy (random characters)"
        
        # Check for empty or whitespace only
        if not msg or msg.isspace():
            return True, "Empty message"
        
        # Check for pure number (unless it's quantity-like "123" after intent)
        if msg.isdigit() and len(msg) > 4:
            return True, "Pure numbers"
        
        # Check for all special characters
        special_count = sum(1 for c in msg if c in string.punctuation)
        if special_count / len(msg) > 0.6 and len(msg) > 5:
            return True, "Too many special characters"
        
        return False, ""

    def _gemini_intent_parse(self, user_message: str, user_name: str = "User") -> Optional[Dict[str, Any]]:
        """
        Parse intent using Gemini API (free tier: 1.5 Flash or 2.0).
        Returns intent dict or None if failed/rate-limited.
        """
        if not self.gemini_api_key or genai is None:
            return None
        
        try:
            model = genai.GenerativeModel(self.gemini_model)
            
            prompt = f"""You are an AI assistant for a car repair shop inventory system.
Classify the user's intent from Thai/English text.

User: {user_name}
Message: {user_message}

IMPORTANT: Respond ONLY with valid JSON (no markdown, no backticks), exactly like this:
{{"intent": "report_usage", "material": "", "quantity": 0, "confidence": 0.95}}

Rules:
1. Intent types:
   - "report_usage": User wants to withdraw/use materials (keywords: เบิก, ใช้, ถอน, ส่ง)
   - "check_stock": User wants to check inventory (keywords: สต็อก, ตรวจสอบ, เหลือ, มีไหม)
   - "help": User needs help/guide (keywords: help, วิธี, ช่วย, คำสั่ง)  
   - "system_info": User asks about system (keywords: ระบบ, สถานะ, ข้อมูล)
   - "other": Doesn't clearly fit above

2. Extract:
   - Material name if mentioned
   - Quantity (number) if mentioned
   
3. Confidence:
   - 0.95: Very clear intent with specific material/qty
   - 0.85: Clear intent, some details missing
   - 0.7: Somewhat ambiguous but reasonable guess
   - 0.5: Very ambiguous
"""
            
            response = model.generate_content(prompt, request_options={"timeout": 30})
            
            if not response or not response.text:
                activity_logger.logger.warning("[Gemini] Empty response")
                return None
            
            # Parse JSON response
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            
            data = json.loads(text)
            
            result = {
                "intent": data.get("intent", "other"),
                "parameters": {
                    "material": data.get("material", ""),
                    "quantity": int(data.get("quantity", 0)) if data.get("quantity") else 0
                },
                "confidence": float(data.get("confidence", 0.5)),
                "parser": "gemini"
            }
            
            activity_logger.logger.info(
                f"[Intent] {user_message[:40]} → {result['intent']} "
                f"(conf: {result['confidence']:.2f}, Gemini)"
            )
            return result
        
        except Exception as e:
            activity_logger.logger.debug(f"[Gemini] Intent parse failed: {e}")
            return None

    def parse_intent(self, user_message: str, user_name: str = "User") -> Dict[str, Any]:
        """
        Primary intent parser with fallback chain:
        1. Detect spam → reject
        2. Try Gemini (if API key available)
        3. Try Ollama (if server healthy)
        4. Fall back to rule-based parsing
        
        Returns: intent dict with "parser" field indicating which succeeded
        """
        # Spam detection first
        is_spam, spam_reason = self._detect_spam(user_message)
        if is_spam:
            activity_logger.logger.warning(f"[Intent] Spam detected: {spam_reason}")
            return {
                "intent": "spam",
                "parameters": {"material": "", "quantity": 0},
                "confidence": 1.0,
                "parser": "spam_filter"
            }
        
        # Check cache
        msg_hash = hashlib.md5(user_message.encode()).hexdigest()
        if msg_hash in self.cache:
            activity_logger.logger.debug(f"[Intent] Cache hit: {user_message[:40]}")
            return self.cache[msg_hash]
        
        # Try Gemini first
        if self.gemini_api_key:
            result = self._gemini_intent_parse(user_message, user_name)
            if result:
                self.cache[msg_hash] = result
                return result
        
        # Try Ollama
        if self.ollama_healthy:
            result = self.classify_intent(user_message, user_name)
            if result.get("parser") == "ollama":
                self.cache[msg_hash] = result
                return result
        
        # Final fallback
        result = self._fallback_intent_parsing(user_message, user_name)
        self.cache[msg_hash] = result
        return result

    def classify_intent(
        self,
        user_message: str,
        user_name: str = "User",
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """
        Classify user intent using local LLM (with fallback to regex).
        
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
        # Check cache
        msg_hash = hashlib.md5(user_message.encode()).hexdigest()
        if msg_hash in self.cache:
            activity_logger.logger.debug(f"[Intent] Cache hit: {user_message[:40]}")
            return self.cache[msg_hash]

        # Build prompt
        prompt = f"""You are an assistant for a car repair shop.
Classify intent from Thai/English text.

User: {user_name}
Message: {user_message}

Respond ONLY with JSON:
{{
  "intent": "report_usage" | "check_stock" | "help" | "other",
  "material": "...",
  "quantity": 0,
  "confidence": 0.5 to 1.0
}}

Rules:
- report_usage: เบิก/ใช้ (withdraw/use)
- check_stock: สต็อก/ตรวจสอบ (stock/check)
- help: วิธี/ช่วย/คำสั่ง (guide/help)
- confidence: 1.0 if clear, 0.5 if ambiguous"""

        activity_logger.logger.debug(f"[Intent] Classifying: {user_message[:40]}")
        
        response_text = self._call_ollama_api(prompt, timeout_secs=60)
        
        if not response_text:
            activity_logger.logger.warning("[Intent] Ollama failed, using rule-based fallback")
            return self._fallback_intent_parsing(user_message, user_name)

        # Parse JSON
        try:
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
                "reply_text": "",
                "confidence": float(data.get("confidence", 0.5)),
                "parser": "ollama"
            }
            
            activity_logger.logger.info(
                f"[Intent] {user_message[:30]} → {result['intent']} "
                f"(conf: {result['confidence']:.1f}, Ollama)"
            )
            
            return result
        
        except json.JSONDecodeError as e:
            activity_logger.logger.warning(f"[Intent] JSON parse failed: {e}, fallback")
            return self._fallback_intent_parsing(user_message, user_name)

    def _fallback_intent_parsing(self, user_message: str, user_name: str) -> Dict[str, Any]:
        """
        Enhanced fallback: rule-based parsing with expanded Thai keyword support.
        Used when Ollama is unavailable.
        """
        msg_lower = user_message.lower()
        msg_thai = user_message
        
        # Report/Withdraw intents
        report_keywords = ["เบิก", "ใช้", "บริหาร", "ถอน", "ส่ง", "ทำ", "จ่าย"]
        if any(kw in msg_thai for kw in report_keywords):
            intent = "report_usage"
            confidence = 0.75
        # Stock/Check intents
        elif any(kw in msg_thai for kw in ["สต็อก", "ตรวจสอบ", "มีเท่าไหร่", "เหลือ", "ตรวจ", "ดู", "เท่า"]):
            intent = "check_stock"
            confidence = 0.75
        # Help/Guide intents
        elif any(kw in msg_lower + msg_thai for kw in ["help", "assist", "guide", "วิธี", "ช่วย", "คำสั่ง", "สวัสดี", "ช่วยด้วย"]):
            intent = "help"
            confidence = 0.8
        # System info request
        elif any(kw in msg_thai for kw in ["ระบบ", "สถานะ", "เกี่ยว", "ข้อมูล"]):
            intent = "system_info"
            confidence = 0.7
        else:
            intent = "other"
            confidence = 0.5  # Raised from 0.4
        
        # Extract quantity
        qty_match = re.search(r'(\d+)', user_message)
        quantity = int(qty_match.group(1)) if qty_match else 0
        
        result = {
            "intent": intent,
            "parameters": {"material": "", "quantity": quantity},
            "reply_text": "",
            "confidence": confidence,
            "parser": "fallback"
        }
        
        activity_logger.logger.info(
            f"[Intent] {user_message[:30]} → {result['intent']} (conf: {confidence:.2f}, fallback/keyword)"
        )
        
        return result

    def generate_daily_summary(self, anomalies: list) -> str:
        """
        Generate natural language summary of anomalies using LLM.
        Falls back to simple text if LLM unavailable.
        """
        if not anomalies:
            return "ไม่พบความผิดปกติ (No anomalies detected)"

        # Format anomalies
        anom_text = "\n".join([
            f"- {a.get('material', 'Unknown')}: {a.get('deviation_percent', 0):.0f}% "
            f"({a.get('severity', 'Low')})"
            for a in anomalies[:10]
        ])

        prompt = f"""Summarize these anomalies briefly in Thai (2-3 sentences):

{anom_text}

Focus on: unusual patterns, severity."""

        start = time.time()
        response = self._call_ollama_api(prompt, timeout_secs=60)
        elapsed = time.time() - start
        
        if response:
            activity_logger.logger.info(f"[Anomaly] Summary generated ({len(response)} chars, {elapsed:.2f}s)")
            return response
        else:
            return f"Found {len(anomalies)} anomalies - review dashboard"

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
