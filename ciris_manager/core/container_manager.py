"""
Container management service for CIRISManager.

Implements periodic docker-compose up -d to ensure containers
restart with latest images after any exit.
"""
import asyncio
import subprocess
import logging
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ContainerManager:
    """Manages Docker containers using docker-compose."""
    
    def __init__(self, compose_file: str, interval: int = 60):
        """
        Initialize container manager.
        
        Args:
            compose_file: Path to docker-compose.yml
            interval: Seconds between docker-compose up -d runs
        """
        self.compose_file = Path(compose_file)
        if not self.compose_file.exists():
            raise FileNotFoundError(f"Docker compose file not found: {compose_file}")
            
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start the container management loop."""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._management_loop())
        logger.info(f"Container manager started with {self.interval}s interval")
        
    async def stop(self):
        """Stop the container management loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Container manager stopped")
        
    async def _management_loop(self):
        """Main container management loop."""
        while self._running:
            try:
                # Pull latest images
                await self._run_compose_command(["pull"])
                
                # Start any stopped containers with latest image
                # This is idempotent - running containers unaffected
                await self._run_compose_command(["up", "-d"])
                
                # Check for agents that need update notification
                agents = await self._get_agents_status()
                for agent in agents:
                    if await self._needs_update(agent):
                        await self._notify_update_available(agent)
                        
            except Exception as e:
                logger.error(f"Error in container management loop: {e}")
                
            # Wait for next iteration
            await asyncio.sleep(self.interval)
            
    async def _run_compose_command(self, args: List[str]) -> str:
        """Run a docker-compose command."""
        cmd = ["docker-compose", "-f", str(self.compose_file)] + args
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise RuntimeError(f"docker-compose command failed: {stderr.decode()}")
                
            return stdout.decode()
            
        except Exception as e:
            logger.error(f"Failed to run docker-compose command: {e}")
            raise
            
    async def _get_agents_status(self) -> List[Dict]:
        """Get status of all agents from docker-compose."""
        output = await self._run_compose_command(["ps", "--format", "json"])
        
        # Parse JSON output
        import json
        containers = []
        for line in output.strip().split('\n'):
            if line:
                containers.append(json.loads(line))
                
        # Filter for agent containers
        agents = []
        for container in containers:
            if container.get('Service', '').startswith('agent-'):
                agents.append({
                    'name': container['Service'],
                    'container': container['Name'],
                    'state': container['State'],
                    'image': container['Image']
                })
                
        return agents
        
    async def _needs_update(self, agent: Dict) -> bool:
        """Check if an agent needs update notification."""
        if agent['state'] != 'running':
            return False
            
        # Get latest image ID
        latest_image = await self._get_latest_image(agent['name'])
        current_image = await self._get_container_image(agent['container'])
        
        return latest_image != current_image
        
    async def _get_latest_image(self, service_name: str) -> str:
        """Get latest image ID for a service."""
        # Get image name from docker-compose config
        output = await self._run_compose_command(["config", "--services"])
        if service_name not in output:
            return ""
            
        # Get image details
        output = await self._run_compose_command(["config", "--images"])
        images = output.strip().split('\n')
        
        # Find image for this service
        for image in images:
            if service_name in image:
                # Get image ID
                cmd = ["docker", "images", "--no-trunc", "-q", image.strip()]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await process.communicate()
                return stdout.decode().strip()
                
        return ""
        
    async def _get_container_image(self, container_name: str) -> str:
        """Get current image ID of a running container."""
        cmd = ["docker", "inspect", container_name, "--format", "{{.Image}}"]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        
        if process.returncode == 0:
            return stdout.decode().strip()
        return ""
        
    async def _notify_update_available(self, agent: Dict):
        """Notify agent that an update is available."""
        # This will be implemented when we add local auth
        logger.info(f"Update available for {agent['name']} - notification pending local auth implementation")