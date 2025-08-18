"""
Clean v2 API models - No legacy cruft.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class Agent(BaseModel):
    """Clean agent model - no version info here."""

    agent_id: str
    name: str
    container_name: str
    template: str
    deployment: str = Field(default="CIRIS_DISCORD_PILOT")
    status: str
    port: int
    health: str = Field(default="unknown")


class Version(BaseModel):
    """Version information for a component."""

    component: str  # agent/gui/nginx
    current: str
    previous: Optional[str] = None
    rollback: Optional[str] = None
    deployed_at: datetime
    deployed_by: str = Field(default="system")


class FleetVersion(BaseModel):
    """Version info for a specific agent."""

    agent_id: str
    agent_name: str
    version: str
    codename: Optional[str] = None
    code_hash: Optional[str] = None
    status: str
    deployment: str = Field(default="CIRIS_DISCORD_PILOT")


class FleetVersions(BaseModel):
    """Fleet-wide version information."""

    agents: List[FleetVersion]
    adoption: Dict[str, List[str]]  # version -> [agent_ids]
    total_agents: int


class Deployment(BaseModel):
    """Clean deployment model."""

    id: str
    status: str  # pending/executing/complete/failed
    strategy: str = Field(default="immediate")  # immediate/canary/staged
    targets: List[str]  # Component types or agent IDs
    versions: Dict[str, str]  # component -> version
    created_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    message: Optional[str] = None


class Template(BaseModel):
    """Agent template information."""

    name: str
    description: str
    stewardship_tier: int
    pre_approved: bool
    checksum: Optional[str] = None


class SystemHealth(BaseModel):
    """System health status."""

    status: str = Field(default="healthy")
    manager_version: str
    uptime_seconds: int
    agents_count: int
    docker_available: bool


class SystemStatus(BaseModel):
    """Detailed system status."""

    health: SystemHealth
    resources: Dict[str, Any]
    ports: Dict[str, int]  # agent_id -> port


class PortAllocation(BaseModel):
    """Port allocation info."""

    allocated: Dict[str, int]  # agent_id -> port
    available: List[int]
    reserved: List[int]
