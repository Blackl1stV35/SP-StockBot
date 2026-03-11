"""
Groq API integration layer for SP-StockBot.
Handles intent classification, LLM calls with retry logic, and response caching.
Optimized for free tier: minimal tokens, fast models, caching.
Direct HTTP to Groq API (no SDK).
"""

import hashlib
import json
import time
from typing import Optional, Dict, Any
import requests
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
)

from config import Config
from database import Database
from logger import activity_logger


class GroqAgent:
    """Groq API client with direct HTTP, retry, caching, and structured JSON output."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, db: Database):
        """Initialize Groq agent."""
        if not Config.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY not set in environment! "
                "Please create .env file with: GROQ_API_KEY=gq_XXXXXXXX... "
                "from https://console.groq.com/keys"
            )

        self.api_key = Config.GROQ_API_KEY
        self.model = Config.GROQ_MODEL
        self.db = db
        
        # Log key verification (first 20 chars for debugging)
        key_preview = f"{self.api_key[:20]}..." if len(self.api_key) > 20 else "SHORT"
        activity_logger.logger.info(
            f"[Groq Init] API Key (first 20 chars): {key_preview}"
        )
        activity_logger.logger.info(
            f"[Groq Init] Model: {self.model} | Endpoint: {self.GROQ_API_URL}"
        )

    def _hash_message(self, message: str) -> str:
        """Create hash of message for cache lookup."""
        return hashlib.md5(message.encode()).hexdigest()

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _call_groq_with_retry(
        self,
        messages: list,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        """Call Groq API directly via HTTP with exponential backoff retry."""
        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            activity_logger.logger.debug(
                f"[Groq API] POST {self.GROQ_API_URL} | Model: {self.model} | Max tokens: {max_tokens}"
            )
            
            # Log request details (hide actual key)
            safe_headers = {
                "Authorization": f"Bearer {self.api_key[:20]}...",
                "Content-Type": "application/json",
            }
            activity_logger.logger.debug(
                f"[Groq API Request] Headers: {safe_headers} | Messages count: {len(messages)}"
            )
            
            response = requests.post(
                self.GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            
            # Log the raw response BEFORE processing (for debugging)
            activity_logger.logger.info(
                f"[Groq API Response] Status: {response.status_code} | Content-Type: {response.headers.get('content-type')}"
            )
            
            # Log full response body for debugging
            response_text = response.text if response.text else "(empty)"
            activity_logger.logger.debug(
                f"[Groq API Response Body] {response_text[:800]}"
            )
            
            # Check for error status codes BEFORE parsing JSON
            if response.status_code >= 400:
                error_detail = response.text[:300]
                activity_logger.logger.error(
                    f"[Groq API ERROR] HTTP {response.status_code} | Detail: {error_detail}"
                )
                response.raise_for_status()  # Raise exception for retry logic
            
            # Parse JSON response
            result = response.json()
            elapsed_ms = (time.time() - start_time) * 1000

            # Extract content with defensive coding
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            
            activity_logger.logger.info(
                f"[Groq API SUCCESS] {tokens_used} tokens in {elapsed_ms:.0f}ms | Content length: {len(content)}"
            )

            return {
                "content": content,
                "tokens_used": tokens_used,
                "elapsed_ms": elapsed_ms,
            }

        except requests.exceptions.HTTPError as e:
            # Handle 401, 429, 500 etc with retry
            status_code = e.response.status_code if e.response else 0
            if status_code in (401, 429, 500, 502, 503):
                activity_logger.logger.warning(
                    f"[Groq API] HTTP {status_code} - Will retry (tenacity)..."
                )
                raise  # Let tenacity retry
            else:
                activity_logger.logger.error(
                    f"[Groq API] HTTP {status_code} - Will NOT retry"
                )
                raise

        except requests.exceptions.RequestException as e:
            activity_logger.logger.error(f"[Groq API] Request Error: {e}")
            raise
        
        except json.JSONDecodeError as e:
            activity_logger.logger.error(
                f"[Groq API] JSON Parse Error: {e} | Response was: {response_text[:200]}"
            )
            raise
        
        except Exception as e:
            activity_logger.logger.error(
                f"[Groq API] Unexpected Error: {type(e).__name__} | {e}"
            )
            raise

    def classify_intent(
        self,
        user_message: str,
        user_name: str = "User",
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """
        Classify user message intent and extract parameters.
        Returns structured JSON with intent, parameters, and suggested reply.
        """
        # Check cache first
        msg_hash = self._hash_message(user_message)
        cached = self.db.get_cached_groq_response(msg_hash)
        if cached:
            activity_logger.logger.debug(
                f"Cache hit for message hash {msg_hash}"
            )
            return cached

        # Build system prompt (minimal to save tokens)
        system_prompt = """You are a Thai-English inventory bot for an auto repair shop.
