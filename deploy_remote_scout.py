#!/usr/bin/env python3
"""
Deploy a new remote scout agent by copying existing scout config (without Discord).
"""

import sys
from pathlib import Path

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent))

from ciris_manager.sdk import CIRISManagerClient


def main():
    # Initialize client (will load token from ~/.manager_token)
    client = CIRISManagerClient()

    # Get existing scout configuration
    print("Fetching existing scout-u7e9s3 configuration...")
    source_config = client.get_agent_config("scout-u7e9s3")
    source_env = source_config["environment"]

    # Create new environment without Discord variables
    new_env = {}
    discord_vars = [
        "DISCORD_SERVER_ID",
        "DISCORD_BOT_TOKEN",
        "DISCORD_DEFERRAL_CHANNEL_ID",
        "DISCORD_CHANNEL_IDS",
    ]

    print("\nCopying environment variables (excluding Discord):")
    for key, value in source_env.items():
        if key not in discord_vars:
            new_env[key] = value
            print(f"  ✓ {key}")
        else:
            print(f"  ✗ {key} (skipped - Discord variable)")

    # Change adapter to API only
    new_env["CIRIS_ADAPTER"] = "api"
    print("\n  ✓ Changed CIRIS_ADAPTER to: api")

    # Update OAuth callback URL for scout server
    new_env["OAUTH_CALLBACK_BASE_URL"] = "https://scoutapi.ciris.ai"
    print("  ✓ Changed OAUTH_CALLBACK_BASE_URL to: https://scoutapi.ciris.ai")

    print(f"\nTotal variables: {len(new_env)}")
    print(f"Removed: {len(source_env) - len(new_env)}")

    # Deploy new agent
    print("\n" + "=" * 80)
    print("Creating new remote scout agent...")
    print("Server: scout (scoutapi.ciris.ai)")
    print("Template: scout")
    print("Adapters: API only (no Discord)")
    print("=" * 80 + "\n")

    try:
        result = client.create_agent(
            name="scout-remote-test",
            template="scout",
            environment=new_env,
            server_id="scout",
            use_mock_llm=False,
            enable_discord=False,
            billing_enabled=True,
            billing_api_key=new_env.get("CIRIS_BILLING_API_KEY"),
        )
    except Exception as e:
        print(f"\n❌ Failed to create agent: {e}")
        if hasattr(e, "response") and e.response:
            print(f"API Response: {e.response}")
        if hasattr(e, "status_code"):
            print(f"Status Code: {e.status_code}")
        raise

    print("\n✅ Agent created successfully!")
    print(f"Agent ID: {result['agent_id']}")
    print(f"Container: {result['container']}")
    print(f"Port: {result['port']}")
    print(f"Status: {result['status']}")

    agent_id = result["agent_id"]

    # Instructions to verify OAuth
    print("\n" + "=" * 80)
    print("To verify OAuth configuration:")
    print("=" * 80)
    print("\n1. Check OAuth files on scout server:")
    print("   ssh -i ~/.ssh/ciris_deploy root@scoutapi.ciris.ai")
    print(f"   docker exec ciris-{agent_id} ls -la /home/ciris/shared/oauth")
    print("\n2. View container logs:")
    print(f"   docker logs ciris-{agent_id}")
    print("\n3. Check agent status via API:")
    print(f"   python get_agent_config.py {agent_id}")

    return agent_id


if __name__ == "__main__":
    agent_id = main()
