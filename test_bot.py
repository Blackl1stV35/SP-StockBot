"""
Test suite for SP-StockBot webhook using simulated Line messages.
Uses httpx to POST to http://localhost:8000/callback with proper hmac signatures.
"""

import json
import hmac
import hashlib
import base64
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional
import httpx

# Read config
sys.path.insert(0, "SP-StockBot")
from config import Config
from logger import activity_logger


class LineWebhookSimulator:
    """Simulates Line webhook requests to test bot."""

    def __init__(self, webhook_url: str = "http://localhost:8000/callback"):
        self.webhook_url = webhook_url
        self.channel_secret = Config.LINE_CHANNEL_SECRET
        self.super_admin_user_id = "U67936b68b8b22bace43483b1bb736d27"
        self.test_user_id = "U12345678901234567890123456789012"

    def _generate_signature(self, body: str) -> str:
        """Generate X-Line-Signature based on channel secret and body."""
        signature = hmac.new(
            self.channel_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _create_event(
        self,
        message_text: str,
        user_id: str,
        event_type: str = "message",
    ) -> Dict[str, Any]:
        """Create a Line webhook event (v3 SDK format)."""
        # SDK v3 requires these fields
        return {
            "mode": "active",
            "webhookEventId": "00000000000000000000000000000000",
            "deliveryContext": {
                "isRedelivery": False,
            },
            "events": [
                {
                    "type": event_type,
                    "message": {
                        "type": "text",
                        "id": "1234567890123",
                        "text": message_text,
                    },
                    "timestamp": int(time.time() * 1000),
                    "source": {
                        "type": "user",
                        "userId": user_id,
                    },
                    "replyToken": f"nHuyWiB7yP5Zw52FIkcQT",
                    "mode": "active",
                }
            ]
        }

    def send_message(
        self,
        message_text: str,
        user_id: str,
        description: str = "",
    ) -> tuple[int, str, str]:
        """
        Send a message to the webhook.
        Returns: (status_code, response_text, raw_body)
        """
        event = self._create_event(message_text, user_id)
        body = json.dumps(event)
        signature = self._generate_signature(body)

        headers = {
            "X-Line-Signature": signature,
            "Content-Type": "application/json",
        }

        print(f"\n{'='*70}")
        print(f"TEST: {description}")
        print(f"{'='*70}")
        print(f"User ID:  {user_id}")
        print(f"Message:  {message_text}")
        print(f"Endpoint: POST {self.webhook_url}")

        try:
            response = httpx.post(
                self.webhook_url,
                content=body,
                headers=headers,
                timeout=10.0,
            )

            status = response.status_code
            text = response.text
            print(f"\nResponse Status: {status}")
            if text:
                print(f"Response Body:   {text}")

            return status, text, body

        except httpx.ConnectError:
            print("\n❌ ERROR: Cannot connect to webhook. Is uvicorn running?")
            print(f"   Make sure server is running: python SP-StockBot/main.py")
            return 0, "Connection failed", body
        except Exception as e:
            print(f"\n❌ ERROR: {type(e).__name__}: {e}")
            return 0, str(e), body

    def run_all_tests(self) -> Dict[str, Any]:
        """Run comprehensive test suite."""
        results = {
            "passed": 0,
            "failed": 0,
            "errors": [],
            "tests": [],
        }

        test_cases = [
            # Employee commands
            {
                "description": "Employee: Help command (ช่วย)",
                "message": "ช่วย",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Help command (English)",
                "message": "help",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Check stock (Thai)",
                "message": "สตอก ทรายอ่อน",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Check stock (English)",
                "message": "check sandpaper",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Report usage (Thai)",
                "message": "ใช้ ทรายอ่อน 5",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Report usage (English)",
                "message": "usage sandpaper 5",
                "user_id": self.test_user_id,
            },
            {
                "description": "Employee: Status command",
                "message": "status",
                "user_id": self.test_user_id,
            },
            # Admin commands (super admin user)
            {
                "description": "Admin: List users",
                "message": f"List users PIN:{Config.SUPER_ADMIN_PIN}",
                "user_id": self.super_admin_user_id,
            },
            {
                "description": "Admin: System stats",
                "message": f"System stats PIN:{Config.SUPER_ADMIN_PIN}",
                "user_id": self.super_admin_user_id,
            },
            {
                "description": "Admin: Help command",
                "message": "ช่วย",
                "user_id": self.super_admin_user_id,
            },
            {
                "description": "Admin: Set Drive folder",
                "message": f"Set drive https://drive.google.com/drive/u/0/folders/1GqzO3zkXXhgEV5q_M3ENQcZfOTVZDgL2 PIN:{Config.SUPER_ADMIN_PIN}",
                "user_id": self.super_admin_user_id,
            },
        ]

        print(f"\n\n{'#'*70}")
        print(f"# SP-STOCKBOT WEBHOOK TEST SUITE")
        print(f"# {len(test_cases)} test cases")
        print(f"{'#'*70}\n")

        start_time = time.time()

        for i, test_case in enumerate(test_cases, 1):
            test_result = {
                "num": i,
                "description": test_case["description"],
                "message": test_case["message"],
                "status": None,
                "response": None,
            }

            try:
                status, response, body = self.send_message(
                    message_text=test_case["message"],
                    user_id=test_case["user_id"],
                    description=test_case["description"],
                )

                # Success = 200 OK
                if status == 200:
                    print(f"✅ SUCCESS (status {status})")
                    results["passed"] += 1
                    test_result["status"] = "PASS"
                else:
                    print(f"⚠️  WARNING (status {status})")
                    results["failed"] += 1
                    test_result["status"] = "FAIL"

                test_result["response"] = {
                    "status_code": status,
                    "body": response[:200] if response else "",
                }

            except Exception as e:
                print(f"❌ ERROR: {e}")
                results["failed"] += 1
                results["errors"].append(str(e))
                test_result["status"] = "ERROR"
                test_result["response"] = {"error": str(e)}

            results["tests"].append(test_result)
            time.sleep(0.5)  # Small delay between tests

        end_time = time.time()
        duration = end_time - start_time

        # Print summary
        print(f"\n\n{'='*70}")
        print(f"TEST SUMMARY")
        print(f"{'='*70}")
        print(f"Total:   {len(test_cases)}")
        print(f"Passed:  {results['passed']} ✅")
        print(f"Failed:  {results['failed']} ❌")
        print(f"Duration: {duration:.2f}s")
        print(f"{'='*70}\n")

        # Print detailed results
        print("DETAILED RESULTS:\n")
        for test in results["tests"]:
            status_icon = "✅" if test["status"] == "PASS" else "❌" if test["status"] == "FAIL" else "⚠️"
            print(f"{status_icon} Test {test['num']}: {test['description']}")
            print(f"   Message: {test['message']}")
            print(f"   Status:  {test['status']}")
            if test["response"]:
                if isinstance(test["response"], dict):
                    if "status_code" in test["response"]:
                        print(f"   Code:    {test['response']['status_code']}")
            print()

        return results

    def check_server_status(self) -> bool:
        """Check if webhook server is running."""
        try:
            response = httpx.get(
                "http://localhost:8000/health",
                timeout=5.0,
            )
            if response.status_code == 200:
                health = response.json()
                print(f"✅ Server is running")
                print(f"   Status: {health.get('status')}")
                print(f"   Memory: {health.get('memory_mb', 0):.1f} MB")
                return True
            else:
                print(f"⚠️  Server health check returned {response.status_code}")
                return False
        except httpx.ConnectError:
            print("❌ Cannot connect to server at http://localhost:8000")
            print("   Make sure uvicorn is running: python SP-StockBot/main.py")
            return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False


def main():
    """Run test suite."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test SP-StockBot webhook with simulated Line messages"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests (default)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check if server is running",
    )
    parser.add_argument(
        "--message",
        type=str,
        help="Send a single message (e.g. 'ช่วย')",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        help="User ID for single message (default: test user)",
    )

    args = parser.parse_args()

    simulator = LineWebhookSimulator()

    print("\n" + "="*70)
    print("SP-STOCKBOT WEBHOOK TEST TOOL")
    print("="*70 + "\n")

    # Check server status first
    print("Checking server status...")
    if not simulator.check_server_status():
        print("\n⚠️  Server not available. Cannot run tests.")
        return 1

    print()

    if args.check_only:
        return 0

    if args.message:
        # Send single message
        user_id = args.user_id or simulator.test_user_id
        print(f"\nSending message: {args.message}")
        status, response, _ = simulator.send_message(
            message_text=args.message,
            user_id=user_id,
            description=f"Custom message from user {user_id}",
        )
        return 0 if status == 200 else 1

    # Run all tests (default)
    results = simulator.run_all_tests()

    # Exit with non-zero if any tests failed
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
