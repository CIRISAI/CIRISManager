"""
Simple unit tests for CrashLoopWatchdog.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ciris_manager.core.watchdog import (
    _ABSENCE_ALERT_THRESHOLD,
    CrashLoopWatchdog,
    ContainerTracker,
    CrashEvent,
)
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


class TestAbsenceDetection:
    """The failure mode the crash-loop counter structurally cannot see.

    scout2's agent exited once after a host reboot and stayed exited with
    RestartCount=0 for three weeks. That is never a crash loop, so the old
    watchdog was silent - and it was doubly silent because it filtered on
    `name=ciris-agent-`, which matches no production container, using the local
    Docker socket on a host that runs no agents.
    """

    def _agent(self, agent_id="scout", server_id="scout2", occurrence_id=None):
        return SimpleNamespace(agent_id=agent_id, server_id=server_id, occurrence_id=occurrence_id)

    def _watchdog(self, agents):
        registry = MagicMock()
        registry.list_agents.return_value = agents
        return CrashLoopWatchdog(
            check_interval=30,
            agent_registry=registry,
            docker_client_manager=MagicMock(),
        )

    def test_container_name_matches_production_convention(self):
        """Production containers are `ciris-{agent_id}`, not `ciris-agent-{id}`."""
        wd = CrashLoopWatchdog()
        assert wd._container_name(self._agent("datum")) == "ciris-datum"
        assert (
            wd._container_name(self._agent("scout-remote-test-dahrb9", occurrence_id="002"))
            == "ciris-scout-remote-test-dahrb9-002"
        )
        # "default" is not a real occurrence suffix
        assert (
            wd._container_name(self._agent("scout-remote-test-dahrb9", occurrence_id="default"))
            == "ciris-scout-remote-test-dahrb9"
        )

    def test_registry_driven_requires_both_dependencies(self):
        assert CrashLoopWatchdog().registry_driven is False
        assert (
            CrashLoopWatchdog(agent_registry=MagicMock()).registry_driven is False
        ), "registry alone cannot reach remote servers"
        assert self._watchdog([]).registry_driven is True

    @pytest.mark.asyncio
    async def test_absent_agent_alerts_after_threshold(self):
        wd = self._watchdog([self._agent()])
        record = {
            "Names": "ciris-scout",
            "AgentId": "scout",
            "ServerId": "scout2",
            "Present": False,
            "State": "absent",
            "ExitCode": None,
        }
        with patch.object(wd, "_send_alert") as alert:
            for _ in range(4):
                await wd._check_container(record)
            assert alert.call_count == 0, "must not alert during a normal deploy window"
            await wd._check_container(record)
            assert alert.call_count == 1

            # Must not re-alert every cycle once it has fired.
            await wd._check_container(record)
            assert alert.call_count == 1

    @pytest.mark.asyncio
    async def test_exited_zero_agent_is_still_absent(self):
        """Exit code 0 is not a crash - but the agent is still down.

        This is exactly scout2: a clean exit that no crash counter would ever
        flag, leaving the agent dead indefinitely.
        """
        wd = self._watchdog([self._agent()])
        record = {
            "Names": "ciris-scout",
            "AgentId": "scout",
            "ServerId": "scout2",
            "Present": True,
            "State": "exited",
            "ExitCode": 0,
        }
        with patch.object(wd, "_send_alert") as alert:
            for _ in range(_ABSENCE_ALERT_THRESHOLD):
                await wd._check_container(record)
        assert alert.call_count == 1
        # No crash recorded, because exit 0 is not a crash.
        assert wd._trackers["ciris-scout"].crashes == []

    @pytest.mark.asyncio
    async def test_unreachable_host_is_not_reported_as_absent(self):
        """ "We couldn't look" must never be reported as "it isn't there"."""
        wd = self._watchdog([self._agent()])
        record = {
            "Names": "ciris-scout",
            "AgentId": "scout",
            "ServerId": "scout2",
            "State": "unknown",
            "Unreachable": True,
        }
        with patch.object(wd, "_send_alert") as alert:
            for _ in range(_ABSENCE_ALERT_THRESHOLD * 2):
                await wd._check_container(record)
        assert alert.call_count == 0
        assert wd._trackers["ciris-scout"].absent_checks == 0

    @pytest.mark.asyncio
    async def test_recovery_resets_absence_state(self):
        wd = self._watchdog([self._agent()])
        down = {
            "Names": "ciris-scout",
            "AgentId": "scout",
            "ServerId": "scout2",
            "State": "exited",
            "ExitCode": 0,
            "Present": True,
        }
        up = {
            "Names": "ciris-scout",
            "AgentId": "scout",
            "ServerId": "scout2",
            "State": "running",
            "Present": True,
        }
        with patch.object(wd, "_send_alert"):
            for _ in range(_ABSENCE_ALERT_THRESHOLD):
                await wd._check_container(down)
            assert wd._trackers["ciris-scout"].absence_alerted is True
            await wd._check_container(up)
        tracker = wd._trackers["ciris-scout"]
        assert tracker.absent_checks == 0
        assert tracker.absence_alerted is False

    @pytest.mark.asyncio
    async def test_get_status_surfaces_degraded_watchdog(self):
        """A watchdog that cannot detect absence must say so.

        The old one logged "Crash loop watchdog started" and then monitored an
        empty set forever, which read as healthy.
        """
        assert CrashLoopWatchdog().get_status()["registry_driven"] is False
        status = self._watchdog([]).get_status()
        assert status["registry_driven"] is True
        assert status["agents_absent"] == []
