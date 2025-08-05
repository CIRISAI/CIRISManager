#!/usr/bin/env python3
"""
CIRIS Manager CLI authentication module.
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

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
                url,
                json={"client_id": "ciris-cli", "scope": "manager:full"},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to request device code: {e}")
            sys.exit(1)
    
    def poll_for_token(self, device_code: str, interval: int = 5, timeout: int = 600) -> Optional[str]:
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
                        "client_id": "ciris-cli"
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("access_token")
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
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        token_data = {
            "token": token,
            "email": email,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.utcnow().isoformat()
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
            
            return data
        except Exception:
            return None
    
    def login(self, email: str) -> Optional[str]:
        """Perform device flow authentication."""
        # Check for existing valid token
        token_data = self.load_token()
        if token_data and token_data.get("email") == email:
            if self.test_token(token_data["token"]):
                print(f"✅ Using saved token for {email}")
                return token_data["token"]
        
        print(f"🔐 Authenticating {email} with CIRIS Manager...")
        
        # Request device code
        device_data = self.request_device_code()
        
        print("\n" + "="*60)
        print(f"🌐 Please visit: {device_data['verification_uri']}")
        print(f"📝 Enter code: {device_data['user_code']}")
        print("="*60 + "\n")
        
        # Debug: show device code (first 10 chars)
        print(f"[DEBUG] Device code: {device_data['device_code'][:10]}...")
        
        print("⏳ Waiting for authorization", end="", flush=True)
        
        # Poll for token
        token = self.poll_for_token(
            device_data["device_code"],
            device_data.get("interval", 5)
        )
        
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
                timeout=5
            )
            return response.status_code == 200
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
            return token_data["token"]
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


def handle_auth_command(args) -> int:
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
            print(f"Example: curl -H \"Authorization: Bearer $(ciris-manager auth token)\" {auth.base_url}/manager/v1/agents")
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
            print("Not authenticated. Run: ciris-manager auth login your-email@ciris.ai", file=sys.stderr)
            return 1
    
    else:
        print(f"Unknown auth command: {args.auth_command}")
        return 1