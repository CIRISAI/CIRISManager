#!/usr/bin/env python3
"""
Create scout agent by directly importing and using the CIRISManager class.
Bypasses API authentication completely.
"""

import asyncio
import sys

# Add manager to path
sys.path.insert(0, "/opt/ciris-manager")

from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.manager import CIRISManager


async def main():
    print("=" * 70)
    print(" Create Scout Agent (Direct Manager Method)")
    print("=" * 70)

    # Load config
    print("\n[1/3] Loading manager configuration...")
    config = CIRISManagerConfig.from_file("/etc/ciris-manager/config.yml")
    print("✓ Config loaded")

    # Initialize manager
    print("\n[2/3] Initializing manager...")
    manager = CIRISManager(config)
    print("✓ Manager initialized")

    # Create agent
    print("\n[3/3] Creating scout agent on scout server...")
    try:
        result = await manager.create_agent(
            template="scout",
            name="scout-labels-test",
            server_id="scout",
            use_mock_llm=True,
            environment={
                "OAUTH_CALLBACK_BASE_URL": "https://scoutapi.ciris.ai",
            },
        )

        print("\n✅ Agent created successfully!")
        print(f"   Agent ID: {result['agent_id']}")
        print(f"   Port: {result['port']}")
        print(f"   Status: {result['status']}")

        # Wait for container to start
        print("\n[Bonus] Checking Docker labels...")
        await asyncio.sleep(5)

        # Get Docker client for scout server and check labels
        agent_id = result["agent_id"]
        docker_client = manager.docker_client.get_client("scout")
        container = docker_client.containers.get(f"ciris-{agent_id}")
        labels = container.labels

        if "ai.ciris.agents.id" in labels:
            print("✓ Docker labels are present!")
            print(f"   ai.ciris.agents.id: {labels.get('ai.ciris.agents.id')}")
            print(f"   ai.ciris.agents.template: {labels.get('ai.ciris.agents.template')}")
            print(
                f"   ai.ciris.agents.deployment_group: {labels.get('ai.ciris.agents.deployment_group')}"
            )
        else:
            print("✗ Docker labels are MISSING!")
            print(f"   Available labels: {list(labels.keys())}")

    except Exception as e:
        print(f"\n✗ Failed to create agent: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 70)
    print(" ✅ Complete!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
