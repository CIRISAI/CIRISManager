"""
Simple unit tests for CrashLoopWatchdog.
"""

import asyncio

import pytest

from ciris_manager.core.watchdog import CrashLoopWatchdog, ContainerTracker, CrashEvent
from datetime import datetime, timedelta


class TestWatchdogSimple:
    """Simple test cases for watchdog."""

    def test_watchdog_initialization(self):
        """Test watchdog initialization."""
        watchdog = CrashLoopWatchdog(check_interval=30, crash_threshold=3, crash_window=300)

        assert watchdog.check_interval == 30
        assert watchdog.crash_threshold == 3
        assert watchdog.crash_window == timedelta(seconds=300)
        assert not watchdog._running

    def test_get_status(self):
        """Test get_status method."""
        watchdog = CrashLoopWatchdog()
        status = watchdog.get_status()

        assert "running" in status
        assert "check_interval" in status
        assert "crash_threshold" in status
        assert "containers" in status

    def test_container_tracker(self):
        """Test ContainerTracker."""
        tracker = ContainerTracker(container="test")
        assert tracker.container == "test"
        assert len(tracker.crashes) == 0
        assert not tracker.stopped

    def test_crash_event(self):
        """Test CrashEvent."""
        event = CrashEvent(container="test", timestamp=datetime.utcnow(), exit_code=1)
        assert event.container == "test"
        assert event.exit_code == 1
        assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_stop_swallows_cancelled_error(self):
        """stop() must not re-raise CancelledError from the cancelled task.

        The watchdog loop awaits asyncio.sleep(); cancelling it via stop() raises
        CancelledError inside the loop. If stop() propagates that error, it
        unwinds through manager.stop() -> run()'s finally -> asyncio.run(), and
        systemd sees a non-zero exit code for what was a clean shutdown.
        """
        watchdog = CrashLoopWatchdog(check_interval=3600)
        await watchdog.start()
        assert watchdog._running is True
        assert watchdog._task is not None

        # Let the loop enter asyncio.sleep() so cancellation hits the sleep.
        await asyncio.sleep(0)

        # Must return cleanly, not raise CancelledError.
        await watchdog.stop()

        assert watchdog._running is False
        assert watchdog._task.done()
        assert watchdog._task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent_when_not_started(self):
        """stop() on a never-started watchdog should be a no-op."""
        watchdog = CrashLoopWatchdog()
        await watchdog.stop()  # Must not raise.
