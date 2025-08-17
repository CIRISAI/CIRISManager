#!/usr/bin/env python3
"""
Fix version tracking state by initializing agent version history.

This script fixes the missing agent version history by:
1. Recording the current running version as 'n'
2. Promoting the staged version if needed
3. Recording historical versions if available
"""

import asyncio
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.version_tracker import get_version_tracker  # noqa: E402


async def fix_version_tracking():
    """Fix the version tracking state."""
    tracker = get_version_tracker()

    # First, let's check current state
    print("Current version state:")
    current_state = await tracker.get_rollback_options()
    print(json.dumps(current_state, indent=2))

    # The problem: agents has only n_plus_1 (staged), but no current version
    # We need to promote the staged version to current since Datum is running 1.4.3

    if current_state.get("agents", {}).get("staged") and not current_state.get("agents", {}).get(
        "current"
    ):
        print("\nAgent versions need fixing - no current version but staged exists")

        # Option 1: Promote the staged version to current
        # This is correct since Datum IS running 1.4.3
        print("Promoting staged agent version to current...")
        await tracker.promote_staged_version("agents", deployment_id="manual-fix-2025-08-17")

        # Now record the previous version (1.4.2) as n-1
        print("Recording previous version 1.4.2-beta as n-1...")
        # We need to manually set this in the state since we can't easily shift versions backward
        # Let's reload and check
        await tracker._load_state()

        # Create a version entry for 1.4.2
        from ciris_manager.version_tracker import ContainerVersion

        async with tracker._lock:
            state = tracker.state["agents"]

            # Create n-1 for the previous version
            if not state.n_minus_1:
                state.n_minus_1 = ContainerVersion(
                    image="ghcr.io/cirisai/ciris-agent:1.4.2-beta",
                    digest=None,
                    deployed_at="2025-08-15T23:00:00",  # Approximate
                    deployment_id="previous-deployment",
                    deployed_by="CD Pipeline",
                )

            # Save the state
            await tracker._save_state()

        print("Version history fixed!")
    else:
        print("\nVersion state looks different than expected")

    # Show final state
    print("\nFinal version state:")
    final_state = await tracker.get_rollback_options()
    print(json.dumps(final_state, indent=2))

    # Now check if rollback options are available
    print("\nRollback options for agents:")
    agent_options = await tracker.get_rollback_options("agents")
    if agent_options.get("n_minus_1"):
        print(f"  Can rollback to: {agent_options['n_minus_1']['image']}")
    else:
        print("  No rollback options available")


if __name__ == "__main__":
    asyncio.run(fix_version_tracking())
