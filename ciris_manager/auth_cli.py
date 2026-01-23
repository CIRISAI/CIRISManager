#!/usr/bin/env python3
"""
CIRIS Manager CLI authentication module.
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, cast
import argparse

try:
    import requests
except ImportError:
    print("Error: requests library not installed")
    print("Install with: pip install requests")
    sys.exit(1)


class AuthManager:
    """Manages authentication for CIRIS Manager CLI."""

    def __init__(self, base_url: str = "https://agents.ciris.ai"):
        self.base_url = base_url
        self.config_dir = Path.home() / ".config" / "ciris-manager"
        self.token_file = self.config_dir / "token.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def request_device_code(self) -> Dict[str, Any]:
        """Request a device code from the manager."""
        url = f"{self.base_url}/manager/v1/device/code"

        try:
            response = requests.post(
                url, json={"client_id": "ciris-cli", "scope": "manager:full"}, timeout=10
            )
            response.raise_for_status()
            return cast(Dict[str, Any], response.json())
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to request device code: {e}")
            sys.exit(1)

    def poll_for_token(
        self, device_code: str, interval: int = 5, timeout: int = 600
    ) -> Optional[str]:
        """Poll for token after user authorizes."""
        url = f"{self.base_url}/manager/v1/device/token"
        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                response = requests.post(
                    url,
                    json={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code,
                        "client_id": "ciris-cli",
                    },
                    timeout=10,
                )

                if response.status_code == 200:
                    data = response.json()
                    return cast(Optional[str], data.get("access_token"))
                elif response.status_code == 428:
                    # Authorization pending
                    print(".", end="", flush=True)
                    time.sleep(interval)
                elif response.status_code == 400:
                    data = response.json()
                    error = data.get("error")
                    if error == "authorization_pending":
                        # Still waiting for user to authorize
                        print(".", end="", flush=True)
                        time.sleep(interval)
                    elif error == "slow_down":
                        interval = data.get("interval", interval * 2)
                        time.sleep(interval)
                    elif error in ["access_denied", "expired_token", "invalid_grant"]:
                        print(f"\n❌ Authorization failed: {error}")
                        return None
                    else:
                        # Unknown error, keep trying
                        time.sleep(interval)
                else:
                    print(f"\n❌ Unexpected response: {response.status_code}")
                    return None

            except requests.exceptions.RequestException as e:
                print(f"\n❌ Request error: {e}")
                time.sleep(interval)

        print("\n❌ Authentication timed out")
        return None

    def save_token(self, token: str, email: str) -> None:
        """Save token to disk."""
        expires_at = datetime.utcnow() + timedelta(hours=24)

        token_data = {
            "token": token,
            "email": email,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        }

        with open(self.token_file, "w") as f:
            json.dump(token_data, f, indent=2)

        # Secure the file
        self.token_file.chmod(0o600)

    def load_token(self) -> Optional[Dict[str, Any]]:
        """Load token from disk if valid."""
        if not self.token_file.exists():
            return None

        try:
            with open(self.token_file) as f:
                data = json.load(f)

            # Check expiry
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.utcnow() > expires_at:
                print("⚠️  Token expired, please login again")
                self.token_file.unlink()
                return None

            return cast(Dict[str, Any], data)
        except Exception:
            return None

    def login(self, email: str) -> Optional[str]:
        """Perform device flow authentication."""
        # Check for existing valid token
        token_data = self.load_token()
        if token_data and token_data.get("email") == email:
            if self.test_token(token_data["token"]):
                print(f"✅ Using saved token for {email}")
                return cast(str, token_data["token"])

        print(f"🔐 Authenticating {email} with CIRIS Manager...")

        # Request device code
        device_data = self.request_device_code()

        print("\n" + "=" * 60)
        print(f"🌐 Please visit: {device_data['verification_uri_complete']}")
        print("=" * 60 + "\n")

        print("⏳ Waiting for authorization", end="", flush=True)

        # Poll for token
        token = self.poll_for_token(device_data["device_code"], device_data.get("interval", 5))

        if token:
            print("\n✅ Authentication successful!")
            self.save_token(token, email)
            return token

        return None

    def test_token(self, token: str) -> bool:
        """Test if token is valid."""
        try:
            response = requests.get(
                f"{self.base_url}/manager/v1/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            return bool(response.status_code == 200)
        except Exception:
            return False

    def logout(self) -> None:
        """Remove saved token."""
        if self.token_file.exists():
            self.token_file.unlink()
            print("✅ Logged out successfully")
        else:
            print("ℹ️  Not logged in")

    def get_token(self) -> Optional[str]:
        """Get current valid token."""
        token_data = self.load_token()
        if token_data and self.test_token(token_data["token"]):
            return cast(Optional[str], token_data["token"])
        return None

    def show_status(self) -> None:
        """Show authentication status."""
        token_data = self.load_token()

        if not token_data:
            print("❌ Not authenticated")
            print("\nLogin with: ciris-manager auth login your-email@ciris.ai")
            return

        email = token_data.get("email", "unknown")
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        created_at = datetime.fromisoformat(token_data["created_at"])

        time_left = expires_at - datetime.utcnow()
        minutes_left = int(time_left.total_seconds() / 60)

        print(f"✅ Authenticated as: {email}")
        print(f"📅 Token created: {created_at.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"⏰ Expires in: {minutes_left} minutes")

        # Test token validity
        if self.test_token(token_data["token"]):
            print("🔒 Token status: Valid")
        else:
            print("⚠️  Token status: Invalid (may have been revoked)")

    def request_dev_token(self) -> Optional[str]:
        """
        Request a dev token from the local manager.

        This only works when:
        1. The manager has CIRIS_DEV_MODE=true
        2. This command is run on the manager server itself (localhost)

        The port is extracted from the configured base_url to support
        non-standard ports (e.g., 8090 instead of 8888).

        Returns the token if successful, None otherwise.
        """
        # Extract port from base_url to use correct port on localhost
        # e.g., https://scout-test.example.com:8090 -> port 8090
        # If no explicit port (standard 443/80), default to 8888 (manager default)
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        # parsed.port is None for standard ports (443 for https, 80 for http)
        # In that case, assume manager is on default port 8888
        port = parsed.port if parsed.port else 8888

        # Dev token endpoint must be called via localhost
        localhost_url = f"http://127.0.0.1:{port}"
        url = f"{localhost_url}/manager/v1/dev/token"

        try:
            response = requests.post(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return cast(Optional[str], data.get("access_token"))
            elif response.status_code == 403:
                print("❌ Dev token rejected: endpoint only accessible from localhost")
                print("   Run this command directly on the manager server.")
                return None
            elif response.status_code == 404:
                print("❌ Dev token endpoint not found.")
                print("   Ensure CIRIS_DEV_MODE=true is set on the manager.")
                print("   Note: This endpoint requires CIRISManager >= 2.3.0")
                return None
            else:
                print(f"❌ Failed to get dev token: HTTP {response.status_code}")
                try:
                    error = response.json().get("detail", response.text)
                    print(f"   {error}")
                except Exception:
                    print(f"   {response.text}")
                return None

        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to local manager at {localhost_url}")
            print("   Ensure the manager is running and you're on the manager server.")
            return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Request failed: {e}")
            return None

    def get_dev_token(self) -> Optional[str]:
        """Get a dev token and save it."""
        print("🔧 Requesting dev token from local manager...")

        token = self.request_dev_token()

        if token:
            # Save the token
            self.save_token(token, "dev@ciris.ai")
            print("✅ Dev token obtained and saved!")
            print("   Email: dev@ciris.ai")
            print(f"   Token file: {self.token_file}")
            return token

        return None


def handle_auth_command(args: argparse.Namespace) -> int:
    """Handle auth subcommand."""
    auth = AuthManager(base_url=args.base_url)

    if args.auth_command == "login":
        if not args.email:
            print("❌ Email required for login")
            print("Usage: ciris-manager auth login your-email@ciris.ai")
            return 1

        if not args.email.endswith("@ciris.ai"):
            print("❌ Only @ciris.ai email addresses are allowed")
            return 1

        token = auth.login(args.email)
        if token:
            print("\n🎉 You can now use authenticated API calls!")
            print(
                f'Example: curl -H "Authorization: Bearer $(ciris-manager auth token)" {auth.base_url}/manager/v1/agents'
            )
            return 0
        else:
            return 1

    elif args.auth_command == "logout":
        auth.logout()
        return 0

    elif args.auth_command == "status":
        auth.show_status()
        return 0

    elif args.auth_command == "token":
        token = auth.get_token()
        if token:
            print(token)
            return 0
        else:
            print(
                "Not authenticated. Run: ciris-manager auth login your-email@ciris.ai",
                file=sys.stderr,
            )
            return 1

    elif args.auth_command == "dev-token":
        token = auth.get_dev_token()
        if token:
            print("\n🎉 Dev token ready! You can now use the CLI:")
            print(f"   ciris-manager-client --api-url {auth.base_url} agent list")
            return 0
        else:
            return 1

    else:
        print(f"Unknown auth command: {args.auth_command}")
        return 1
