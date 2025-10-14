"""
Pydantic models for server management.

These models define data structures for server information, statistics,
and comparisons in the multi-server deployment system.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ServerInfo(BaseModel):
    """
    Basic server information response model.

    Used for listing servers with summary information.
    """

    server_id: str = Field(description="Unique identifier for the server (e.g., 'main', 'scout')")
    hostname: str = Field(description="Public hostname (e.g., 'agents.ciris.ai')")
    is_local: bool = Field(description="Whether this is the local server")
    vpc_ip: Optional[str] = Field(default=None, description="VPC private IP address")
    docker_host: Optional[str] = Field(default=None, description="Docker API endpoint URL")
    status: str = Field(description="Server connection status ('online' or 'offline')")
    agent_count: int = Field(description="Number of agents running on this server")


class ServerStats(BaseModel):
    """
    Server system statistics.

    Provides real-time resource usage metrics for a server.
    """

    cpu_percent: float = Field(description="CPU usage percentage (0-100)")
    memory_percent: float = Field(description="Memory usage percentage (0-100)")
    memory_total_gb: float = Field(description="Total memory in gigabytes")
    memory_used_gb: float = Field(description="Used memory in gigabytes")
    disk_percent: float = Field(description="Disk usage percentage (0-100)")
    disk_total_gb: float = Field(description="Total disk space in gigabytes")
    disk_used_gb: float = Field(description="Used disk space in gigabytes")
    load_average: Optional[List[float]] = Field(
        default=None, description="System load averages [1min, 5min, 15min]"
    )


class ServerDetails(BaseModel):
    """
    Detailed server information with stats.

    Combines basic server info with agent list and real-time statistics.
    """

    server_id: str = Field(description="Unique identifier for the server")
    hostname: str = Field(description="Public hostname")
    is_local: bool = Field(description="Whether this is the local server")
    vpc_ip: Optional[str] = Field(default=None, description="VPC private IP address")
    docker_host: Optional[str] = Field(default=None, description="Docker API endpoint URL")
    status: str = Field(description="Server connection status ('online' or 'offline')")
    agent_count: int = Field(description="Number of agents running on this server")
    agents: List[str] = Field(description="List of agent IDs running on this server")
    stats: Optional[ServerStats] = Field(
        default=None, description="Real-time system statistics (None if server is offline)"
    )


class ServerComparison(BaseModel):
    """
    Comparison between two servers.

    Used for analyzing resource usage and capacity differences between servers
    to aid in load balancing and migration decisions.
    """

    server_a: ServerInfo = Field(description="First server to compare")
    server_b: ServerInfo = Field(description="Second server to compare")
    stats_a: Optional[ServerStats] = Field(default=None, description="Statistics for first server")
    stats_b: Optional[ServerStats] = Field(default=None, description="Statistics for second server")
    cpu_diff: Optional[float] = Field(
        default=None, description="CPU usage difference (server_a - server_b)"
    )
    memory_diff: Optional[float] = Field(
        default=None, description="Memory usage difference in GB (server_a - server_b)"
    )
    disk_diff: Optional[float] = Field(
        default=None, description="Disk usage difference in GB (server_a - server_b)"
    )
    agent_count_diff: int = Field(description="Agent count difference (server_a - server_b)")
    recommendation: Optional[str] = Field(
        default=None, description="Recommendation for load balancing or migration"
    )
