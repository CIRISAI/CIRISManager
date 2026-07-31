"""
Liveness watchdog for CIRISManager.

Monitors agent containers for two distinct failure modes:

1. **Crash loops** - a container restarting repeatedly. Detected by counting
   non-zero exits inside a sliding window; the container is stopped so it
   cannot thrash forever.

2. **Absence** - a registered agent with no running container at all. This is
   NOT a crash loop: the container exits once, stays exited, and RestartCount
   never leaves zero. The 2026-07-30 soak review found the scout2 agent had
   been down for three weeks after a host reboot precisely because nothing
   looked for this. Agent containers run with `restart: 'no'` (the manager owns
   lifecycle exclusively), so a host reboot leaves them dead until something
   notices.

Container discovery is driven by the **agent registry**, not by a container
name filter. The previous implementation ran `docker ps --filter
name=ciris-agent-` against the *local* Docker socket, which matched nothing in
production twice over: real containers are named `ciris-{agent_id}` (no
`agent-` infix), and the manager runs on its own server with no agent
containers on it at all. The watchdog therefore reported healthy while
monitoring an empty set.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Consecutive checks an agent must be absent before alerting. At the default
# 30s interval this is ~2.5 minutes, which rides out a normal deploy/restart
# window without alerting, while still catching a reboot within minutes rather
# than weeks.
_ABSENCE_ALERT_THRESHOLD = 5

# Container states that mean "this agent is not serving traffic".
_DEAD_STATES = {"exited", "dead", "created", "removing", "paused"}


@dataclass
class CrashEvent:
    """Record of a container crash."""

    container: str
    timestamp: datetime
    exit_code: int


@dataclass
class ContainerTracker:
    """Track crash events for a container."""

    container: str
    crashes: List[CrashEvent] = field(default_factory=list)
    stopped: bool = False
    # Consecutive checks this agent has been absent/not-running. Reset to 0 the
    # moment it is seen running again.
    absent_checks: int = 0
    absence_alerted: bool = False


class CrashLoopWatchdog:
    """Monitors containers for crash loops."""

    def __init__(
        self,
        check_interval: int = 30,
        crash_threshold: int = 3,
        crash_window: int = 300,  # 5 minutes
        agent_registry: Any = None,
        docker_client_manager: Any = None,
    ):
        """
        Initialize watchdog.

        Args:
            check_interval: Seconds between checks
            crash_threshold: Number of crashes to trigger intervention
            crash_window: Time window in seconds to count crashes
            agent_registry: AgentRegistry used to enumerate expected agents.
                Required for absence detection - without it the watchdog can
                only see containers that exist, never ones that should.
            docker_client_manager: MultiServerDockerClient used to reach each
                agent's own server. Without it the watchdog falls back to the
                local Docker socket, which on the manager host holds no agents.
        """
        self.check_interval = check_interval
        self.crash_threshold = crash_threshold
        self.crash_window = timedelta(seconds=crash_window)
        self.agent_registry = agent_registry
        self.docker_client_manager = docker_client_manager

        self._trackers: Dict[str, ContainerTracker] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def registry_driven(self) -> bool:
        """True when the watchdog can enumerate expected agents.

        Absence detection is only possible in this mode.
        """
        return self.agent_registry is not None and self.docker_client_manager is not None

    @staticmethod
    def _container_name(agent: Any) -> str:
        """Derive a container name from a registered agent.

        Mirrors the compose generator: `ciris-{agent_id}`, with the occurrence
        id appended for non-default occurrences (e.g. the second scout).
        """
        agent_id = getattr(agent, "agent_id", "")
        occurrence = getattr(agent, "occurrence_id", None)
        if occurrence and occurrence != "default":
            return f"ciris-{agent_id}-{occurrence}"
        return f"ciris-{agent_id}"

    async def start(self) -> None:
        """Start the watchdog monitoring loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            f"Crash loop watchdog started - threshold: {self.crash_threshold} "
            f"crashes in {self.crash_window.total_seconds()}s"
        )

    async def stop(self) -> None:
        """Stop the watchdog monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected: we just cancelled the task. Swallow so graceful
                # shutdown can complete and the process exits with code 0.
                logger.debug("Watchdog task cancelled as expected")
        logger.info("Crash loop watchdog stopped")

    async def _watchdog_loop(self) -> None:
        """Main watchdog monitoring loop."""
        while self._running:
            try:
                containers = await self._get_all_containers()

                for container in containers:
                    await self._check_container(container)

            except Exception as e:
                logger.error(f"Error in watchdog loop: {e}")

            await asyncio.sleep(self.check_interval)

    async def _get_all_containers(self) -> List[Dict]:
        """Enumerate expected agents and resolve each one's actual container.

        Returns one record per REGISTERED agent, whether or not a container
        exists for it. A record with ``Present=False`` is an absent agent -
        the case a container listing can never surface, because you cannot
        list something that is not there.
        """
        if not self.registry_driven:
            logger.debug("Watchdog not registry-driven; absence detection disabled")
            return []

        try:
            agents = await asyncio.to_thread(self.agent_registry.list_agents)
        except Exception as e:
            logger.error(f"Watchdog could not list registered agents: {e}")
            return []

        records: List[Dict] = []
        for agent in agents:
            server_id = getattr(agent, "server_id", None) or "main"
            name = self._container_name(agent)
            record: Dict[str, Any] = {
                "Names": name,
                "AgentId": getattr(agent, "agent_id", ""),
                "ServerId": server_id,
                "Present": False,
                "State": "absent",
                "ExitCode": None,
            }
            try:
                record.update(await self._inspect_remote(server_id, name))
            except Exception as e:
                # Could not reach the server at all. Do NOT treat that as
                # absence - "we couldn't look" and "it isn't there" are
                # different, and conflating them alerts on every network blip.
                logger.warning(f"Watchdog could not inspect {name} on {server_id}: {e}")
                record["State"] = "unknown"
                record["Unreachable"] = True
            records.append(record)

        return records

    async def _inspect_remote(self, server_id: str, name: str) -> Dict[str, Any]:
        """Inspect one container on its own server. Blocking Docker SDK call."""

        def _inspect() -> Dict[str, Any]:
            import docker.errors

            client = self.docker_client_manager.get_client(server_id)
            try:
                container = client.containers.get(name)
            except docker.errors.NotFound:
                return {"Present": False, "State": "absent", "ExitCode": None}
            state = container.attrs.get("State", {}) or {}
            return {
                "Present": True,
                "State": (state.get("Status") or "").lower(),
                "ExitCode": state.get("ExitCode"),
            }

        result: Dict[str, Any] = await asyncio.to_thread(_inspect)
        return result

    async def _check_container(self, container: Dict) -> None:
        """Check one agent for crash loops and for absence."""
        name = container["Names"]
        state = container.get("State", "")

        # Initialize tracker if needed
        if name not in self._trackers:
            self._trackers[name] = ContainerTracker(container=name)

        tracker = self._trackers[name]

        # Skip if already stopped by watchdog
        if tracker.stopped:
            return

        # We couldn't reach the server. Hold the previous absence state rather
        # than counting an unreachable host as a down agent.
        if container.get("Unreachable"):
            return

        running = state == "running"

        # --- absence detection -------------------------------------------
        # A registered agent that is missing entirely, or present but parked
        # in a non-running state, is not serving traffic. Agent containers use
        # `restart: 'no'`, so nothing will bring it back on its own.
        if running:
            if tracker.absence_alerted:
                logger.info(f"Agent container {name} is running again")
            tracker.absent_checks = 0
            tracker.absence_alerted = False
        elif state in _DEAD_STATES or not container.get("Present", False):
            tracker.absent_checks += 1
            if tracker.absent_checks >= _ABSENCE_ALERT_THRESHOLD and not tracker.absence_alerted:
                tracker.absence_alerted = True
                await self._handle_absence(container, tracker)

        # --- crash loop detection ----------------------------------------
        if state == "exited":
            exit_code = container.get("ExitCode")
            if exit_code is None:
                exit_code = await self._get_exit_code(name)

            if exit_code != 0:
                # Record crash
                crash = CrashEvent(container=name, timestamp=datetime.now(), exit_code=exit_code)
                tracker.crashes.append(crash)

                # Remove old crashes outside window
                cutoff = datetime.now() - self.crash_window
                tracker.crashes = [c for c in tracker.crashes if c.timestamp > cutoff]

                # Check for crash loop
                if len(tracker.crashes) >= self.crash_threshold:
                    await self._handle_crash_loop(tracker)

    async def _handle_absence(self, container: Dict, tracker: ContainerTracker) -> None:
        """Alert that a registered agent has no running container.

        Deliberately does NOT restart it. Agent containers are `restart: 'no'`
        so that the manager owns lifecycle exclusively; auto-recovery here
        would restart agents a human had deliberately stopped. Recovery stays
        an explicit operator action via `ciris-manager-client agent start`.
        """
        agent_id = container.get("AgentId") or tracker.container
        server_id = container.get("ServerId", "?")
        state = container.get("State", "absent")
        elapsed = tracker.absent_checks * self.check_interval
        await self._send_alert(
            f"Agent {agent_id} ({tracker.container}) on server {server_id} has had no "
            f"running container for ~{elapsed}s (state={state}). Nothing will restart "
            f"it automatically - run `ciris-manager-client agent start {agent_id}`."
        )

    async def _get_exit_code(self, container: str) -> int:
        """Get exit code of a container."""
        cmd = ["docker", "inspect", container, "--format", "{{.State.ExitCode}}"]

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()

        if process.returncode == 0:
            try:
                return int(stdout.decode().strip())
            except ValueError:
                return -1
        return -1

    async def _handle_crash_loop(self, tracker: ContainerTracker) -> None:
        """Handle a detected crash loop."""
        logger.error(
            f"Crash loop detected for {tracker.container}: "
            f"{len(tracker.crashes)} crashes in {self.crash_window.total_seconds()}s"
        )

        # Stop the container
        await self._stop_container(tracker.container)
        tracker.stopped = True

        # Send alert (implement notification mechanism later)
        await self._send_alert(
            f"Agent {tracker.container} stopped due to crash loop. Manual intervention required."
        )

    async def _stop_container(self, container: str) -> None:
        """Stop a container."""
        cmd = ["docker", "stop", container]

        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode == 0:
            logger.info(f"Stopped container {container}")
        else:
            logger.error(f"Failed to stop container {container}: {stderr.decode()}")

    async def _send_alert(self, message: str) -> None:
        """Send an alert about crash loop."""
        logger.critical(f"ALERT: {message}")

    def get_status(self) -> Dict[str, Any]:
        """Get current watchdog status."""
        return {
            "running": self._running,
            "check_interval": self.check_interval,
            "crash_threshold": self.crash_threshold,
            "crash_window": self.crash_window.total_seconds(),
            # False means absence detection is inactive - surfaced explicitly so
            # a degraded watchdog cannot masquerade as a healthy one.
            "registry_driven": self.registry_driven,
            "agents_absent": [
                name for name, tracker in self._trackers.items() if tracker.absence_alerted
            ],
            "containers": {
                name: {
                    "crashes": len(tracker.crashes),
                    "stopped": tracker.stopped,
                    "absent_checks": tracker.absent_checks,
                    "absence_alerted": tracker.absence_alerted,
                    "recent_crashes": [
                        {"timestamp": crash.timestamp.isoformat(), "exit_code": crash.exit_code}
                        for crash in tracker.crashes[-5:]  # Last 5 crashes
                    ],
                }
                for name, tracker in self._trackers.items()
            },
        }
