"""
System namespace - Manager health and status.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any
from datetime import datetime
import psutil
import time

from .models import SystemHealth, SystemStatus, PortAllocation
from ciris_manager.api.auth import get_current_user_dependency as get_current_user
from ciris_manager.manager_core import get_manager


router = APIRouter(prefix="/system", tags=["system"])

# Track startup time
STARTUP_TIME = time.time()


@router.get("/health")
async def health_check() -> SystemHealth:
    """
    Simple health check - no auth required.
    """
    # Check Docker availability
    try:
        import docker

        client = docker.from_env()
        docker_available = True
        agents_count = len(
            [c for c in client.containers.list() if c.name and "ciris-agent" in c.name]
        )
    except Exception:
        docker_available = False
        agents_count = 0

    uptime = int(time.time() - STARTUP_TIME)

    return SystemHealth(
        status="healthy",
        manager_version="2.0.0",  # Clean v2
        uptime_seconds=uptime,
        agents_count=agents_count,
        docker_available=docker_available,
    )


@router.get("/status")
async def system_status(_user: Dict[str, str] = Depends(get_current_user)) -> SystemStatus:
    """
    Detailed system status.
    """
    health = await health_check()

    # Get resource usage
    resources = {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": {
            "total": psutil.virtual_memory().total,
            "used": psutil.virtual_memory().used,
            "percent": psutil.virtual_memory().percent,
        },
        "disk": {
            "total": psutil.disk_usage("/").total,
            "used": psutil.disk_usage("/").used,
            "percent": psutil.disk_usage("/").percent,
        },
    }

    # Get port allocations
    manager = get_manager()
    ports = {}
    for agent_id, agent in manager.agent_registry.agents.items():
        if hasattr(agent, "port"):
            ports[agent_id] = agent.port

    return SystemStatus(health=health, resources=resources, ports=ports)


@router.get("/ports")
async def port_allocations(_user: Dict[str, str] = Depends(get_current_user)) -> PortAllocation:
    """
    Get port allocation information.
    """
    manager = get_manager()

    # Get allocated ports
    allocated = {}
    for agent_id, agent in manager.agent_registry.agents.items():
        if hasattr(agent, "port"):
            allocated[agent_id] = agent.port

    # Calculate available ports (8080-8099 range)
    all_ports = set(range(8080, 8100))
    used_ports = set(allocated.values())
    available = sorted(list(all_ports - used_ports))

    # Reserved ports
    reserved = [8888]  # Manager API port

    return PortAllocation(allocated=allocated, available=available, reserved=reserved)


@router.get("/metrics")
async def system_metrics(_user: Dict[str, str] = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Get system metrics for monitoring.
    """
    manager = get_manager()

    # Collect metrics
    metrics: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": int(time.time() - STARTUP_TIME),
        "agents": {"total": len(manager.agent_registry.agents), "running": 0, "stopped": 0},
        "deployments": {"total": 0, "active": 0, "failed_last_hour": 0},
        "resources": {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        },
    }

    # Count agent states
    try:
        import docker

        client = docker.from_env()
        for container in client.containers.list(all=True):
            if container.name and "ciris-agent" in container.name:
                if container.status == "running":
                    metrics["agents"]["running"] += 1
                else:
                    metrics["agents"]["stopped"] += 1
    except Exception:
        pass

    return metrics
