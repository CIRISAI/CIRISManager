"""
Base classes and protocols for telemetry collectors.

This module defines the abstract base classes that all collectors must inherit from,
ensuring consistent interfaces and extensibility for future telemetry types.
"""

from abc import ABC, abstractmethod
from typing import List, Any, Optional, Generic, TypeVar
from datetime import datetime
import asyncio
import logging

from ciris_manager.telemetry.schemas import (
    TelemetrySnapshot,
)

logger = logging.getLogger(__name__)

# Type variable for metrics - allows type-safe generic collectors
T = TypeVar("T")


class BaseCollector(ABC, Generic[T]):
    """
    Abstract base class for all telemetry collectors.

    All collectors must inherit from this class and implement the required methods.
    This ensures consistent error handling, timeout behavior, and extensibility.
    """

    def __init__(self, name: str, timeout_seconds: int = 30):
        """
        Initialize base collector.

        Args:
            name: Collector name for logging and identification
            timeout_seconds: Maximum time allowed for collection
        """
        self.name = name
        self.timeout_seconds = timeout_seconds
        self._last_collection_time: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._collection_count = 0
        self._error_count = 0

    @abstractmethod
    async def collect(self) -> List[T]:
        """
        Collect metrics from the source.

        Must be implemented by subclasses.

        Returns:
            List of collected metrics of type T

        Promises:
        - Returns empty list on error (never raises)
        - Completes within timeout_seconds
        - Logs all errors
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if the data source is available.

        Must be implemented by subclasses.

        Returns:
            True if source is available, False otherwise

        Promises:
        - Never raises exceptions
        - Completes within 2 seconds
        - Returns False on any error
        """
        pass

    async def collect_with_timeout(self) -> List[T]:
        """
        Collect metrics with timeout enforcement.

        Wraps the collect() method with timeout and error handling.

        Returns:
            List of collected metrics or empty list on timeout/error
        """
        try:
            self._collection_count += 1
            start_time = datetime.utcnow()

            # Apply timeout
            result = await asyncio.wait_for(self.collect(), timeout=self.timeout_seconds)

            self._last_collection_time = datetime.utcnow()
            logger.debug(
                f"{self.name} collected {len(result)} items in "
                f"{(datetime.utcnow() - start_time).total_seconds():.2f}s"
            )
            return result

        except asyncio.TimeoutError:
            self._error_count += 1
            self._last_error = f"Collection timeout after {self.timeout_seconds}s"
            logger.error(f"{self.name}: {self._last_error}")
            return []

        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            logger.error(f"{self.name} collection failed: {e}")
            return []

    def get_stats(self) -> dict:
        """
        Get collector statistics.

        Returns:
            Dictionary with collection stats
        """
        return {
            "name": self.name,
            "collections": self._collection_count,
            "errors": self._error_count,
            "error_rate": self._error_count / max(1, self._collection_count),
            "last_collection": self._last_collection_time.isoformat()
            if self._last_collection_time
            else None,
            "last_error": self._last_error,
        }

    def reset_stats(self) -> None:
        """Reset collector statistics."""
        self._collection_count = 0
        self._error_count = 0
        self._last_error = None


class CompositeCollector(BaseCollector[TelemetrySnapshot]):
    """
    Base class for collectors that aggregate data from multiple sources.

    This is used for the main telemetry collector that combines all metrics.
    """

    def __init__(self, name: str = "CompositeCollector"):
        """Initialize composite collector."""
        super().__init__(name, timeout_seconds=60)
        self.collectors: dict[str, BaseCollector] = {}

    def register_collector(self, key: str, collector: BaseCollector) -> None:
        """
        Register a sub-collector.

        Args:
            key: Unique key for this collector
            collector: Collector instance to register
        """
        if key in self.collectors:
            raise ValueError(f"Collector {key} already registered")
        self.collectors[key] = collector
        logger.info(f"Registered collector: {key}")

    def unregister_collector(self, key: str) -> None:
        """
        Unregister a sub-collector.

        Args:
            key: Key of collector to remove
        """
        if key in self.collectors:
            del self.collectors[key]
            logger.info(f"Unregistered collector: {key}")

    async def collect_all_parallel(self) -> dict[str, List[Any]]:
        """
        Collect from all registered collectors in parallel.

        Returns:
            Dictionary mapping collector keys to their results
        """
        if not self.collectors:
            logger.warning("No collectors registered")
            return {}

        # Create collection tasks
        tasks = {}
        for key, collector in self.collectors.items():
            tasks[key] = collector.collect_with_timeout()

        # Wait for all to complete
        results = {}
        for key, task in tasks.items():
            try:
                results[key] = await task
            except Exception as e:
                logger.error(f"Collector {key} failed: {e}")
                results[key] = []

        return results

    def get_all_stats(self) -> dict:
        """
        Get statistics for all collectors.

        Returns:
            Dictionary with stats for each collector
        """
        stats = {"composite": super().get_stats(), "collectors": {}}

        for key, collector in self.collectors.items():
            stats["collectors"][key] = collector.get_stats()

        return stats


