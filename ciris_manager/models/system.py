"""
Pydantic models for system-related data structures.

These models define the schema for system health, status monitoring,
port allocation tracking, and deployment token management.
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from datetime import datetime


class SystemHealth(BaseModel):
    """
    System health status information.

    Provides a quick health check response including manager version,
    uptime, and Docker availability. This is used for health monitoring
    and does not require authentication.
    """

    status: str = Field(default="healthy", description="Overall system status")
    manager_version: str = Field(description="CIRISManager version string")
    uptime_seconds: int = Field(description="System uptime in seconds")
    agents_count: int = Field(description="Number of active agents")
    docker_available: bool = Field(description="Whether Docker is accessible")


class SystemStatus(BaseModel):
    """
    Detailed system status information.

    Includes health status, resource usage metrics, and port allocation
    information. Requires authentication to access.
    """

    health: SystemHealth = Field(description="Basic health status")
    resources: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resource usage including CPU, memory, and disk metrics",
    )
    ports: Dict[str, int] = Field(default_factory=dict, description="Agent ID to port mapping")


class PortRange(BaseModel):
    """
    Port allocation range configuration.

    Defines the range of ports available for dynamic allocation
    to agent containers.
    """

    start: int = Field(description="First port in allocation range")
    end: int = Field(description="Last port in allocation range")


class PortAllocation(BaseModel):
    """
    Port allocation information.

    Tracks which ports are allocated to agents, which are available,
    and which are reserved for system use.
    """

    allocated: Dict[str, int] = Field(
        default_factory=dict, description="Agent ID to allocated port mapping"
    )
    available: List[int] = Field(default_factory=list, description="List of available ports")
    reserved: List[int] = Field(
        default_factory=list, description="List of reserved ports (e.g., 8888, 80, 443)"
    )
    range: Optional[PortRange] = Field(
        default=None, description="Port allocation range configuration"
    )


class AllocatedPortsResponse(BaseModel):
    """
    Response model for allocated ports endpoint (legacy).

    Provides a list of allocated port numbers, reserved ports,
    and the allocation range configuration.
    """

    allocated: List[int] = Field(default_factory=list, description="List of allocated port numbers")
    reserved: List[int] = Field(default_factory=list, description="List of reserved port numbers")
    range: PortRange = Field(description="Port allocation range")


class DeploymentTokenInfo(BaseModel):
    """
    Deployment token configuration for a repository.

    Contains the GitHub secret name and value for configuring
    deployment authentication.
    """

    secret_name: str = Field(description="GitHub secret name (e.g., DEPLOY_TOKEN)")
    secret_value: str = Field(description="Token value for deployment authentication")


class DeploymentToken(BaseModel):
    """
    Deployment tokens for GitHub repository configuration.

    Provides tokens for authenticating CD pipeline deployments from
    GitHub Actions. Only accessible to @ciris.ai users.
    """

    status: str = Field(default="success", description="Response status")
    tokens: Dict[str, DeploymentTokenInfo] = Field(
        default_factory=dict,
        description="Repository to token configuration mapping",
    )
    instructions: str = Field(
        default="Add these as repository secrets in GitHub Settings > Secrets and variables > Actions",
        description="Instructions for configuring tokens",
    )


class SystemMetrics(BaseModel):
    """
    System metrics for monitoring and observability.

    Provides detailed metrics about system performance, agent status,
    and deployment activity.
    """

    timestamp: datetime = Field(description="Metric collection timestamp (UTC)")
    uptime_seconds: int = Field(description="System uptime in seconds")
    agents: Dict[str, int] = Field(
        default_factory=dict,
        description="Agent count breakdown (total, running, stopped)",
    )
    deployments: Dict[str, int] = Field(
        default_factory=dict,
        description="Deployment statistics (total, active, failed)",
    )
    resources: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resource usage percentages (CPU, memory, disk)",
    )


class StatusResponse(BaseModel):
    """
    Manager status response (legacy).

    Provides overall manager status including version, components,
    and optional uptime/metrics information.
    """

    status: str = Field(description="Overall status (e.g., 'running', 'healthy')")
    version: str = Field(default="2.2.0", description="Manager version")
    components: Dict[str, str] = Field(default_factory=dict, description="Component status mapping")
    auth_mode: Optional[str] = Field(default=None, description="Authentication mode")
    uptime_seconds: Optional[int] = Field(default=None, description="Uptime in seconds")
    start_time: Optional[str] = Field(default=None, description="ISO 8601 start timestamp")
    system_metrics: Optional[Dict[str, Any]] = Field(
        default=None, description="System metrics data"
    )
