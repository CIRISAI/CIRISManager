#!/usr/bin/env python3
"""Create test agent on main server to verify labels fix."""

import asyncio
import sys

sys.path.insert(0, "/opt/ciris-manager")

from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.manager import CIRISManager


async def main():
    print("=" * 70)
    print(" Create Test Agent on Main Server (Verify Labels Fix)")
    print("=" * 70)

    config = CIRISManagerConfig.from_file("/etc/ciris-manager/config.yml")
    manager = CIRISManager(config)

    print("\n[1/2] Creating test agent on main server...")
    try:
        result = await manager.create_agent(
            template="scout",
            name="labels-test",
            server_id="main",  # Create on main server
            use_mock_llm=True,
        )

        print("\n✅ Agent created successfully!")
        print(f"   Agent ID: {result['agent_id']}")
        print(f"   Port: {result['port']}")

        # Check Docker labels
        print("\n[2/2] Checking Docker labels...")
        await asyncio.sleep(3)

        agent_id = result["agent_id"]
        docker_client = manager.docker_client.get_client("main")
        container = docker_client.containers.get(f"ciris-{agent_id}")
        labels = container.labels

        print(f"\nDocker labels for {agent_id}:")
        if "ai.ciris.agents.id" in labels:
            print("✅ LABELS PRESENT!")
            print(f"   ai.ciris.agents.id: {labels.get('ai.ciris.agents.id')}")
            print(f"   ai.ciris.agents.template: {labels.get('ai.ciris.agents.template')}")
            print(
                f"   ai.ciris.agents.deployment_group: {labels.get('ai.ciris.agents.deployment_group')}"
            )
        else:
            print("✗ LABELS MISSING!")
            print(f"   Available labels: {list(labels.keys())}")

    except Exception as e:
        print(f"\n✗ Failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
