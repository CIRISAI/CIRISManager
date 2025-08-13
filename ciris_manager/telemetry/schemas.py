"""
Type-safe telemetry schemas for CIRISManager.

These schemas define the complete data model for infrastructure telemetry.
No Dict[str, Any] allowed - everything is strictly typed.
"""

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


# ============================================================================
# ENUMS - No magic strings
# ============================================================================


class ContainerStatus(str, Enum):
    """Docker container status states."""

    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    PAUSED = "paused"
    EXITED = "exited"
    DEAD = "dead"
    CREATED = "created"
    REMOVING = "removing"
    UNKNOWN = "unknown"


class HealthStatus(str, Enum):
    """Container health check status."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    NONE = "none"  # No health check defined
    UNKNOWN = "unknown"


class CognitiveState(str, Enum):
    """Agent cognitive states from CIRIS - matches actual API."""

    WAKEUP = "WAKEUP"
    WORK = "WORK"
    PLAY = "PLAY"
    SOLITUDE = "SOLITUDE"
    DREAM = "DREAM"
    SHUTDOWN = "SHUTDOWN"
    UNKNOWN = "unknown"


class DeploymentStatus(str, Enum):
    """Deployment lifecycle states - matches models.py."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    STAGED = "staged"  # Added for staged deployments


class DeploymentPhase(str, Enum):
    """Canary deployment phases - matches actual implementation."""

    EXPLORERS = "explorers"
    EARLY_ADOPTERS = "early_adopters"
    GENERAL = "general"
    COMPLETE = "complete"


class ComponentType(str, Enum):
    """Types of components we track versions for."""

    AGENT = "agent"
    GUI = "gui"
    NGINX = "nginx"
    MANAGER = "manager"


# ============================================================================
# CONTAINER METRICS - Docker infrastructure
# ============================================================================


class ContainerResources(BaseModel):
    """Resource usage for a container."""

    model_config = ConfigDict(strict=True)

    cpu_percent: float = Field(
        ge=0, le=10000, description="CPU usage percentage (can exceed 100% for multi-core)"
    )
    memory_mb: int = Field(ge=0, description="Memory usage in megabytes")
    memory_limit_mb: Optional[int] = Field(None, ge=0, description="Memory limit if set")
    memory_percent: float = Field(ge=0, le=100, description="Memory usage as percentage of limit")
    disk_read_mb: int = Field(ge=0, description="Cumulative disk read in MB")
    disk_write_mb: int = Field(ge=0, description="Cumulative disk write in MB")
    network_rx_mb: int = Field(ge=0, description="Network received in MB")
    network_tx_mb: int = Field(ge=0, description="Network transmitted in MB")


class ContainerMetrics(BaseModel):
    """Complete container metrics at a point in time."""

    model_config = ConfigDict(strict=True, extra="forbid")

    container_id: str = Field(min_length=12, max_length=64)
    container_name: str = Field(min_length=1, max_length=255)
    image: str = Field(min_length=1)
    image_digest: Optional[str] = None

    status: ContainerStatus
    health: HealthStatus
    restart_count: int = Field(ge=0)

    resources: ContainerResources

    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    exit_code: Optional[int] = None
    error_message: Optional[str] = None


# ============================================================================
# AGENT METRICS - High-level operational state (not internal details)
# ============================================================================


class AgentOperationalMetrics(BaseModel):
    """Agent operational metrics that Manager needs for infrastructure decisions."""

    model_config = ConfigDict(strict=True)

    agent_id: str = Field(min_length=1, max_length=255)
    agent_name: str = Field(min_length=1, max_length=255)

    # Version info for deployment tracking
    version: str = Field(min_length=1)

    # Cognitive state for operational awareness
    cognitive_state: CognitiveState

    # Basic health for routing decisions
    api_healthy: bool
    api_response_time_ms: Optional[int] = Field(None, ge=0, le=30000)

    # High-level metrics for capacity planning
    uptime_seconds: int = Field(ge=0)
    incident_count_24h: int = Field(ge=0, description="Number of incidents in last 24 hours")
    message_count_24h: int = Field(ge=0, description="Messages processed in last 24 hours")

    # Resource constraints
    cost_cents_24h: int = Field(ge=0, description="Operational cost in last 24 hours")

    # Port for routing
    api_port: int = Field(gt=0, le=65535)

    # OAuth status for UI
    oauth_configured: bool = False
    oauth_providers: List[str] = Field(default_factory=list)


# ============================================================================
# DEPLOYMENT METRICS - CD and version tracking
# ============================================================================


class DeploymentMetrics(BaseModel):
    """Deployment state and progress."""

    model_config = ConfigDict(strict=True)

    deployment_id: str = Field(min_length=1)
    status: DeploymentStatus
    phase: Optional[DeploymentPhase] = None

    # What's being deployed
    agent_image: Optional[str] = None
    gui_image: Optional[str] = None
    nginx_image: Optional[str] = None

    # Progress tracking
    agents_total: int = Field(ge=0)
    agents_staged: int = Field(ge=0)
    agents_updated: int = Field(ge=0)
    agents_failed: int = Field(ge=0)
    agents_deferred: int = Field(ge=0)

    # Timing
    created_at: datetime
    staged_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Human operator
    initiated_by: Optional[str] = None
    approved_by: Optional[str] = None

    # Rollback info
    is_rollback: bool = False
    rollback_from_deployment: Optional[str] = None

    # Additional info
    message: Optional[str] = None
    duration_seconds: Optional[int] = None


# ============================================================================
# VERSION TRACKING - What versions are where
# ============================================================================


