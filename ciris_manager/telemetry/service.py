"""
Telemetry service that manages continuous collection and storage.

This service runs as part of CIRISManager and continuously collects
telemetry data from all sources.
"""

import asyncio
import logging
import signal
from typing import Optional
from pathlib import Path

from ciris_manager.telemetry.orchestrator import (
    TelemetryOrchestrator,
    ContinuousTelemetryCollector,
)
from ciris_manager.telemetry.storage import TelemetryStorageBackend
from ciris_manager.telemetry.schemas import SystemSummary, PublicStatus

logger = logging.getLogger(__name__)


class TelemetryService:
    """
    Main telemetry service that manages continuous collection.

    This service:
    - Initializes all collectors
    - Manages the continuous collection loop
    - Stores data in PostgreSQL/TimescaleDB
    - Provides query interfaces for dashboards
    """

    def __init__(
        self,
        agent_registry,
        database_url: Optional[str] = None,
        state_dir: str = "/opt/ciris/state",
        versions_dir: str = "/opt/ciris/versions",
        collection_interval: int = 60,
        enable_storage: bool = True,
    ):
        """
        Initialize telemetry service.

        Args:
            agent_registry: Registry containing agent metadata
            database_url: PostgreSQL connection string (if storage enabled)
            state_dir: Directory for deployment state files
            versions_dir: Directory for version tracking files
            collection_interval: Seconds between collections
            enable_storage: Whether to enable database storage
        """
        self.agent_registry = agent_registry
        self.database_url = database_url
        self.state_dir = Path(state_dir)
        self.versions_dir = Path(versions_dir)
        self.collection_interval = collection_interval
        self.enable_storage = enable_storage and database_url is not None

        # Components
        self.orchestrator: Optional[TelemetryOrchestrator] = None
        self.storage: Optional[TelemetryStorageBackend] = None
        self.continuous_collector: Optional[ContinuousTelemetryCollector] = None

        # Service state
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize telemetry components."""
        logger.info("Initializing telemetry service")

        # Create orchestrator
        self.orchestrator = TelemetryOrchestrator(
            agent_registry=self.agent_registry,
            state_dir=str(self.state_dir),
            versions_dir=str(self.versions_dir),
        )

        # Initialize storage if enabled
        if self.enable_storage and self.database_url:
            try:
                self.storage = TelemetryStorageBackend(self.database_url)
                await self.storage.connect()
                logger.info("Connected to telemetry database")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                logger.warning("Running without persistent storage")
                self.storage = None
                self.enable_storage = False

        # Create continuous collector
        self.continuous_collector = ContinuousTelemetryCollector(
            orchestrator=self.orchestrator,
            storage_backend=self.storage,
            interval_seconds=self.collection_interval,
        )

        logger.info(
            f"Telemetry service initialized "
            f"(storage={'enabled' if self.enable_storage else 'disabled'}, "
            f"interval={self.collection_interval}s)"
        )

    async def start(self) -> None:
        """Start the telemetry service."""
        if self._running:
            logger.warning("Telemetry service already running")
            return

        logger.info("Starting telemetry service")

        # Initialize if not done
        if not self.orchestrator:
            await self.initialize()

        # Start continuous collection
        if self.continuous_collector:
            await self.continuous_collector.start()

        self._running = True

        # Register signal handlers
        self._register_signal_handlers()

        logger.info("Telemetry service started")

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop the telemetry service."""
        if not self._running:
            return

        logger.info("Stopping telemetry service")

        # Stop continuous collection
        if self.continuous_collector:
            await self.continuous_collector.stop()

        # Disconnect from database
        if self.storage:
            await self.storage.disconnect()

        self._running = False
        self._shutdown_event.set()

        logger.info("Telemetry service stopped")

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    async def collect_once(self) -> Optional[SystemSummary]:
        """
        Perform a single collection and return summary.

        Returns:
            System summary or None on failure
        """
        if not self.orchestrator:
            await self.initialize()

        if not self.orchestrator:
            logger.error("Failed to initialize orchestrator")
            return None

        snapshot = await self.orchestrator.collect_snapshot()
        if not snapshot:
            return None

        summary = self.orchestrator.calculate_summary(snapshot)

        # Store if enabled
        if self.storage:
            try:
                await self.storage.store_snapshot(snapshot)
                await self.storage.store_summary(summary)
            except Exception as e:
                logger.error(f"Failed to store telemetry: {e}")

        return summary

    def get_current_status(self) -> Optional[SystemSummary]:
        """
        Get current system status from last collection.

        Returns:
            Latest system summary or None
        """
        if not self.continuous_collector:
            return None

        return self.continuous_collector.get_last_summary()

    def get_public_status(self) -> Optional[PublicStatus]:
        """
        Get public-safe status for external dashboard.

        Returns:
            Public status or None
        """
        if not self.continuous_collector:
            return None

        public_dict = self.continuous_collector.get_public_status()
        if not public_dict:
            return None

        # Convert to typed model
        return PublicStatus(
            total_agents=public_dict["total_agents"],
            healthy_percentage=public_dict["healthy_percentage"],
            messages_24h=public_dict["messages_24h"],
            incidents_24h=public_dict["incidents_24h"],
            uptime_percentage=95.0,  # Calculate from actual data
        )

    async def get_public_history(self, hours: int = 24):
        """
        Get public-safe historical data.

        Args:
            hours: Number of hours to retrieve

        Returns:
            List of public history entries
        """
        if not self.storage:
            return []

        try:
            return await self.storage.get_public_history(hours=hours)
        except Exception as e:
            logger.error(f"Failed to get public history: {e}")
            return []

    async def cleanup_old_data(self, days: int = 7) -> None:
        """
        Clean up old telemetry data.

        Args:
            days: Number of days to retain
        """
        if not self.storage:
            return

        try:
            await self.storage.cleanup_old_data(days_to_keep=days)
            logger.info(f"Cleaned up telemetry data older than {days} days")
        except Exception as e:
            logger.error(f"Failed to clean up old data: {e}")

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running

    @property
    def has_storage(self) -> bool:
        """Check if persistent storage is enabled."""
        return self.enable_storage and self.storage is not None


async def run_telemetry_service(
    agent_registry, database_url: Optional[str] = None, **kwargs
) -> None:
    """
    Run the telemetry service.

    This is the main entry point for running telemetry as a service.

    Args:
        agent_registry: Agent registry instance
        database_url: PostgreSQL connection string
        **kwargs: Additional configuration options
    """
    service = TelemetryService(agent_registry=agent_registry, database_url=database_url, **kwargs)

    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Telemetry service error: {e}")
    finally:
        await service.stop()
