"""
Crash loop detection watchdog for CIRISManager.

Monitors containers for repeated crashes and stops them
to prevent infinite restart loops.
"""
import asyncio
import logging
from typing import Dict, List, Set, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    

class CrashLoopWatchdog:
    """Monitors containers for crash loops."""
    
    def __init__(
        self,
        check_interval: int = 30,
        crash_threshold: int = 3,
        crash_window: int = 300  # 5 minutes
    ):
        """
        Initialize watchdog.
        
        Args:
            check_interval: Seconds between checks
            crash_threshold: Number of crashes to trigger intervention
            crash_window: Time window in seconds to count crashes
        """
        self.check_interval = check_interval
        self.crash_threshold = crash_threshold
        self.crash_window = timedelta(seconds=crash_window)
        
        self._trackers: Dict[str, ContainerTracker] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start the watchdog monitoring loop."""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            f"Crash loop watchdog started - threshold: {self.crash_threshold} "
            f"crashes in {self.crash_window.total_seconds()}s"
        )
        
    async def stop(self):
        """Stop the watchdog monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Crash loop watchdog stopped")
        
    async def _watchdog_loop(self):
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
        """Get all CIRIS agent containers."""
        cmd = ["docker", "ps", "-a", "--format", "json", "--filter", "name=ciris-agent-"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"Failed to list containers: {stderr.decode()}")
            return []
            
        # Parse JSON output
        import json
        containers = []
        for line in stdout.decode().strip().split('\n'):
            if line:
                containers.append(json.loads(line))
                
        return containers
        
    async def _check_container(self, container: Dict):
        """Check a container for crash loops."""
        name = container['Names']
        state = container['State']
        
        # Initialize tracker if needed
        if name not in self._trackers:
            self._trackers[name] = ContainerTracker(container=name)
            
        tracker = self._trackers[name]
        
        # Skip if already stopped by watchdog
        if tracker.stopped:
            return
            
        # Check if container exited with error
        if state == 'exited':
            exit_code = await self._get_exit_code(name)
            
            if exit_code != 0:
                # Record crash
                crash = CrashEvent(
                    container=name,
                    timestamp=datetime.now(),
                    exit_code=exit_code
                )
                tracker.crashes.append(crash)
                
                # Remove old crashes outside window
                cutoff = datetime.now() - self.crash_window
                tracker.crashes = [
                    c for c in tracker.crashes
                    if c.timestamp > cutoff
                ]
                
                # Check for crash loop
                if len(tracker.crashes) >= self.crash_threshold:
                    await self._handle_crash_loop(tracker)
                    
    async def _get_exit_code(self, container: str) -> int:
        """Get exit code of a container."""
        cmd = ["docker", "inspect", container, "--format", "{{.State.ExitCode}}"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        
        if process.returncode == 0:
            try:
                return int(stdout.decode().strip())
            except ValueError:
                return -1
        return -1
        
    async def _handle_crash_loop(self, tracker: ContainerTracker):
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
            f"Agent {tracker.container} stopped due to crash loop. "
            f"Manual intervention required."
        )
        
    async def _stop_container(self, container: str):
        """Stop a container."""
        cmd = ["docker", "stop", container]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info(f"Stopped container {container}")
        else:
            logger.error(f"Failed to stop container {container}: {stderr.decode()}")
            
    async def _send_alert(self, message: str):
        """Send an alert about crash loop."""
        # TODO: Implement actual alerting mechanism
        logger.critical(f"ALERT: {message}")
        
    def get_status(self) -> Dict[str, Any]:
        """Get current watchdog status."""
        return {
            'running': self._running,
            'check_interval': self.check_interval,
            'crash_threshold': self.crash_threshold,
            'crash_window': self.crash_window.total_seconds(),
            'containers': {
                name: {
                    'crashes': len(tracker.crashes),
                    'stopped': tracker.stopped,
                    'recent_crashes': [
                        {
                            'timestamp': crash.timestamp.isoformat(),
                            'exit_code': crash.exit_code
                        }
                        for crash in tracker.crashes[-5:]  # Last 5 crashes
                    ]
                }
                for name, tracker in self._trackers.items()
            }
        }