class VersionInfo(BaseModel):
    """Version information for a component."""

    model_config = ConfigDict(strict=True)

    image: str = Field(min_length=1)
    digest: Optional[str] = None
    tag: str = Field(min_length=1)
    deployed_at: datetime
    deployment_id: Optional[str] = None


class VersionState(BaseModel):
    """Version state for a component type."""

    model_config = ConfigDict(strict=True)

    component_type: ComponentType

    current: Optional[VersionInfo] = None  # n
    previous: Optional[VersionInfo] = None  # n-1
    fallback: Optional[VersionInfo] = None  # n-2
    staged: Optional[VersionInfo] = None  # n+1 (pending deployment)

    last_updated: datetime


class AgentVersionAdoption(BaseModel):
    """Track which agents are on which versions."""

    model_config = ConfigDict(strict=True)

    agent_id: str
    agent_name: str
    current_version: str
    last_transition_at: Optional[datetime] = None
    last_work_state_at: Optional[datetime] = None

    # Deployment group for canary - matches actual groups
    deployment_group: Literal["explorers", "early_adopters", "general"]


# ============================================================================
# TELEMETRY SNAPSHOT - Complete system state at a point in time
# ============================================================================


class TelemetrySnapshot(BaseModel):
    """Complete telemetry snapshot - the atomic unit of collection."""

    model_config = ConfigDict(strict=True)

    snapshot_id: str = Field(min_length=1)
    timestamp: datetime

    # All metrics collected at this point
    containers: List[ContainerMetrics]
    agents: List[AgentOperationalMetrics]
    deployments: List[DeploymentMetrics]  # Active deployments
    versions: List[VersionState]  # Version states for all components
    adoption: List[AgentVersionAdoption]  # Which agent has which version

    # Collection metadata
    collection_duration_ms: int = Field(ge=0)
    errors: List[str] = Field(default_factory=list)


# ============================================================================
# AGGREGATED METRICS - For dashboard and monitoring
# ============================================================================


class SystemSummary(BaseModel):
    """Aggregated system metrics for dashboard."""

    model_config = ConfigDict(strict=True)

    timestamp: datetime

    # Agent summary
    agents_total: int = Field(ge=0)
    agents_healthy: int = Field(ge=0)
    agents_degraded: int = Field(ge=0)
    agents_down: int = Field(ge=0)

    # Cognitive state distribution
    agents_in_work: int = Field(ge=0)
    agents_in_dream: int = Field(ge=0)
    agents_in_solitude: int = Field(ge=0)
    agents_in_play: int = Field(ge=0)

    # Resource usage
    total_cpu_percent: float = Field(ge=0)
    total_memory_mb: int = Field(ge=0)
    total_cost_cents_24h: int = Field(ge=0)

    # Activity
    total_messages_24h: int = Field(ge=0)
    total_incidents_24h: int = Field(ge=0)

    # Deployment status
    active_deployments: int = Field(ge=0)
    staged_deployments: int = Field(ge=0)

    # Version adoption
    agents_on_latest: int = Field(ge=0)
    agents_on_previous: int = Field(ge=0)
    agents_on_older: int = Field(ge=0)


# ============================================================================
# API MODELS - For querying telemetry
# ============================================================================


class TelemetryQuery(BaseModel):
    """Query parameters for telemetry data."""

    model_config = ConfigDict(strict=True)

    start_time: datetime
    end_time: datetime

    # Optional filters
    agent_ids: Optional[List[str]] = None
    container_names: Optional[List[str]] = None
    include_resources: bool = True
    include_deployments: bool = True
    include_versions: bool = True

    # Aggregation
    interval: Optional[Literal["1m", "5m", "1h", "1d"]] = None

    # Pagination
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class TelemetryResponse(BaseModel):
    """Response from telemetry query."""

    model_config = ConfigDict(strict=True)

    query: TelemetryQuery
    snapshots: List[TelemetrySnapshot]
    summary: Optional[SystemSummary] = None

    total_count: int = Field(ge=0)
    has_more: bool


# ============================================================================
# STATISTICS MODELS - No more raw dicts!
# ============================================================================


class CollectorStats(BaseModel):
    """Statistics for a single collector."""

    model_config = ConfigDict(strict=True)

    name: str
    collections: int = Field(ge=0)
    errors: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    last_collection: Optional[str] = None  # ISO timestamp
    last_error: Optional[str] = None


class CompositeCollectorStats(BaseModel):
    """Statistics for composite collector with sub-collectors."""

    model_config = ConfigDict(strict=True)

    composite: CollectorStats
    collectors: dict[str, CollectorStats]  # Key is collector name, value is typed!


class HealthCheckResult(BaseModel):
    """Health check result for a collector."""

    model_config = ConfigDict(strict=True)

    healthy: bool
    available: bool
    stats: Optional[CollectorStats] = None
    error: Optional[str] = None


class PublicStatus(BaseModel):
    """Public-safe status information."""

    model_config = ConfigDict(strict=True)

    total_agents: int = Field(ge=0)
    healthy_percentage: float = Field(ge=0, le=100)
    messages_24h: int = Field(ge=0)
    incidents_24h: int = Field(ge=0)
    uptime_percentage: float = Field(ge=0, le=100)


class PublicHistoryEntry(BaseModel):
    """Public-safe historical data point."""

    model_config = ConfigDict(strict=True)

    timestamp: datetime
    total_agents: int = Field(ge=0)
    healthy_agents: int = Field(ge=0)
    total_messages: int = Field(ge=0)
    total_incidents: int = Field(ge=0)
