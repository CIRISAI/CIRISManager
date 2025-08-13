"""
Unit tests for telemetry base classes.

Tests the abstract base classes, mixins, and composite collectors.
"""

import pytest
import asyncio
from datetime import datetime
from typing import List

from ciris_manager.telemetry.base import (
    BaseCollector,
    CompositeCollector,
    PeriodicCollector,
    HealthCheckMixin,
    RetryableMixin,
)


class MockMetric:
    """Mock metric for testing."""

    def __init__(self, value: str):
        self.value = value


class TestCollector(BaseCollector[MockMetric]):
    """Concrete test implementation of BaseCollector."""

    def __init__(self, name: str = "TestCollector"):
        super().__init__(name, timeout_seconds=1)
        self.available = True
        self.metrics = [MockMetric("test1"), MockMetric("test2")]
        self.collect_called = 0

    async def collect(self) -> List[MockMetric]:
        """Collect test metrics."""
        self.collect_called += 1
        if not self.available:
            raise Exception("Test error")
        return self.metrics

    async def is_available(self) -> bool:
        """Check availability."""
        return self.available


class TestBaseCollector:
    """Test BaseCollector functionality."""

    @pytest.mark.asyncio
    async def test_successful_collection(self):
        """Test successful metric collection."""
        collector = TestCollector()

        result = await collector.collect_with_timeout()

        assert len(result) == 2
        assert result[0].value == "test1"
        assert result[1].value == "test2"
        assert collector._collection_count == 1
        assert collector._error_count == 0

    @pytest.mark.asyncio
    async def test_collection_error_handling(self):
        """Test error handling during collection."""
        collector = TestCollector()
        collector.available = False

        result = await collector.collect_with_timeout()

        assert result == []
        assert collector._collection_count == 1
        assert collector._error_count == 1
        assert collector._last_error == "Test error"

    @pytest.mark.asyncio
    async def test_collection_timeout(self):
        """Test timeout handling."""
        collector = TestCollector()

        # Make collect take too long
        async def slow_collect():
            await asyncio.sleep(2)
            return []

        collector.collect = slow_collect

        result = await collector.collect_with_timeout()

        assert result == []
        assert collector._error_count == 1
        assert "timeout" in collector._last_error.lower()

    def test_get_stats(self):
        """Test statistics retrieval."""
        collector = TestCollector()
        collector._collection_count = 10
        collector._error_count = 2
        collector._last_collection_time = datetime(2025, 1, 1, 12, 0, 0)
        collector._last_error = "Test error"

        stats = collector.get_stats()

        assert stats["name"] == "TestCollector"
        assert stats["collections"] == 10
        assert stats["errors"] == 2
        assert stats["error_rate"] == 0.2
        assert "2025-01-01" in stats["last_collection"]
        assert stats["last_error"] == "Test error"

    def test_reset_stats(self):
        """Test statistics reset."""
        collector = TestCollector()
        collector._collection_count = 5
        collector._error_count = 1
        collector._last_error = "Error"

        collector.reset_stats()

        assert collector._collection_count == 0
        assert collector._error_count == 0
        assert collector._last_error is None


class TestCompositeCollector:
    """Test CompositeCollector functionality."""

    def test_register_collector(self):
        """Test registering sub-collectors."""

        # Create a concrete implementation for testing
        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()
        collector1 = TestCollector("collector1")
        collector2 = TestCollector("collector2")

        composite.register_collector("test1", collector1)
        composite.register_collector("test2", collector2)

        assert len(composite.collectors) == 2
        assert composite.collectors["test1"] == collector1
        assert composite.collectors["test2"] == collector2

    def test_register_duplicate_fails(self):
        """Test that registering duplicate key fails."""

        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()
        collector = TestCollector()

        composite.register_collector("test", collector)

        with pytest.raises(ValueError, match="already registered"):
            composite.register_collector("test", collector)

    def test_unregister_collector(self):
        """Test unregistering collectors."""

        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()
        collector = TestCollector()

        composite.register_collector("test", collector)
        assert "test" in composite.collectors

        composite.unregister_collector("test")
        assert "test" not in composite.collectors

    @pytest.mark.asyncio
    async def test_collect_all_parallel(self):
        """Test parallel collection from all sub-collectors."""

        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()
        collector1 = TestCollector("collector1")
        collector2 = TestCollector("collector2")
        collector3 = TestCollector("collector3")
        collector3.available = False  # This one will fail

        composite.register_collector("test1", collector1)
        composite.register_collector("test2", collector2)
        composite.register_collector("test3", collector3)

        results = await composite.collect_all_parallel()

        assert len(results) == 3
        assert len(results["test1"]) == 2
        assert len(results["test2"]) == 2
        assert results["test3"] == []  # Failed collector returns empty

    @pytest.mark.asyncio
    async def test_collect_all_empty(self):
        """Test collection with no registered collectors."""

        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()

        results = await composite.collect_all_parallel()

        assert results == {}

    def test_get_all_stats(self):
        """Test getting stats for all collectors."""

        class TestComposite(CompositeCollector):
            async def collect(self):
                return []

            async def is_available(self):
                return True

        composite = TestComposite()
        collector1 = TestCollector("collector1")
        collector2 = TestCollector("collector2")

        collector1._collection_count = 5
        collector1._error_count = 1
        collector2._collection_count = 10
        collector2._error_count = 0

        composite.register_collector("test1", collector1)
        composite.register_collector("test2", collector2)

        stats = composite.get_all_stats()

        assert "composite" in stats
        assert "collectors" in stats
        assert "test1" in stats["collectors"]
        assert "test2" in stats["collectors"]
        assert stats["collectors"]["test1"]["collections"] == 5
        assert stats["collectors"]["test2"]["errors"] == 0


