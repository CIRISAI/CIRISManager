"""
Tests for version tracking system.
"""

import pytest
import tempfile
from ciris_manager.version_tracker import VersionTracker


class TestVersionTracker:
    """Test version tracking functionality."""

    @pytest.fixture
    async def tracker(self):
        """Create a temporary version tracker for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = VersionTracker(data_dir=tmpdir)
            yield tracker

    @pytest.mark.asyncio
    async def test_stage_version(self, tracker):
        """Test staging a new version as n+1."""
        # Stage a new version
        await tracker.stage_version(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.4",
            digest="sha256:abc123",
            deployment_id="test-deploy-1",
            deployed_by="test",
        )

        # Check it's staged as n+1
        rollback_options = await tracker.get_rollback_options("agent")
        assert rollback_options["staged"] is not None
        assert rollback_options["staged"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert rollback_options["staged"]["digest"] == "sha256:abc123"
        assert rollback_options["current"] is None  # No current version yet

    @pytest.mark.asyncio
    async def test_promote_staged_version(self, tracker):
        """Test promoting n+1 to n."""
        # First record some history
        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
            digest="sha256:old2",
            deployment_id="deploy-2",
            deployed_by="test",
        )

        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.3",
            digest="sha256:old3",
            deployment_id="deploy-3",
            deployed_by="test",
        )

        # Stage a new version
        await tracker.stage_version(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.4",
            digest="sha256:new4",
            deployment_id="deploy-4",
            deployed_by="test",
        )

        # Promote staged to current
        await tracker.promote_staged_version("agent", "deploy-4")

        # Check the progression
        rollback_options = await tracker.get_rollback_options("agent")
        assert rollback_options["staged"] is None  # n+1 should be cleared
        assert rollback_options["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert rollback_options["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"
        assert rollback_options["n_minus_2"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.2"

    @pytest.mark.asyncio
    async def test_deployment_flow(self, tracker):
        """Test the full deployment flow: stage -> deploy -> promote."""
        # Simulate existing production state
        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.1",
            deployment_id="prod-1",
        )
        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.2",
            deployment_id="prod-2",
        )
        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.3",
            deployment_id="prod-3",
        )

        # Check current state (v1.4.3 should be n)
        rollback = await tracker.get_rollback_options("agent")
        assert rollback["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"
        assert rollback["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.2"
        assert rollback["n_minus_2"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.1"
        assert rollback["staged"] is None

        # Stage v1.4.4 for deployment
        await tracker.stage_version(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.4",
            digest="sha256:4a550fc548c32c87e2279918bd685be0635ac3de64e01c022dfc679592d63cba",
            deployment_id="staged-deploy-4",
            deployed_by="cd-system",
        )

        # Check staged state
        rollback = await tracker.get_rollback_options("agent")
        assert rollback["staged"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert rollback["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"  # Still v1.4.3

        # Promote after successful deployment
        await tracker.promote_staged_version("agent", "staged-deploy-4")

        # Check final state
        rollback = await tracker.get_rollback_options("agent")
        assert rollback["staged"] is None  # Cleared after promotion
        assert rollback["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert rollback["n_minus_1"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"
        assert rollback["n_minus_2"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.2"

    @pytest.mark.asyncio
    async def test_record_deployment_clears_staged(self, tracker):
        """Test that record_deployment clears any staged version."""
        # Stage a version
        await tracker.stage_version(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.4",
            deployment_id="staged-1",
        )

        # Verify it's staged
        rollback = await tracker.get_rollback_options("agent")
        assert rollback["staged"] is not None

        # Record a direct deployment (bypasses staging)
        await tracker.record_deployment(
            container_type="agent",
            image="ghcr.io/cirisai/ciris-agent:v1.4.5",
            deployment_id="direct-1",
        )

        # Staged should be cleared
        rollback = await tracker.get_rollback_options("agent")
        assert rollback["staged"] is None
        assert rollback["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.5"

    @pytest.mark.asyncio
    async def test_get_version_history(self, tracker):
        """Test getting version history with and without staged."""
        # Set up some versions
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.1")
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.2")
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.3")
        await tracker.stage_version("agent", "ghcr.io/cirisai/ciris-agent:v1.4.4")

        # Get history without staged
        history = await tracker.get_version_history("agent", include_staged=False)
        assert len(history) == 3
        assert history[0]["position"] == "n"
        assert history[0]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"

        # Get history with staged
        history_with_staged = await tracker.get_version_history("agent", include_staged=True)
        assert len(history_with_staged) == 4
        assert history_with_staged[0]["position"] == "n+1"
        assert history_with_staged[0]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert history_with_staged[1]["position"] == "n"
        assert history_with_staged[1]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"

    @pytest.mark.asyncio
    async def test_clear_staged(self, tracker):
        """Test clearing staged versions."""
        # Stage versions for multiple container types
        await tracker.stage_version("agent", "ghcr.io/cirisai/ciris-agent:v1.4.4")
        await tracker.stage_version("gui", "ghcr.io/cirisai/ciris-gui:v2.0.0")

        # Clear specific staged version
        await tracker.clear_staged("agent")

        rollback = await tracker.get_rollback_options()
        assert rollback["agent"]["staged"] is None
        assert rollback["gui"]["staged"]["image"] == "ghcr.io/cirisai/ciris-gui:v2.0.0"

        # Clear all staged versions
        await tracker.clear_staged()

        rollback = await tracker.get_rollback_options()
        assert rollback["agent"]["staged"] is None
        assert rollback["gui"]["staged"] is None

    @pytest.mark.asyncio
    async def test_validate_rollback(self, tracker):
        """Test rollback validation."""
        # Set up version history
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.1")
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.2")
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.3")

        # Validate rollback to known version
        result = await tracker.validate_rollback({"agent": "ghcr.io/cirisai/ciris-agent:v1.4.2"})
        assert result["valid"] is True
        assert len(result["warnings"]) == 0

        # Validate rollback to unknown version
        result = await tracker.validate_rollback({"agent": "ghcr.io/cirisai/ciris-agent:v0.9.9"})
        assert result["valid"] is True  # Still valid, just with warning
        assert len(result["warnings"]) == 1
        assert "not in tracked history" in result["warnings"][0]

    @pytest.mark.asyncio
    async def test_persistence(self, tracker):
        """Test that state persists across tracker instances."""
        # Set up some state
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.3")
        await tracker.stage_version("agent", "ghcr.io/cirisai/ciris-agent:v1.4.4")

        # Create new tracker with same data dir
        tracker2 = VersionTracker(data_dir=tracker.data_dir)
        rollback = await tracker2.get_rollback_options("agent")

        # Should load persisted state
        assert rollback["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"
        assert rollback["staged"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"

    @pytest.mark.asyncio
    async def test_container_type_separation(self, tracker):
        """Test that different container types maintain separate histories."""
        # Set up different versions for different types
        await tracker.record_deployment("agent", "ghcr.io/cirisai/ciris-agent:v1.4.3")
        await tracker.record_deployment("gui", "ghcr.io/cirisai/ciris-gui:v2.0.0")
        await tracker.stage_version("agent", "ghcr.io/cirisai/ciris-agent:v1.4.4")
        await tracker.stage_version("gui", "ghcr.io/cirisai/ciris-gui:v2.1.0")

        # Check they're separate
        rollback = await tracker.get_rollback_options()
        assert rollback["agent"]["current"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.3"
        assert rollback["agent"]["staged"]["image"] == "ghcr.io/cirisai/ciris-agent:v1.4.4"
        assert rollback["gui"]["current"]["image"] == "ghcr.io/cirisai/ciris-gui:v2.0.0"
        assert rollback["gui"]["staged"]["image"] == "ghcr.io/cirisai/ciris-gui:v2.1.0"