Classify the user's message into one of these intents:
- check_stock: User wants to check current inventory
- add_stock: User wants to add inventory item (may require PIN)
- report_usage: User reports consumption/usage
- help: User asks for help
- other: None of the above

For admin-only commands (add_user, bulk_add, set_drive, etc.), return intent="admin_command".

Respond ONLY with valid JSON in this exact format:
{
  "intent": "check_stock|add_stock|report_usage|help|admin_command|other",
  "parameters": {
    "material": "material name if mentioned",
    "quantity": "quantity if mentioned",
    "pin": "PIN if provided at end of message",
    "command": "admin command name if applicable"
  },
  "reply_text": "Brief Thai + English response acknowledgment (10-20 words)",
  "requires_pin": "true|false",
  "confidence": 0.0-1.0
}"""

        # User message with context
        user_prompt = f"""User: {user_name} (admin={is_admin})
Message: {user_message}

Classify this message."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = self._call_groq_with_retry(messages, max_tokens=300)
            groq_output = json.loads(result["content"])

            # Cache the response
            self.db.cache_groq_response(
                message_hash=msg_hash,
                intent=groq_output.get("intent", "other"),
                parameters=groq_output.get("parameters", {}),
                reply_text=groq_output.get("reply_text", ""),
            )

            # Log API call
            activity_logger.log_groq_api_call(
                user_id=None,
                model=self.model,
                tokens_used=result.get("tokens_used"),
                response_time_ms=result.get("elapsed_ms"),
            )

            return groq_output

        except json.JSONDecodeError as e:
            activity_logger.log_error(
                f"Invalid JSON from Groq: {e}",
                error_type="groq_json_error",
            )
            return {
                "intent": "other",
                "parameters": {},
                "reply_text": "Processing error. Please try again.",
                "requires_pin": False,
                "confidence": 0.0,
            }
        except Exception as e:
            activity_logger.log_groq_api_call(
                user_id=None,
                model=self.model,
                error=str(e),
            )
            return {
                "intent": "error",
                "parameters": {},
                "reply_text": "Unable to process. API error.",
                "requires_pin": False,
                "confidence": 0.0,
            }

    def generate_anomaly_report(
        self,
        employee_name: str,
        material_name: str,
        current_usage: float,
        baseline_usage: float,
        deviation_percent: float,
    ) -> str:
        """
        Generate human-readable anomaly alert in Thai+English.
        """
        msg_hash = self._hash_message(
            f"anomaly_report:{employee_name}:{material_name}"
        )
        cached = self.db.get_cached_groq_response(msg_hash)
        if cached:
            return cached.get("reply_text", "")

        system_prompt = """You are a report writer for an auto repair shop in Thailand.
Create a brief, clear anomaly alert about unusual material consumption.
Use both Thai and English. Keep it to 30-40 words maximum.
Be direct and highlight the problem."""

        user_prompt = f"""Employee: {employee_name}
Material: {material_name}
Baseline monthly usage: {baseline_usage:.1f} units
Current usage: {current_usage:.1f} units
Deviation: {deviation_percent:.1f}%

Write alert message."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = self._call_groq_with_retry(messages, max_tokens=100)
            reply_text = result["content"]

            # Cache it
            self.db.cache_groq_response(
                message_hash=msg_hash,
                intent="anomaly_report",
                parameters={},
                reply_text=reply_text,
            )

            return reply_text
        except Exception as e:
            activity_logger.log_error(
                f"Failed to generate anomaly report: {e}",
                error_type="groq_anomaly_error",
            )
            return f"Anomaly: {employee_name} - {material_name} ({deviation_percent:.0f}%)"

    def generate_daily_summary(self, anomalies: list) -> str:
        """
        Generate daily summary of all anomalies for admin.
        Minimal tokens: just number + severity.
        """
        if not anomalies:
            return "✓ No anomalies detected today."

        summary_text = f"Daily Summary:\n"
        summary_text += f"- {len(anomalies)} anomalie(s) detected\n"

        high_count = sum(1 for a in anomalies if a.get("severity") == "High")
        medium_count = sum(
            1 for a in anomalies if a.get("severity") == "Medium"
        )

        summary_text += f"  🔴 High: {high_count}\n"
        summary_text += f"  🟡 Medium: {medium_count}\n"

        # List top 3 by severity
        sorted_anomalies = sorted(
            anomalies,
            key=lambda x: {"High": 3, "Medium": 2, "Low": 1}.get(
                x.get("severity"), 0
            ),
            reverse=True,
        )[:3]

        for anom in sorted_anomalies:
            summary_text += (
                f"  • {anom.get('description', 'Unknown')} "
                f"({anom.get('deviation_percent', 0):.0f}%)\n"
            )

        return summary_text

    def verify_pin(self, provided_pin: str, expected_pin: str) -> bool:
        """Verify PIN (simple string comparison)."""
        return provided_pin.strip() == expected_pin.strip()

    def extract_pin_from_message(self, message: str) -> Optional[str]:
        """Extract PIN from message (format: PIN:1234 or just 1234 at end)."""
        # Look for "PIN:XXXX" pattern
        import re
        match = re.search(r"PIN:(\d{4,6})", message, re.IGNORECASE)
        if match:
            return match.group(1)

        # Look for 4-6 digits at end of message
        words = message.split()
        if words:
            last_word = words[-1]
            if last_word.isdigit() and 4 <= len(last_word) <= 6:
                return last_word

        return None


# Global agent instance (lazy loaded)
_groq_agent: Optional[GroqAgent] = None


def get_groq_agent(db: Database) -> GroqAgent:
    """Get or create Groq agent instance."""
    global _groq_agent
    if _groq_agent is None:
        _groq_agent = GroqAgent(db)
    return _groq_agent


if __name__ == "__main__":
    # Test the agent with direct HTTP to Groq API
    import sys
    import io
    
    # Fix Windows console encoding for Unicode
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    db = Database()
    agent = GroqAgent(db)

    # Test intent classification
    test_messages = [
        "ช่วย",  # Thai help - should return intent "help"
        "สตอก ทรายอ่อน",  # Check stock
        "Add user ไผท",  # Admin command
        "Help me",  # English help
        "Set drive https://drive.google.com/... PIN:1234",  # Admin set drive
    ]

    print("=" * 60)
    print("Testing GroqAgent with Direct HTTP to Groq API")
    print("API Endpoint: https://api.groq.com/openai/v1/chat/completions")
    print("=" * 60)

    for msg in test_messages:
        print(f"\n[MESSAGE] {msg}")
        try:
            result = agent.classify_intent(msg, "TestUser", is_admin=True)
            print(f"[INTENT] {result.get('intent')}")
            print(f"[PIN_REQUIRED] {result.get('requires_pin')}")
            print(f"[REPLY] {result.get('reply_text')}")
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)
