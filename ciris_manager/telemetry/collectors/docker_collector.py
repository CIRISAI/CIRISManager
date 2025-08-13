"""
Docker container metrics collector implementation.

Collects metrics from Docker API for all CIRIS containers.
"""

import asyncio
import logging
from typing import List, Optional
from datetime import datetime
import docker
from docker.models.containers import Container

from ciris_manager.telemetry.schemas import (
    ContainerMetrics,
    ContainerResources,
    ContainerStatus,
    HealthStatus,
)
from ciris_manager.telemetry.base import BaseCollector, HealthCheckMixin

logger = logging.getLogger(__name__)


class DockerCollector(BaseCollector[ContainerMetrics], HealthCheckMixin):
    """Collects metrics from Docker containers."""

    def __init__(self):
        """Initialize Docker collector."""
        super().__init__(name="DockerCollector", timeout_seconds=30)
        self.client: Optional[docker.DockerClient] = None
        self._connect()

    def _connect(self) -> None:
        """Connect to Docker daemon."""
        try:
            self.client = docker.from_env()
            logger.debug("Connected to Docker daemon")
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            self.client = None

    async def is_available(self) -> bool:
        """Check if Docker API is available."""
        if not self.client:
            self._connect()

        if not self.client:
            return False

        try:
            # Run sync ping in executor to not block
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.ping)
            return True
        except Exception as e:
            logger.debug(f"Docker not available: {e}")
            return False

    async def collect(self) -> List[ContainerMetrics]:
        """
        Collect metrics for all CIRIS containers.

        Returns empty list on any error to fulfill protocol promise.
        """
        if not await self.is_available():
            logger.warning("Docker not available, returning empty metrics")
            return []

        try:
            loop = asyncio.get_event_loop()

            # Get all containers with 'ciris' in name
            containers = await loop.run_in_executor(
                None, lambda: self.client.containers.list(all=True, filters={"name": "ciris"})
            )

            metrics = []
            for container in containers:
                try:
                    metric = await self._collect_single_container(container)
                    if metric:
                        metrics.append(metric)
                except Exception as e:
                    logger.warning(f"Failed to collect metrics for {container.name}: {e}")
                    continue

            logger.info(f"Collected metrics for {len(metrics)} containers")
            return metrics

        except Exception as e:
            logger.error(f"Failed to collect container metrics: {e}")
            return []

    async def _collect_single_container(self, container: Container) -> Optional[ContainerMetrics]:
        """Collect metrics for a single container."""
        try:
            loop = asyncio.get_event_loop()

            # Get container details
            await loop.run_in_executor(None, container.reload)
            attrs = container.attrs

            # Parse status
            status = self._parse_status(container.status)
            health = self._parse_health(attrs)

            # Get resource stats if running
            resources = (
                await self._get_resources(container)
                if status == ContainerStatus.RUNNING
                else ContainerResources(
                    cpu_percent=0.0,
                    memory_mb=0,
                    memory_limit_mb=None,
                    memory_percent=0.0,
                    disk_read_mb=0,
                    disk_write_mb=0,
                    network_rx_mb=0,
                    network_tx_mb=0,
                )
            )

            # Parse timestamps
            created_at = self._parse_timestamp(attrs.get("Created"))
            state = attrs.get("State", {})
            started_at = self._parse_timestamp(state.get("StartedAt"))
            finished_at = self._parse_timestamp(state.get("FinishedAt"))

            # Get image info
            image = attrs.get("Config", {}).get("Image", "unknown")
            image_digest = attrs.get("Image", "")[:12]  # Short digest

            # Get restart count
            restart_count = attrs.get("RestartCount", 0)

            # Get exit code if stopped
            exit_code = (
                state.get("ExitCode")
                if status in [ContainerStatus.EXITED, ContainerStatus.DEAD]
                else None
            )
            error_message = state.get("Error") if exit_code and exit_code != 0 else None

            return ContainerMetrics(
                container_id=container.short_id,
                container_name=container.name,
                image=image,
                image_digest=image_digest,
                status=status,
                health=health,
                restart_count=restart_count,
                resources=resources,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
                exit_code=exit_code,
                error_message=error_message,
            )

        except Exception as e:
            logger.error(f"Failed to collect metrics for container: {e}")
            return None

    def _parse_status(self, status: str) -> ContainerStatus:
        """Parse Docker status to enum."""
        status_lower = status.lower()

        if status_lower == "running":
            return ContainerStatus.RUNNING
        elif status_lower == "exited":
            return ContainerStatus.EXITED
        elif status_lower == "paused":
            return ContainerStatus.PAUSED
        elif status_lower == "restarting":
            return ContainerStatus.RESTARTING
        elif status_lower == "dead":
            return ContainerStatus.DEAD
        elif status_lower == "created":
            return ContainerStatus.CREATED
        elif status_lower == "removing":
            return ContainerStatus.REMOVING
        else:
            return ContainerStatus.UNKNOWN

    def _parse_health(self, attrs: dict) -> HealthStatus:
        """Parse health check status."""
        state = attrs.get("State", {})
        health = state.get("Health", {})

        if not health:
            return HealthStatus.NONE

        status = health.get("Status", "").lower()

        if status == "healthy":
            return HealthStatus.HEALTHY
        elif status == "unhealthy":
            return HealthStatus.UNHEALTHY
        elif status == "starting":
            return HealthStatus.STARTING
        else:
            return HealthStatus.UNKNOWN

    async def _get_resources(self, container: Container) -> ContainerResources:
        """Get resource usage stats for running container."""
        try:
            loop = asyncio.get_event_loop()

            # Get stats (this is a blocking call)
            stats = await loop.run_in_executor(None, lambda: container.stats(stream=False))

            # Parse CPU usage
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_count = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
            cpu_percent = (
                (cpu_delta / system_delta) * cpu_count * 100.0 if system_delta > 0 else 0.0
            )

            # Parse memory usage
            memory_stats = stats.get("memory_stats", {})
            memory_usage = memory_stats.get("usage", 0)
            memory_limit = memory_stats.get("limit", 0)
            memory_mb = memory_usage // (1024 * 1024)
            memory_limit_mb = memory_limit // (1024 * 1024) if memory_limit > 0 else None
            memory_percent = (memory_usage / memory_limit * 100.0) if memory_limit > 0 else 0.0

            # Parse disk I/O
            blkio_stats = stats.get("blkio_stats", {})
            io_service_bytes = blkio_stats.get("io_service_bytes_recursive", [])

            disk_read_mb = 0
            disk_write_mb = 0
            for entry in io_service_bytes:
                if entry.get("op") == "Read":
                    disk_read_mb += entry.get("value", 0) // (1024 * 1024)
                elif entry.get("op") == "Write":
                    disk_write_mb += entry.get("value", 0) // (1024 * 1024)

            # Parse network I/O
            networks = stats.get("networks", {})
            network_rx_mb = sum(net.get("rx_bytes", 0) for net in networks.values()) // (
                1024 * 1024
            )
            network_tx_mb = sum(net.get("tx_bytes", 0) for net in networks.values()) // (
                1024 * 1024
            )

            return ContainerResources(
                cpu_percent=round(cpu_percent, 2),
                memory_mb=memory_mb,
                memory_limit_mb=memory_limit_mb,
                memory_percent=round(memory_percent, 2),
                disk_read_mb=disk_read_mb,
                disk_write_mb=disk_write_mb,
                network_rx_mb=network_rx_mb,
                network_tx_mb=network_tx_mb,
            )

        except Exception as e:
            logger.warning(f"Failed to get resource stats: {e}")
            # Return zeros rather than fail
            return ContainerResources(
                cpu_percent=0.0,
                memory_mb=0,
                memory_limit_mb=None,
                memory_percent=0.0,
                disk_read_mb=0,
                disk_write_mb=0,
                network_rx_mb=0,
                network_tx_mb=0,
            )

    def _parse_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """Parse Docker timestamp to datetime."""
        if not timestamp_str or timestamp_str == "0001-01-01T00:00:00Z":
            return None

        try:
            # Docker uses RFC3339 format
            # Remove nanoseconds if present
            if "." in timestamp_str:
                timestamp_str = timestamp_str.split(".")[0] + "Z"

            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except Exception as e:
            logger.debug(f"Failed to parse timestamp {timestamp_str}: {e}")
            return None