class PeriodicCollector(ABC):
    """
    Base class for collectors that run periodically.

    Handles the scheduling and lifecycle of continuous collection.
    """

    def __init__(
        self,
        collector: BaseCollector,
        interval_seconds: int = 60,
        storage_backend: Optional[Any] = None,
    ):
        """
        Initialize periodic collector.

        Args:
            collector: The collector to run periodically
            interval_seconds: Collection interval
            storage_backend: Optional storage for collected data
        """
        self.collector = collector
        self.interval_seconds = interval_seconds
        self.storage_backend = storage_backend
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_snapshot: Optional[Any] = None

    async def start(self) -> None:
        """Start the periodic collection loop."""
        if self._running:
            logger.warning("Collector already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info(
            f"Started periodic collection for {self.collector.name} every {self.interval_seconds}s"
        )

    async def stop(self) -> None:
        """Stop the periodic collection loop."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(f"Stopped periodic collection for {self.collector.name}")

    async def _collection_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                # Collect data
                data = await self.collector.collect_with_timeout()
                self._last_snapshot = data

                # Store if backend available
                if self.storage_backend and data:
                    await self._store_data(data)

            except Exception as e:
                logger.error(f"Collection loop error: {e}")

            # Wait for next interval
            await asyncio.sleep(self.interval_seconds)

    @abstractmethod
    async def _store_data(self, data: Any) -> None:
        """
        Store collected data.

        Must be implemented by subclasses to define storage strategy.

        Args:
            data: Collected data to store
        """
        pass

    def get_last_snapshot(self) -> Optional[Any]:
        """Get the most recent collected data."""
        return self._last_snapshot

    @property
    def is_running(self) -> bool:
        """Check if collector is running."""
        return self._running


class HealthCheckMixin:
    """
    Mixin to add health check capabilities to collectors.

    Provides standard health check implementation.
    """

    async def health_check(self) -> dict:
        """
        Perform health check.

        Returns:
            Dictionary with health status
        """
        is_available = False
        error_message = None

        try:
            # Check if source is available
            if hasattr(self, "is_available"):
                is_available = await self.is_available()

            # Get stats if available
            stats = {}
            if hasattr(self, "get_stats"):
                stats = self.get_stats()

            return {
                "healthy": is_available and stats.get("error_rate", 1.0) < 0.5,
                "available": is_available,
                "stats": stats,
                "error": error_message,
            }

        except Exception as e:
            return {
                "healthy": False,
                "available": False,
                "error": str(e),
            }


class RetryableMixin:
    """
    Mixin to add retry capabilities to collectors.

    Provides exponential backoff retry logic.
    """

    def __init__(self, *args, max_retries: int = 3, **kwargs):
        """
        Initialize retryable mixin.

        Args:
            max_retries: Maximum number of retry attempts
        """
        super().__init__(*args, **kwargs)
        self.max_retries = max_retries

    async def collect_with_retry(self) -> List[Any]:
        """
        Collect with retry on failure.

        Returns:
            Collected data or empty list after all retries
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Call parent's collect method
                if hasattr(super(), "collect"):
                    result = await super().collect()
                    if result:
                        return result

            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    wait_time = 2**attempt
                    logger.warning(
                        f"Collection attempt {attempt + 1} failed, retrying in {wait_time}s: {e}"
                    )
                    await asyncio.sleep(wait_time)

        logger.error(f"All {self.max_retries} collection attempts failed: {last_error}")
        return []
