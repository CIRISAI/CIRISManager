"""
Server management API routes.

Provides endpoints for viewing and managing remote servers in the multi-server deployment system.
"""

import logging
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ServerInfo(BaseModel):
    """Server information response model."""

    server_id: str
    hostname: str
    is_local: bool
    vpc_ip: str | None = None
    docker_host: str | None = None
    status: str
    agent_count: int


class ServerStats(BaseModel):
    """Server system statistics."""

    cpu_percent: float
    memory_percent: float
    memory_total_gb: float
    memory_used_gb: float
    disk_percent: float
    disk_total_gb: float
    disk_used_gb: float
    load_average: List[float] | None = None


class ServerDetails(BaseModel):
    """Detailed server information with stats."""

    server_id: str
    hostname: str
    is_local: bool
    vpc_ip: str | None = None
    docker_host: str | None = None
    status: str
    agent_count: int
    agents: List[str]
    stats: ServerStats | None = None


def create_server_routes(manager) -> APIRouter:
    """
    Create server management API routes.

    Args:
        manager: CIRISManager instance

    Returns:
        Configured FastAPI router
    """
    router = APIRouter(tags=["servers"])

    @router.get("/servers", response_model=List[ServerInfo])
    async def list_servers() -> List[ServerInfo]:
        """
        List all configured servers with basic info.

        Returns:
            List of server information
        """
        servers = []

        for server_config in manager.config.servers:
            # Test connection status
            is_online = manager.docker_client.test_connection(server_config.server_id)

            # Count agents on this server
            agent_count = sum(
                1
                for agent in manager.agent_registry.list_agents()
                if (hasattr(agent, "server_id") and agent.server_id == server_config.server_id)
                or (not hasattr(agent, "server_id") and server_config.server_id == "main")
            )

            servers.append(
                ServerInfo(
                    server_id=server_config.server_id,
                    hostname=server_config.hostname,
                    is_local=server_config.is_local,
                    vpc_ip=server_config.vpc_ip,
                    docker_host=server_config.docker_host if not server_config.is_local else None,
                    status="online" if is_online else "offline",
                    agent_count=agent_count,
                )
            )

        return servers

    @router.get("/servers/{server_id}", response_model=ServerDetails)
    async def get_server_details(server_id: str) -> ServerDetails:
        """
        Get detailed information about a specific server.

        Args:
            server_id: Server identifier

        Returns:
            Detailed server information with stats

        Raises:
            HTTPException: If server not found or stats unavailable
        """
        # Validate server exists
        try:
            server_config = manager.docker_client.get_server_config(server_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

        # Test connection
        is_online = manager.docker_client.test_connection(server_id)

        # Get agents on this server
        server_agents = [
            agent.agent_id
            for agent in manager.agent_registry.list_agents()
            if (hasattr(agent, "server_id") and agent.server_id == server_id)
            or (not hasattr(agent, "server_id") and server_id == "main")
        ]

        # Get system stats if online
        stats = None
        if is_online:
            try:
                stats = await get_server_stats(server_id)
            except Exception as e:
                logger.warning(f"Failed to get stats for server {server_id}: {e}")

        return ServerDetails(
            server_id=server_config.server_id,
            hostname=server_config.hostname,
            is_local=server_config.is_local,
            vpc_ip=server_config.vpc_ip,
            docker_host=server_config.docker_host if not server_config.is_local else None,
            status="online" if is_online else "offline",
            agent_count=len(server_agents),
            agents=server_agents,
            stats=stats,
        )

    @router.get("/servers/{server_id}/stats", response_model=ServerStats)
    async def get_server_stats(server_id: str) -> ServerStats:
        """
        Get real-time system statistics for a server.

        Args:
            server_id: Server identifier

        Returns:
            Server system statistics

        Raises:
            HTTPException: If server not found or offline
        """
        # Validate server exists
        try:
            server_config = manager.docker_client.get_server_config(server_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

        # Get Docker client for server
        try:
            docker_client = manager.docker_client.get_client(server_id)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Server '{server_id}' is offline: {e}")

        # For remote servers, we need to run a container to get stats
        # For local server, we can use psutil directly
        if server_config.is_local:
            try:
                import psutil

                mem = psutil.virtual_memory()
                disk = psutil.disk_usage("/")

                return ServerStats(
                    cpu_percent=psutil.cpu_percent(interval=0.1),
                    memory_percent=mem.percent,
                    memory_total_gb=round(mem.total / (1024**3), 2),
                    memory_used_gb=round(mem.used / (1024**3), 2),
                    disk_percent=psutil.disk_usage("/").percent,
                    disk_total_gb=round(disk.total / (1024**3), 2),
                    disk_used_gb=round(disk.used / (1024**3), 2),
                    load_average=list(psutil.getloadavg())
                    if hasattr(psutil, "getloadavg")
                    else None,
                )
            except ImportError:
                raise HTTPException(status_code=500, detail="psutil not installed")
        else:
            # Remote server: Run a lightweight container to get stats
            # For now, return Docker API stats as a fallback
            try:
                # Get system info from Docker API
                info = docker_client.info()

                # Calculate memory stats
                mem_total = info.get("MemTotal", 0)
                mem_total_gb = round(mem_total / (1024**3), 2)

                # Docker doesn't provide used memory directly, so we'll estimate
                # based on container usage
                containers = docker_client.containers.list()
                mem_used = 0
                for container in containers:
                    stats = container.stats(stream=False)
                    mem_used += stats.get("memory_stats", {}).get("usage", 0)

                mem_used_gb = round(mem_used / (1024**3), 2)
                mem_percent = round((mem_used / mem_total * 100), 2) if mem_total > 0 else 0

                # Note: CPU and disk stats not available via Docker API for remote servers
                return ServerStats(
                    cpu_percent=0.0,  # Docker API doesn't provide system-wide CPU easily
                    memory_percent=mem_percent,
                    memory_total_gb=mem_total_gb,
                    memory_used_gb=mem_used_gb,
                    disk_percent=0.0,  # Would need additional container to get this
                    disk_total_gb=0.0,
                    disk_used_gb=0.0,
                    load_average=None,
                )
            except Exception as e:
                logger.error(f"Failed to get stats from remote server {server_id}: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to get stats from remote server: {e}"
                )

    @router.get("/servers/{server_id}/agents", response_model=List[str])
    async def list_server_agents(server_id: str) -> List[str]:
        """
        List all agents running on a specific server.

        Args:
            server_id: Server identifier

        Returns:
            List of agent IDs on this server

        Raises:
            HTTPException: If server not found
        """
        # Validate server exists
        try:
            manager.docker_client.get_server_config(server_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

        # Get agents on this server
        server_agents = [
            agent.agent_id
            for agent in manager.agent_registry.list_agents()
            if (hasattr(agent, "server_id") and agent.server_id == server_id)
            or (not hasattr(agent, "server_id") and server_id == "main")
        ]

        return server_agents

    return router
