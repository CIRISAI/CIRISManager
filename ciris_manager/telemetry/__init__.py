"""
CIRISManager Telemetry System.

A comprehensive, type-safe telemetry collection system for infrastructure monitoring.
Designed with complete data isolation for secure public dashboards.

Principles:
- Integrity: Tamper-evident, type-safe data structures
- Transparency: Clear data flow, inspectable for accountability
- Non-Maleficence: Clean separation prevents data leaks
- Adaptive Coherence: Rigid contracts, flexible implementation

Key Features:
- 100% type-safe with Pydantic models (no Dict[str, Any])
- Clear separation of infrastructure vs agent concerns
- PostgreSQL/TimescaleDB for time-series storage
- Continuous collection with error recovery
- Public-safe API for external dashboards
- Automatic data retention and aggregation

Usage:
    from ciris_manager.telemetry import TelemetryService

    service = TelemetryService(
        agent_registry=registry,
        database_url="postgresql://user:pass@localhost/telemetry",
        collection_interval=60
    )

    await service.start()
"""

from ciris_manager.telemetry.service import TelemetryService, run_telemetry_service
from ciris_manager.telemetry.orchestrator import (
    TelemetryOrchestrator,
    ContinuousTelemetryCollector,
)
from ciris_manager.telemetry.storage import TelemetryStorageBackend
from ciris_manager.telemetry.schemas import (
    TelemetrySnapshot,
    SystemSummary,
    ContainerMetrics,
    AgentOperationalMetrics,
    DeploymentMetrics,
    VersionState,
    AgentVersionAdoption,
    PublicStatus,
    PublicHistoryEntry,
)

__all__ = [
    # Service
    "TelemetryService",
    "run_telemetry_service",
    # Orchestrator
    "TelemetryOrchestrator",
    "ContinuousTelemetryCollector",
    # Storage
    "TelemetryStorageBackend",
    # Core schemas
    "TelemetrySnapshot",
    "SystemSummary",
    "ContainerMetrics",
    "AgentOperationalMetrics",
    "DeploymentMetrics",
    "VersionState",
    "AgentVersionAdoption",
    # Public schemas
    "PublicStatus",
    "PublicHistoryEntry",
]

__version__ = "1.0.0"
