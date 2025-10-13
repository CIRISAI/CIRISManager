#!/usr/bin/env python3
"""
Get agent configuration including environment variables using the CIRISManager SDK.
"""

import sys
import json
from pathlib import Path

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent))

from ciris_manager.sdk import CIRISManagerClient


def main():
    if len(sys.argv) < 2:
        print("Usage: python get_agent_config.py <agent_id>")
        print("\nExample: python get_agent_config.py scout-u7e9s3")
        sys.exit(1)

    agent_id = sys.argv[1]

    # Initialize client (will load token from ~/.manager_token)
    client = CIRISManagerClient()

    print(f"Fetching configuration for agent: {agent_id}\n")

    # Get agent config (includes environment variables)
    config = client.get_agent_config(agent_id)

    print(f"Agent ID: {config['agent_id']}")
    print(f"Compose File: {config['compose_file']}\n")

    print("Environment Variables:")
    print("=" * 80)

    # Sort environment variables for easier reading
    env = config.get("environment", {})
    for key in sorted(env.keys()):
        value = env[key]
        # Truncate long values for readability
        if len(str(value)) > 60:
            value = str(value)[:57] + "..."
        print(f"{key}: {value}")

    print("\n" + "=" * 80)
    print(f"Total environment variables: {len(env)}")

    # Identify Discord-related variables
    discord_vars = [k for k in env.keys() if "DISCORD" in k.upper()]
    if discord_vars:
        print(f"\nDiscord-related variables: {', '.join(discord_vars)}")

    # Save to JSON file
    output_file = f"{agent_id}_config.json"
    with open(output_file, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nFull configuration saved to: {output_file}")


if __name__ == "__main__":
    main()
