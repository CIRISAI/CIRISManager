"""
Unit tests for telemetry schemas.

Tests type safety, validation, and serialization of all schema models.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from ciris_manager.telemetry.schemas import (
    ContainerStatus,
    HealthStatus,
    CognitiveState,
    DeploymentStatus,
    DeploymentPhase,
    ComponentType,
    ContainerResources,
    ContainerMetrics,
    AgentOperationalMetrics,
    DeploymentMetrics,
    VersionInfo,
    VersionState,
    AgentVersionAdoption,
    TelemetrySnapshot,
    SystemSummary,
    TelemetryQuery,
)


class TestEnums:
    """Test enum values match expected constants."""

    def test_container_status_values(self):
        """Test ContainerStatus enum has expected values."""
        assert ContainerStatus.RUNNING.value == "running"
        assert ContainerStatus.STOPPED.value == "stopped"
        assert ContainerStatus.EXITED.value == "exited"

    def test_cognitive_state_values(self):
        """Test CognitiveState enum matches CIRIS API."""
        assert CognitiveState.WORK.value == "WORK"
        assert CognitiveState.DREAM.value == "DREAM"
        assert CognitiveState.SHUTDOWN.value == "SHUTDOWN"

    def test_deployment_status_values(self):
        """Test DeploymentStatus enum matches models.py."""
        assert DeploymentStatus.STAGED.value == "staged"
        assert DeploymentStatus.IN_PROGRESS.value == "in_progress"
        assert DeploymentStatus.ROLLED_BACK.value == "rolled_back"

    def test_deployment_phase_values(self):
        """Test DeploymentPhase enum uses correct plurals."""
        assert DeploymentPhase.EXPLORERS.value == "explorers"
        assert DeploymentPhase.EARLY_ADOPTERS.value == "early_adopters"
        assert DeploymentPhase.GENERAL.value == "general"


class TestContainerMetrics:
    """Test container metrics models."""

    def test_container_resources_validation(self):
        """Test ContainerResources validates ranges."""
        # Valid resources
        resources = ContainerResources(
            cpu_percent=50.5,
            memory_mb=1024,
            memory_limit_mb=2048,
            memory_percent=50.0,
            disk_read_mb=100,
            disk_write_mb=200,
            network_rx_mb=10,
            network_tx_mb=20,
        )
        assert resources.cpu_percent == 50.5
        assert resources.memory_mb == 1024

        # CPU can exceed 100% for multi-core
        resources = ContainerResources(
            cpu_percent=250.0,  # 2.5 cores
            memory_mb=1024,
            memory_limit_mb=None,
            memory_percent=0.0,
            disk_read_mb=0,
            disk_write_mb=0,
            network_rx_mb=0,
            network_tx_mb=0,
        )
        assert resources.cpu_percent == 250.0

        # Invalid: negative values
        with pytest.raises(ValidationError):
            ContainerResources(
                cpu_percent=-1.0,
                memory_mb=1024,
                memory_limit_mb=2048,
                memory_percent=50.0,
                disk_read_mb=0,
                disk_write_mb=0,
                network_rx_mb=0,
                network_tx_mb=0,
            )

        # Invalid: memory percent > 100
        with pytest.raises(ValidationError):
            ContainerResources(
                cpu_percent=50.0,
                memory_mb=1024,
                memory_limit_mb=2048,
                memory_percent=101.0,
                disk_read_mb=0,
                disk_write_mb=0,
                network_rx_mb=0,
                network_tx_mb=0,
            )

    def test_container_metrics_creation(self):
        """Test ContainerMetrics model creation."""
        now = datetime.now(timezone.utc)

        resources = ContainerResources(
            cpu_percent=25.5,
            memory_mb=512,
            memory_limit_mb=1024,
            memory_percent=50.0,
            disk_read_mb=10,
            disk_write_mb=20,
            network_rx_mb=5,
            network_tx_mb=10,
        )

        metrics = ContainerMetrics(
            container_id="abc123def456",
            container_name="ciris-agent-datum",
            image="ghcr.io/cirisai/ciris-agent:latest",
            image_digest="sha256:abc123",
            status=ContainerStatus.RUNNING,
            health=HealthStatus.HEALTHY,
            restart_count=0,
            resources=resources,
            created_at=now,
            started_at=now,
            finished_at=None,
            exit_code=None,
            error_message=None,
        )

        assert metrics.container_name == "ciris-agent-datum"
        assert metrics.status == ContainerStatus.RUNNING
        assert metrics.health == HealthStatus.HEALTHY
        assert metrics.resources.cpu_percent == 25.5

    def test_container_metrics_strict_mode(self):
        """Test ContainerMetrics strict mode prevents extra fields."""
        now = datetime.now(timezone.utc)

        resources = ContainerResources(
            cpu_percent=0.0,
            memory_mb=0,
            memory_limit_mb=None,
            memory_percent=0.0,
            disk_read_mb=0,
            disk_write_mb=0,
            network_rx_mb=0,
            network_tx_mb=0,
        )

        # Should raise error for unexpected field
        with pytest.raises(ValidationError) as exc_info:
            ContainerMetrics(
                container_id="abc123def456",
                container_name="test",
                image="test:latest",
                image_digest=None,
                status=ContainerStatus.RUNNING,
                health=HealthStatus.NONE,
                restart_count=0,
                resources=resources,
                created_at=now,
                unexpected_field="should fail",  # Extra field
            )

        assert "unexpected_field" in str(exc_info.value)


class TestAgentMetrics:
    """Test agent operational metrics models."""

    def test_agent_metrics_creation(self):
        """Test AgentOperationalMetrics model."""
        metrics = AgentOperationalMetrics(
            agent_id="datum-abc123",
            agent_name="Datum",
            version="1.4.0",
            cognitive_state=CognitiveState.WORK,
            api_healthy=True,
            api_response_time_ms=150,
            uptime_seconds=3600,
            incident_count_24h=2,
            message_count_24h=1000,
            cost_cents_24h=250,
            carbon_24h_grams=50,
            api_port=8080,
            oauth_configured=True,
            oauth_providers=["google", "github"],
        )

        assert metrics.agent_id == "datum-abc123"
        assert metrics.cognitive_state == CognitiveState.WORK
        assert metrics.api_healthy is True
        assert metrics.cost_cents_24h == 250
        assert metrics.carbon_24h_grams == 50

    def test_agent_metrics_validation(self):
        """Test AgentOperationalMetrics validation."""
        # Invalid: negative uptime
        with pytest.raises(ValidationError):
            AgentOperationalMetrics(
                agent_id="test",
                agent_name="Test",
                version="1.0.0",
                cognitive_state=CognitiveState.WORK,
                api_healthy=True,
                api_response_time_ms=100,
                uptime_seconds=-1,  # Invalid
                incident_count_24h=0,
                message_count_24h=0,
                cost_cents_24h=0,
                carbon_24h_grams=0,
                api_port=8080,
                oauth_configured=False,
                oauth_providers=[],
            )

        # Invalid: port out of range
        with pytest.raises(ValidationError):
            AgentOperationalMetrics(
                agent_id="test",
                agent_name="Test",
                version="1.0.0",
                cognitive_state=CognitiveState.WORK,
                api_healthy=True,
                api_response_time_ms=100,
                uptime_seconds=0,
                incident_count_24h=0,
                message_count_24h=0,
                cost_cents_24h=0,
                carbon_24h_grams=0,
                api_port=70000,  # Invalid (> 65535)
                oauth_configured=False,
                oauth_providers=[],
            )


class TestDeploymentMetrics:
    """Test deployment metrics models."""

    def test_deployment_metrics_creation(self):
        """Test DeploymentMetrics model."""
        now = datetime.now(timezone.utc)

        metrics = DeploymentMetrics(
            deployment_id="deploy-123",
            status=DeploymentStatus.IN_PROGRESS,
            phase=DeploymentPhase.EXPLORERS,
            agent_image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            gui_image="ghcr.io/cirisai/ciris-gui:v1.2.0",
            nginx_image=None,
            agents_total=5,
            agents_staged=5,
            agents_updated=2,
            agents_failed=0,
            agents_deferred=1,
            created_at=now,
            staged_at=now,
            started_at=now,
            completed_at=None,
            initiated_by="github-actions",
            approved_by=None,
            is_rollback=False,
            rollback_from_deployment=None,
        )

        assert metrics.deployment_id == "deploy-123"
        assert metrics.status == DeploymentStatus.IN_PROGRESS
        assert metrics.phase == DeploymentPhase.EXPLORERS
        assert metrics.agents_updated == 2

    def test_deployment_metrics_rollback(self):
        """Test DeploymentMetrics for rollback scenario."""
        now = datetime.now(timezone.utc)

        metrics = DeploymentMetrics(
            deployment_id="rollback-456",
            status=DeploymentStatus.ROLLING_BACK,
            phase=None,
            agent_image="ghcr.io/cirisai/ciris-agent:v1.3.0",
            gui_image=None,
            nginx_image=None,
            agents_total=5,
            agents_staged=0,
            agents_updated=0,
            agents_failed=0,
            agents_deferred=0,
            created_at=now,
            staged_at=None,
            started_at=now,
            completed_at=None,
            initiated_by="operator",
            approved_by="operator",
            is_rollback=True,
            rollback_from_deployment="deploy-123",
        )

        assert metrics.is_rollback is True
        assert metrics.rollback_from_deployment == "deploy-123"
        assert metrics.status == DeploymentStatus.ROLLING_BACK


class TestVersionTracking:
    """Test version tracking models."""

    def test_version_info_creation(self):
        """Test VersionInfo model."""
        now = datetime.now(timezone.utc)

        version = VersionInfo(
            image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            digest="sha256:abc123def456",
            tag="v1.4.0",
            deployed_at=now,
            deployment_id="deploy-123",
        )

        assert version.image == "ghcr.io/cirisai/ciris-agent:v1.4.0"
        assert version.tag == "v1.4.0"
        assert version.deployment_id == "deploy-123"

    def test_version_state_creation(self):
        """Test VersionState model."""
        now = datetime.now(timezone.utc)

        current = VersionInfo(
            image="ghcr.io/cirisai/ciris-agent:v1.4.0",
            digest="sha256:current",
            tag="v1.4.0",
            deployed_at=now,
            deployment_id="deploy-3",
        )

        previous = VersionInfo(
            image="ghcr.io/cirisai/ciris-agent:v1.3.0",
            digest="sha256:previous",
            tag="v1.3.0",
            deployed_at=now,
            deployment_id="deploy-2",
        )

        state = VersionState(
            component_type=ComponentType.AGENT,
            current=current,
            previous=previous,
            fallback=None,
            staged=None,
            last_updated=now,
        )

        assert state.component_type == ComponentType.AGENT
        assert state.current.tag == "v1.4.0"
        assert state.previous.tag == "v1.3.0"
        assert state.fallback is None

    def test_agent_version_adoption(self):
        """Test AgentVersionAdoption model."""
        now = datetime.now(timezone.utc)

        adoption = AgentVersionAdoption(
            agent_id="datum-abc123",
            agent_name="Datum",
            current_version="v1.4.0",
            last_transition_at=now,
            last_work_state_at=now,
            deployment_group="explorers",
        )

        assert adoption.deployment_group == "explorers"
        assert adoption.current_version == "v1.4.0"

        # Test valid deployment groups
        for group in ["explorers", "early_adopters", "general"]:
            adoption = AgentVersionAdoption(
                agent_id="test",
                agent_name="Test",
                current_version="v1.0.0",
                last_transition_at=None,
                last_work_state_at=None,
                deployment_group=group,
            )
            assert adoption.deployment_group == group

        # Invalid deployment group
        with pytest.raises(ValidationError):
            AgentVersionAdoption(
                agent_id="test",
                agent_name="Test",
                current_version="v1.0.0",
                last_transition_at=None,
                last_work_state_at=None,
                deployment_group="invalid_group",
            )


class TestTelemetrySnapshot:
    """Test complete telemetry snapshot model."""

    def test_snapshot_creation(self):
        """Test TelemetrySnapshot model."""
        now = datetime.now(timezone.utc)

        # Create sample data
        container = ContainerMetrics(
            container_id="abc123def456",
            container_name="ciris-agent-test",
            image="test:latest",
            image_digest=None,
            status=ContainerStatus.RUNNING,
            health=HealthStatus.HEALTHY,
            restart_count=0,
            resources=ContainerResources(
                cpu_percent=10.0,
                memory_mb=256,
                memory_limit_mb=512,
                memory_percent=50.0,
                disk_read_mb=0,
                disk_write_mb=0,
                network_rx_mb=0,
                network_tx_mb=0,
            ),
            created_at=now,
            started_at=now,
            finished_at=None,
            exit_code=None,
            error_message=None,
        )

        agent = AgentOperationalMetrics(
            agent_id="test",
            agent_name="Test",
            version="1.0.0",
            cognitive_state=CognitiveState.WORK,
            api_healthy=True,
            api_response_time_ms=100,
            uptime_seconds=3600,
            incident_count_24h=0,
            message_count_24h=100,
            cost_cents_24h=10,
            carbon_24h_grams=5,
            api_port=8080,
            oauth_configured=False,
            oauth_providers=[],
        )

        deployment = DeploymentMetrics(
            deployment_id="deploy-1",
            status=DeploymentStatus.COMPLETED,
            phase=DeploymentPhase.GENERAL,
            agent_image="test:latest",
            gui_image=None,
            nginx_image=None,
            agents_total=1,
            agents_staged=0,
            agents_updated=1,
            agents_failed=0,
            agents_deferred=0,
            created_at=now,
            staged_at=None,
            started_at=now,
            completed_at=now,
            initiated_by="test",
            approved_by="test",
            is_rollback=False,
            rollback_from_deployment=None,
        )

        version = VersionState(
            component_type=ComponentType.AGENT,
            current=VersionInfo(
                image="test:latest",
                digest=None,
                tag="latest",
                deployed_at=now,
                deployment_id="deploy-1",
            ),
            previous=None,
            fallback=None,
            staged=None,
            last_updated=now,
        )

        adoption = AgentVersionAdoption(
            agent_id="test",
            agent_name="Test",
            current_version="1.0.0",
            last_transition_at=now,
            last_work_state_at=now,
            deployment_group="general",
        )

        # Create snapshot
        snapshot = TelemetrySnapshot(
            snapshot_id="snap-123",
            timestamp=now,
            containers=[container],
            agents=[agent],
            deployments=[deployment],
            versions=[version],
            adoption=[adoption],
            collection_duration_ms=1500,
            errors=[],
        )

        assert snapshot.snapshot_id == "snap-123"
        assert len(snapshot.containers) == 1
        assert len(snapshot.agents) == 1
        assert snapshot.collection_duration_ms == 1500
        assert len(snapshot.errors) == 0

    def test_snapshot_with_errors(self):
        """Test TelemetrySnapshot with collection errors."""
        now = datetime.now(timezone.utc)

        snapshot = TelemetrySnapshot(
            snapshot_id="snap-error",
            timestamp=now,
            containers=[],
            agents=[],
            deployments=[],
            versions=[],
            adoption=[],
            collection_duration_ms=30000,
            errors=["Docker API timeout", "Agent health check failed"],
        )

        assert len(snapshot.errors) == 2
        assert "Docker API timeout" in snapshot.errors


class TestSystemSummary:
    """Test aggregated system summary model."""

    def test_system_summary_creation(self):
        """Test SystemSummary model."""
        now = datetime.now(timezone.utc)

        summary = SystemSummary(
            timestamp=now,
            agents_total=5,
            agents_healthy=3,
            agents_degraded=1,
            agents_down=1,
            agents_in_work=2,
            agents_in_dream=1,
            agents_in_solitude=0,
            agents_in_play=0,
            total_cpu_percent=125.5,
            total_memory_mb=4096,
            total_cost_cents_24h=500,
            total_messages_24h=10000,
            total_incidents_24h=5,
            active_deployments=1,
            staged_deployments=0,
            agents_on_latest=3,
            agents_on_previous=1,
            agents_on_older=1,
        )

        assert summary.agents_total == 5
        assert summary.agents_healthy == 3
        assert summary.total_cost_cents_24h == 500

    def test_system_summary_validation(self):
        """Test SystemSummary validation."""
        now = datetime.now(timezone.utc)

        # All counts must be non-negative
        with pytest.raises(ValidationError):
            SystemSummary(
                timestamp=now,
                agents_total=-1,  # Invalid
                agents_healthy=0,
                agents_degraded=0,
                agents_down=0,
                agents_in_work=0,
                agents_in_dream=0,
                agents_in_solitude=0,
                agents_in_play=0,
                total_cpu_percent=0.0,
                total_memory_mb=0,
                total_cost_cents_24h=0,
                total_messages_24h=0,
                total_incidents_24h=0,
                active_deployments=0,
                staged_deployments=0,
                agents_on_latest=0,
                agents_on_previous=0,
                agents_on_older=0,
            )


class TestQueryModels:
    """Test telemetry query and response models."""

    def test_telemetry_query_creation(self):
        """Test TelemetryQuery model."""
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now

        query = TelemetryQuery(
            start_time=start,
            end_time=end,
            agent_ids=["datum-abc123", "sage-def456"],
            container_names=None,
            include_resources=True,
            include_deployments=False,
            include_versions=True,
            interval="1h",
            limit=100,
            offset=0,
        )

        assert query.start_time == start
        assert query.end_time == end
        assert len(query.agent_ids) == 2
        assert query.interval == "1h"

    def test_telemetry_query_validation(self):
        """Test TelemetryQuery validation."""
        now = datetime.now(timezone.utc)

        # Invalid interval
        with pytest.raises(ValidationError):
            TelemetryQuery(
                start_time=now,
                end_time=now,
                interval="2h",  # Not in allowed values
            )

        # Invalid limit
        with pytest.raises(ValidationError):
            TelemetryQuery(
                start_time=now,
                end_time=now,
                limit=20000,  # > 10000
            )

        # Negative offset
        with pytest.raises(ValidationError):
            TelemetryQuery(
                start_time=now,
                end_time=now,
                offset=-1,
            )
