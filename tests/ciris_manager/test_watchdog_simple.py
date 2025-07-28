"""
Simple unit tests for CrashLoopWatchdog.
"""

import pytest
from unittest.mock import Mock
from ciris_manager.core.watchdog import CrashLoopWatchdog, ContainerTracker, CrashEvent
from pathlib import Path
from datetime import datetime, timedelta


class TestWatchdogSimple:
    """Simple test cases for watchdog."""
    
    def test_watchdog_initialization(self):
        """Test watchdog initialization."""
        watchdog = CrashLoopWatchdog(
            check_interval=30,
            crash_threshold=3,
            crash_window=300
        )
        
        assert watchdog.check_interval == 30
        assert watchdog.crash_threshold == 3
        assert watchdog.crash_window == timedelta(seconds=300)
        assert not watchdog._running
    
    def test_get_status(self):
        """Test get_status method."""
        watchdog = CrashLoopWatchdog()
        status = watchdog.get_status()
        
        assert 'running' in status
        assert 'check_interval' in status
        assert 'crash_threshold' in status
        assert 'containers' in status
    
    def test_container_tracker(self):
        """Test ContainerTracker."""
        tracker = ContainerTracker(container="test")
        assert tracker.container == "test"
        assert len(tracker.crashes) == 0
        assert not tracker.stopped
    
    def test_crash_event(self):
        """Test CrashEvent."""
        event = CrashEvent(
            container="test",
            timestamp=datetime.utcnow(),
            exit_code=1
        )
        assert event.container == "test"
        assert event.exit_code == 1
        assert event.timestamp is not None