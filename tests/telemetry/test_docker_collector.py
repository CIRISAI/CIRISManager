"""
Unit tests for Docker container metrics collector.

Tests the DockerCollector implementation with mocked Docker API.
"""

import pytest
from unittest.mock import Mock, patch
import docker

from ciris_manager.telemetry.collectors.docker_collector import DockerCollector
from ciris_manager.telemetry.schemas import (
    ContainerStatus,
    HealthStatus,
)


class TestDockerCollector:
    """Test DockerCollector functionality."""

    @pytest.fixture
    def mock_docker_client(self):
        """Create mock Docker client."""
        client = Mock(spec=docker.DockerClient)
        client.ping = Mock(return_value=True)
        return client

    @pytest.fixture
    def mock_container(self):
        """Create mock container with typical attributes."""
        container = Mock()
        container.short_id = "abc123def456"
        container.name = "ciris-agent-datum"
        container.status = "running"

        # Mock attrs for detailed info
        container.attrs = {
            "Created": "2025-01-01T12:00:00Z",
            "State": {
                "Status": "running",
                "StartedAt": "2025-01-01T12:00:00Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Health": {"Status": "healthy"},
                "ExitCode": 0,
            },
            "Config": {"Image": "ghcr.io/cirisai/ciris-agent:latest"},
            "Image": "sha256:abcdef123456",
            "RestartCount": 0,
        }

        # Mock stats for resource usage
        container.stats = Mock(
            return_value={
                "cpu_stats": {
                    "cpu_usage": {
                        "total_usage": 1000000000,
                        "percpu_usage": [500000000, 500000000],
                    },
                    "system_cpu_usage": 10000000000,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 900000000},
                    "system_cpu_usage": 9500000000,
                },
                "memory_stats": {
                    "usage": 268435456,  # 256 MB
                    "limit": 536870912,  # 512 MB
                },
                "blkio_stats": {
                    "io_service_bytes_recursive": [
                        {"op": "Read", "value": 10485760},  # 10 MB
                        {"op": "Write", "value": 20971520},  # 20 MB
                    ]
                },
                "networks": {
                    "eth0": {
                        "rx_bytes": 5242880,  # 5 MB
                        "tx_bytes": 10485760,  # 10 MB
                    }
                },
            }
        )

        container.reload = Mock()
        return container

    @pytest.mark.asyncio
    async def test_initialization(self, mock_docker_client):
        """Test collector initialization."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            assert collector.name == "DockerCollector"
            assert collector.timeout_seconds == 30
            assert collector.client == mock_docker_client

    @pytest.mark.asyncio
    async def test_docker_not_available(self):
        """Test handling when Docker is not available."""
        with patch("docker.from_env", side_effect=Exception("Docker not found")):
            collector = DockerCollector()

            assert collector.client is None
            is_available = await collector.is_available()
            assert is_available is False

            # Should return empty list when Docker not available
            metrics = await collector.collect()
            assert metrics == []

    @pytest.mark.asyncio
    async def test_is_available_success(self, mock_docker_client):
        """Test checking Docker availability."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            is_available = await collector.is_available()

            assert is_available is True
            mock_docker_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_available_ping_fails(self, mock_docker_client):
        """Test availability check when ping fails."""
        mock_docker_client.ping.side_effect = Exception("Connection refused")

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            is_available = await collector.is_available()

            assert is_available is False

    @pytest.mark.asyncio
    async def test_collect_single_container(self, mock_docker_client, mock_container):
        """Test collecting metrics for a single container."""
        mock_docker_client.containers.list.return_value = [mock_container]

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            metrics = await collector.collect()

            assert len(metrics) == 1
            metric = metrics[0]

            # Verify container info
            assert metric.container_id == "abc123def456"
            assert metric.container_name == "ciris-agent-datum"
            assert metric.image == "ghcr.io/cirisai/ciris-agent:latest"
            assert metric.status == ContainerStatus.RUNNING
            assert metric.health == HealthStatus.HEALTHY
            assert metric.restart_count == 0

            # Verify resources
            assert metric.resources.cpu_percent == 4.0  # (100M / 500M) * 2 cores * 100
            assert metric.resources.memory_mb == 256
            assert metric.resources.memory_limit_mb == 512
            assert metric.resources.memory_percent == 50.0
            assert metric.resources.disk_read_mb == 10
            assert metric.resources.disk_write_mb == 20
            assert metric.resources.network_rx_mb == 5
            assert metric.resources.network_tx_mb == 10

    @pytest.mark.asyncio
    async def test_collect_multiple_containers(self, mock_docker_client):
        """Test collecting metrics for multiple containers."""
        # Create multiple mock containers
        containers = []
        for i in range(3):
            container = Mock()
            container.short_id = f"container{i}"
            container.name = f"ciris-agent-{i}"
            container.status = "running"
            container.attrs = {
                "Created": "2025-01-01T12:00:00Z",
                "State": {
                    "Status": "running",
                    "StartedAt": "2025-01-01T12:00:00Z",
                    "Health": {"Status": "healthy"},
                },
                "Config": {"Image": f"test:v{i}"},
                "Image": f"sha256:image{i}",
                "RestartCount": i,
            }
            container.stats = Mock(
                return_value={
                    "cpu_stats": {
                        "cpu_usage": {"total_usage": 1000000000, "percpu_usage": [500000000]},
                        "system_cpu_usage": 10000000000,
                    },
                    "precpu_stats": {
                        "cpu_usage": {"total_usage": 900000000},
                        "system_cpu_usage": 9500000000,
                    },
                    "memory_stats": {"usage": 268435456, "limit": 536870912},
                    "blkio_stats": {"io_service_bytes_recursive": []},
                    "networks": {},
                }
            )
            container.reload = Mock()
            containers.append(container)

        mock_docker_client.containers.list.return_value = containers

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            metrics = await collector.collect()

            assert len(metrics) == 3
            for i, metric in enumerate(metrics):
                assert metric.container_name == f"ciris-agent-{i}"
                assert metric.restart_count == i

    @pytest.mark.asyncio
    async def test_collect_stopped_container(self, mock_docker_client):
        """Test collecting metrics for stopped container."""
        container = Mock()
        container.short_id = "stopped123"
        container.name = "ciris-agent-stopped"
        container.status = "exited"
        container.attrs = {
            "Created": "2025-01-01T12:00:00Z",
            "State": {
                "Status": "exited",
                "StartedAt": "2025-01-01T12:00:00Z",
                "FinishedAt": "2025-01-01T13:00:00Z",
                "ExitCode": 1,
                "Error": "Out of memory",
            },
            "Config": {"Image": "test:latest"},
            "Image": "sha256:test",
            "RestartCount": 5,
        }
        container.reload = Mock()

        mock_docker_client.containers.list.return_value = [container]

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            metrics = await collector.collect()

            assert len(metrics) == 1
            metric = metrics[0]

            assert metric.status == ContainerStatus.EXITED
            assert metric.exit_code == 1
            assert metric.error_message == "Out of memory"
            assert metric.restart_count == 5

            # Stopped container should have zero resources
            assert metric.resources.cpu_percent == 0.0
            assert metric.resources.memory_mb == 0

    @pytest.mark.asyncio
    async def test_parse_container_status(self, mock_docker_client):
        """Test parsing various container statuses."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            assert collector._parse_status("running") == ContainerStatus.RUNNING
            assert collector._parse_status("exited") == ContainerStatus.EXITED
            assert collector._parse_status("paused") == ContainerStatus.PAUSED
            assert collector._parse_status("restarting") == ContainerStatus.RESTARTING
            assert collector._parse_status("dead") == ContainerStatus.DEAD
            assert collector._parse_status("created") == ContainerStatus.CREATED
            assert collector._parse_status("removing") == ContainerStatus.REMOVING
            assert collector._parse_status("weird_status") == ContainerStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_parse_health_status(self, mock_docker_client):
        """Test parsing health check status."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            # Healthy
            attrs = {"State": {"Health": {"Status": "healthy"}}}
            assert collector._parse_health(attrs) == HealthStatus.HEALTHY

            # Unhealthy
            attrs = {"State": {"Health": {"Status": "unhealthy"}}}
            assert collector._parse_health(attrs) == HealthStatus.UNHEALTHY

            # Starting
            attrs = {"State": {"Health": {"Status": "starting"}}}
            assert collector._parse_health(attrs) == HealthStatus.STARTING

            # No health check
            attrs = {"State": {}}
            assert collector._parse_health(attrs) == HealthStatus.NONE

            # Unknown status
            attrs = {"State": {"Health": {"Status": "weird"}}}
            assert collector._parse_health(attrs) == HealthStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_parse_timestamp(self, mock_docker_client):
        """Test timestamp parsing."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            # Valid timestamp
            ts = collector._parse_timestamp("2025-01-01T12:00:00Z")
            assert ts is not None
            assert ts.year == 2025
            assert ts.month == 1
            assert ts.day == 1
            assert ts.hour == 12

            # Timestamp with nanoseconds
            ts = collector._parse_timestamp("2025-01-01T12:00:00.123456789Z")
            assert ts is not None
            assert ts.year == 2025

            # Null timestamp
            assert collector._parse_timestamp("0001-01-01T00:00:00Z") is None
            assert collector._parse_timestamp(None) is None
            assert collector._parse_timestamp("") is None

            # Invalid format
            assert collector._parse_timestamp("not a timestamp") is None

    @pytest.mark.asyncio
    async def test_collect_with_container_error(self, mock_docker_client, mock_container):
        """Test handling errors for specific containers."""
        # Make one container fail
        bad_container = Mock()
        bad_container.short_id = "bad"
        bad_container.name = "ciris-agent-bad"
        bad_container.reload.side_effect = Exception("Container disappeared")

        mock_docker_client.containers.list.return_value = [mock_container, bad_container]

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            metrics = await collector.collect()

            # Should still get metrics for good container
            assert len(metrics) == 1
            assert metrics[0].container_name == "ciris-agent-datum"

    @pytest.mark.asyncio
    async def test_collect_with_stats_error(self, mock_docker_client, mock_container):
        """Test handling stats collection errors."""
        mock_container.stats.side_effect = Exception("Stats unavailable")
        mock_docker_client.containers.list.return_value = [mock_container]

        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            metrics = await collector.collect()

            # Should still get basic metrics with zero resources
            assert len(metrics) == 1
            metric = metrics[0]
            assert metric.container_name == "ciris-agent-datum"
            assert metric.resources.cpu_percent == 0.0
            assert metric.resources.memory_mb == 0

    @pytest.mark.asyncio
    async def test_health_check(self, mock_docker_client):
        """Test health check functionality."""
        with patch("docker.from_env", return_value=mock_docker_client):
            collector = DockerCollector()

            # Collect some metrics first
            mock_docker_client.containers.list.return_value = []
            await collector.collect()

            result = await collector.health_check()

            assert result["healthy"] is True
            assert result["available"] is True
            assert "stats" in result
            assert result["error"] is None

    @pytest.mark.asyncio
    async def test_reconnect_on_failure(self, mock_docker_client):
        """Test reconnection attempt when Docker connection lost."""
        # First connection succeeds
        with patch("docker.from_env", return_value=mock_docker_client) as mock_from_env:
            collector = DockerCollector()
            assert collector.client is not None

            # Simulate connection loss
            collector.client = None

            # is_available should try to reconnect
            await collector.is_available()

            # Should have attempted reconnection
            assert mock_from_env.call_count == 2
