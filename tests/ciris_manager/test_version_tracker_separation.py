"""
Test that GUI and Agent rollback options are properly separated.
"""

import pytest
import json
from pathlib import Path
from ciris_manager.version_tracker import VersionTracker


@pytest.mark.asyncio
async def test_version_tracker_separate_containers():
    """Test that agent and gui versions are tracked separately."""
    tracker = VersionTracker("/tmp/test-versions")

    # Record agent deployment
    await tracker.record_deployment(
        "agent", "ghcr.io/cirisai/ciris-agent:1.0.0", deployment_id="agent-deploy-1"
    )

    # Record GUI deployment
    await tracker.record_deployment(
        "gui", "ghcr.io/cirisai/ciris-gui:2.0.0", deployment_id="gui-deploy-1"
    )

    # Get rollback options
    options = await tracker.get_rollback_options()

    # Verify they are separate
    assert "agent" in options
    assert "gui" in options

    agent_current = options["agent"]["current"]
    gui_current = options["gui"]["current"]

    assert agent_current["image"] == "ghcr.io/cirisai/ciris-agent:1.0.0"
    assert gui_current["image"] == "ghcr.io/cirisai/ciris-gui:2.0.0"


@pytest.mark.asyncio
async def test_gui_updates_dont_affect_agent_rollback():
    """Test that GUI updates don't overwrite agent rollback history."""
    tracker = VersionTracker("/tmp/test-versions")

    # Record initial agent versions
    await tracker.record_deployment(
        "agent", "ghcr.io/cirisai/ciris-agent:1.0.0", deployment_id="agent-1"
    )
    await tracker.record_deployment(
        "agent", "ghcr.io/cirisai/ciris-agent:1.0.1", deployment_id="agent-2"
    )
    await tracker.record_deployment(
        "agent", "ghcr.io/cirisai/ciris-agent:1.0.2", deployment_id="agent-3"
    )

    # Now deploy GUI multiple times
    await tracker.record_deployment("gui", "ghcr.io/cirisai/ciris-gui:2.0.0", deployment_id="gui-1")
    await tracker.record_deployment("gui", "ghcr.io/cirisai/ciris-gui:2.0.1", deployment_id="gui-2")

    # Get rollback options
    options = await tracker.get_rollback_options()

    # Verify agent rollback history is intact
    agent_options = options["agent"]
    assert agent_options["current"]["image"] == "ghcr.io/cirisai/ciris-agent:1.0.2"
    assert agent_options["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-agent:1.0.1"
    assert agent_options["n_minus_2"]["image"] == "ghcr.io/cirisai/ciris-agent:1.0.0"

    # Verify GUI has its own history
    gui_options = options["gui"]
    assert gui_options["current"]["image"] == "ghcr.io/cirisai/ciris-gui:2.0.1"
    assert gui_options["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-gui:2.0.0"


@pytest.mark.asyncio
async def test_legacy_agents_migration():
    """Test that legacy 'agents' data is migrated to 'agent'."""
    tracker = VersionTracker("/tmp/test-legacy")

    # Create legacy data file
    legacy_data = {
        "agents": {
            "n": {"image": "ghcr.io/cirisai/ciris-agent:0.9.0"},
            "n_minus_1": {"image": "ghcr.io/cirisai/ciris-agent:0.8.0"},
            "n_minus_2": None,
            "n_plus_1": None,
        },
        "gui": {
            "n": {"image": "ghcr.io/cirisai/ciris-gui:1.0.0"},
            "n_minus_1": None,
            "n_minus_2": None,
            "n_plus_1": None,
        },
    }

    # Write legacy file
    version_file = Path("/tmp/test-legacy/version_state.json")
    version_file.parent.mkdir(parents=True, exist_ok=True)
    with open(version_file, "w") as f:
        json.dump(legacy_data, f)

    # Load tracker - should migrate
    await tracker._load_state()

    # Get options
    options = await tracker.get_rollback_options()

    # Verify migration worked
    assert "agent" in options
    assert options["agent"]["current"]["image"] == "ghcr.io/cirisai/ciris-agent:0.9.0"
    assert options["agent"]["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-agent:0.8.0"


@pytest.mark.asyncio
async def test_independent_staging():
    """Test that agent and GUI can have independent staged versions."""
    tracker = VersionTracker("/tmp/test-staging")

    # Stage agent version
    await tracker.stage_version(
        "agent", "ghcr.io/cirisai/ciris-agent:1.1.0-rc1", deployment_id="agent-stage-1"
    )

    # Stage GUI version
    await tracker.stage_version(
        "gui", "ghcr.io/cirisai/ciris-gui:2.1.0-rc1", deployment_id="gui-stage-1"
    )

    # Get rollback options (which includes staged)
    options = await tracker.get_rollback_options()

    # Verify both have independent staged versions
    assert options["agent"]["staged"]["image"] == "ghcr.io/cirisai/ciris-agent:1.1.0-rc1"
    assert options["gui"]["staged"]["image"] == "ghcr.io/cirisai/ciris-gui:2.1.0-rc1"

    # Promote only agent
    await tracker.promote_staged_version("agent", "agent-deploy-1")

    # Verify agent promoted, GUI still staged
    options = await tracker.get_rollback_options()
    assert options["agent"]["current"]["image"] == "ghcr.io/cirisai/ciris-agent:1.1.0-rc1"
    assert options["agent"]["staged"] is None
    assert options["gui"]["staged"]["image"] == "ghcr.io/cirisai/ciris-gui:2.1.0-rc1"