class TestPeriodicCollector:
    """Test PeriodicCollector functionality."""

    class TestPeriodicImpl(PeriodicCollector):
        """Concrete implementation for testing."""

        def __init__(self, collector, interval_seconds=1):
            super().__init__(collector, interval_seconds)
            self.stored_data = []

        async def _store_data(self, data):
            """Store collected data."""
            self.stored_data.append(data)

    @pytest.mark.asyncio
    @pytest.mark.flaky
    @pytest.mark.skip(reason="Flaky test - timing dependent")
    async def test_start_stop(self):
        """Test starting and stopping periodic collection."""
        collector = TestCollector()
        periodic = self.TestPeriodicImpl(collector, interval_seconds=0.1)

        assert not periodic.is_running

        await periodic.start()
        assert periodic.is_running

        # Let it run for a bit
        await asyncio.sleep(0.25)

        await periodic.stop()
        assert not periodic.is_running

        # Should have collected at least twice
        assert len(periodic.stored_data) >= 2

    @pytest.mark.asyncio
    async def test_already_running(self):
        """Test that starting twice doesn't create multiple loops."""
        collector = TestCollector()
        periodic = self.TestPeriodicImpl(collector)

        await periodic.start()
        task1 = periodic._task

        # Try to start again
        await periodic.start()
        task2 = periodic._task

        assert task1 == task2  # Same task

        await periodic.stop()

    @pytest.mark.asyncio
    async def test_get_last_snapshot(self):
        """Test retrieving last collected snapshot."""
        collector = TestCollector()
        periodic = self.TestPeriodicImpl(collector, interval_seconds=0.1)

        assert periodic.get_last_snapshot() is None

        await periodic.start()
        await asyncio.sleep(0.15)
        await periodic.stop()

        last = periodic.get_last_snapshot()
        assert last is not None
        assert len(last) == 2


class TestHealthCheckMixin:
    """Test HealthCheckMixin functionality."""

    class HealthyCollector(TestCollector, HealthCheckMixin):
        """Collector with health check capability."""

        pass

    @pytest.mark.asyncio
    async def test_healthy_check(self):
        """Test health check for healthy collector."""
        collector = self.HealthyCollector()
        collector._collection_count = 10
        collector._error_count = 1

        result = await collector.health_check()

        assert result["healthy"] is True
        assert result["available"] is True
        assert result["stats"]["error_rate"] == 0.1
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_unhealthy_check(self):
        """Test health check for unhealthy collector."""
        collector = self.HealthyCollector()
        collector.available = False
        collector._collection_count = 10
        collector._error_count = 6  # > 50% error rate

        result = await collector.health_check()

        assert result["healthy"] is False
        assert result["available"] is False
        assert result["stats"]["error_rate"] == 0.6

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """Test health check handles exceptions."""
        collector = self.HealthyCollector()

        # Make is_available raise
        async def failing_check():
            raise Exception("Check failed")

        collector.is_available = failing_check

        result = await collector.health_check()

        assert result["healthy"] is False
        assert result["available"] is False
        assert "Check failed" in result["error"]


class TestRetryableMixin:
    """Test RetryableMixin functionality."""

    class RetryableCollector(RetryableMixin, TestCollector):
        """Collector with retry capability."""

        def __init__(self):
            super().__init__(max_retries=3)
            self.attempt_count = 0

        async def collect(self):
            """Collect with counting."""
            self.attempt_count += 1
            if self.attempt_count < 3:
                raise Exception(f"Attempt {self.attempt_count} failed")
            return await super().collect()

    @pytest.mark.asyncio
    async def test_retry_success(self):
        """Test successful retry after failures."""
        collector = self.RetryableCollector()

        result = await collector.collect_with_retry()

        assert len(result) == 2
        assert collector.attempt_count == 3  # Failed twice, succeeded on third

    @pytest.mark.asyncio
    async def test_retry_all_fail(self):
        """Test all retries failing."""
        collector = self.RetryableCollector()

        # Make it always fail
        async def always_fail():
            raise Exception("Always fails")

        collector.collect = always_fail

        result = await collector.collect_with_retry()

        assert result == []

    @pytest.mark.asyncio
    async def test_retry_with_backoff(self):
        """Test exponential backoff between retries."""
        collector = self.RetryableCollector()

        start_time = asyncio.get_event_loop().time()
        result = await collector.collect_with_retry()
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should have waited 1 + 2 = 3 seconds minimum for backoff
        assert elapsed >= 3.0
        assert len(result) == 2
