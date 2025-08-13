"""
Telemetry API for querying and accessing collected metrics.

Provides both internal and public-safe interfaces for telemetry data.
"""

import logging
from typing import List, Dict, Any, TypedDict
from fastapi import APIRouter, HTTPException, Query

from ciris_manager.telemetry.service import TelemetryService
from ciris_manager.telemetry.schemas import (
    SystemSummary,
    PublicStatus,
    PublicHistoryEntry,
    TelemetryQuery,
    TelemetryResponse,
)


class HealthResponse(TypedDict):
    status: str
    collection_status: str
    last_collection_time: str | None
    database_connected: bool
    collectors_enabled: Dict[str, bool]
    collection_interval: int
    storage_enabled: bool


class HistoryResponse(TypedDict):
    hours: int
    interval: str
    data: List[Dict[str, Any]]


class TriggerResponse(TypedDict):
    status: str
    message: str


class AgentMetricsResponse(TypedDict, total=False):
    agent_name: str
    hours: int
    current: Dict[str, Any]
    data: List[Any]


class ContainerMetricsResponse(TypedDict, total=False):
    container_name: str
    hours: int
    current: Dict[str, Any]
    data: List[Any]


logger = logging.getLogger(__name__)


class TelemetryAPI:
    """
    API interface for telemetry data.

    Provides endpoints for:
    - Current system status
    - Historical metrics
    - Public dashboard data
    - Agent-specific metrics
    """

    def __init__(self, telemetry_service: TelemetryService):
        """
        Initialize telemetry API.

        Args:
            telemetry_service: The telemetry service instance
        """
        self.service = telemetry_service
        self.router = APIRouter(prefix="/telemetry", tags=["telemetry"])
        self._setup_routes()

    def _setup_routes(self):
        """Set up API routes."""
        # Health check endpoint
        self.router.get("/health")(self.get_health)

        # Internal endpoints
        self.router.get("/status", response_model=SystemSummary)(self.get_status)
        self.router.get("/history")(self.get_history)
        self.router.post("/query", response_model=TelemetryResponse)(self.query_telemetry)
        self.router.get("/agent/{agent_name}")(self.get_agent_metrics)
        self.router.get("/container/{container_name}")(self.get_container_metrics)

        # Public endpoints (sanitized data only)
        self.router.get("/public/status", response_model=PublicStatus)(self.get_public_status)
        self.router.get("/public/history", response_model=List[PublicHistoryEntry])(
            self.get_public_history
        )

        # Management endpoints
        self.router.post("/collect")(self.trigger_collection)
        self.router.post("/cleanup")(self.cleanup_old_data)

    async def get_health(self) -> HealthResponse:
        """
        Get telemetry system health status.

        Returns:
            Health check response
        """
        try:
            # Check if service is running
            is_running = self.service.is_running

            # Get last collection time
            last_status = self.service.get_current_status()
            last_collection = last_status.timestamp if last_status else None

            # Check database connectivity if enabled
            db_healthy = False
            if self.service.has_storage and self.service.storage:
                try:
                    # Try to get latest summary from DB
                    await self.service.storage.get_latest_summary()
                    db_healthy = True
                except Exception:
                    pass

            return {
                "status": "healthy" if is_running else "degraded",
                "collection_status": "active" if is_running else "stopped",
                "last_collection_time": last_collection.isoformat() if last_collection else None,
                "database_connected": db_healthy,
                "collectors_enabled": {
                    "docker": True,
                    "agents": True,
                    "deployments": True,
                    "versions": True,
                },
                "collection_interval": self.service.collection_interval,
                "storage_enabled": self.service.has_storage,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise HTTPException(status_code=503, detail="Health check failed")

    async def get_status(self) -> SystemSummary:
        """
        Get current system status.

        Returns:
            Current system summary
        """
        status = self.service.get_current_status()

        if not status:
            # Try to collect once if no data available
            status = await self.service.collect_once()

        if not status:
            raise HTTPException(status_code=503, detail="No telemetry data available")

        return status

    async def get_history(
        self,
        hours: int = Query(default=24, ge=1, le=168),
        interval: str = Query(default="5m", regex="^(1m|5m|1h|1d)$"),
    ) -> HistoryResponse:
        """
        Get historical telemetry data.

        Args:
            hours: Number of hours to retrieve
            interval: Aggregation interval

        Returns:
            Historical data dictionary
        """
        if not self.service.has_storage:
            raise HTTPException(
                status_code=503, detail="Historical data not available (storage disabled)"
            )

        # Map interval to minutes
        interval_map = {"1m": 1, "5m": 5, "1h": 60, "1d": 1440}
        interval_minutes = interval_map[interval]

        try:
            # Get data from storage
            if not self.service.storage:
                return {"hours": hours, "interval": interval, "data": []}

            history = await self.service.storage.get_public_history(
                hours=hours, interval_minutes=interval_minutes
            )

            return {
                "hours": hours,
                "interval": interval,
                "data": [
                    {
                        "timestamp": entry.timestamp.isoformat(),
                        "total_agents": entry.total_agents,
                        "healthy_agents": entry.healthy_agents,
                        "messages": entry.total_messages,
                        "incidents": entry.total_incidents,
                    }
                    for entry in history
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve history")

    async def query_telemetry(self, query: TelemetryQuery) -> TelemetryResponse:
        """
        Query telemetry data with filters.

        Args:
            query: Query parameters

        Returns:
            Telemetry response with matching data
        """
        if not self.service.has_storage:
            raise HTTPException(status_code=503, detail="Query not available (storage disabled)")

        try:
            if not self.service.storage:
                raise HTTPException(status_code=503, detail="Storage backend not available")

            response = await self.service.storage.query_telemetry(query)
            return response
        except Exception as e:
            logger.error(f"Failed to query telemetry: {e}")
            raise HTTPException(status_code=500, detail="Query failed")

    async def get_agent_metrics(
        self, agent_name: str, hours: int = Query(default=24, ge=1, le=168)
    ) -> AgentMetricsResponse:
        """
        Get metrics for specific agent.

        Args:
            agent_name: Name of the agent
            hours: Number of hours to retrieve

        Returns:
            Agent metrics dictionary
        """
        if not self.service.has_storage:
            # Return current data only
            status = self.service.get_current_status()
            if not status:
                raise HTTPException(status_code=404, detail="No data available")

            # Find agent in current snapshot
            if self.service.continuous_collector:
                snapshot = self.service.continuous_collector.get_last_snapshot()
                if snapshot and len(snapshot) > 0:
                    for agent in snapshot[0].agents:
                        if agent.agent_name == agent_name:
                            return {
                                "agent_name": agent_name,
                                "current": {
                                    "version": agent.version,
                                    "cognitive_state": agent.cognitive_state.value,
                                    "api_healthy": agent.api_healthy,
                                    "uptime_seconds": agent.uptime_seconds,
                                    "messages_24h": agent.message_count_24h,
                                    "incidents_24h": agent.incident_count_24h,
                                },
                            }

            raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")

        # Get from storage
        # This would be implemented with specific queries
        return {"agent_name": agent_name, "hours": hours, "data": []}

    async def get_container_metrics(
        self, container_name: str, hours: int = Query(default=24, ge=1, le=168)
    ) -> ContainerMetricsResponse:
        """
        Get metrics for specific container.

        Args:
            container_name: Name of the container
            hours: Number of hours to retrieve

        Returns:
            Container metrics dictionary
        """
        if not self.service.has_storage:
            # Return current data only
            if self.service.continuous_collector:
                snapshot = self.service.continuous_collector.get_last_snapshot()
                if snapshot and len(snapshot) > 0:
                    for container in snapshot[0].containers:
                        if container.container_name == container_name:
                            return {
                                "container_name": container_name,
                                "current": {
                                    "status": container.status.value,
                                    "health": container.health.value,
                                    "cpu_percent": container.resources.cpu_percent,
                                    "memory_mb": container.resources.memory_mb,
                                    "restart_count": container.restart_count,
                                },
                            }

            raise HTTPException(status_code=404, detail=f"Container {container_name} not found")

        # Get from storage
        return {"container_name": container_name, "hours": hours, "data": []}

    async def get_public_status(self) -> PublicStatus:
        """
        Get public-safe system status.

        Returns:
            Sanitized public status
        """
        status = self.service.get_public_status()

        if not status:
            # Try to collect once
            await self.service.collect_once()
            status = self.service.get_public_status()

        if not status:
            # Return minimal data
            return PublicStatus(
                total_agents=0,
                healthy_percentage=0.0,
                messages_24h=0,
                incidents_24h=0,
                uptime_percentage=0.0,
            )

        return status

    async def get_public_history(
        self, hours: int = Query(default=24, ge=1, le=48)
    ) -> List[PublicHistoryEntry]:
        """
        Get public-safe historical data.

        Args:
            hours: Number of hours to retrieve (limited for public)

        Returns:
            List of public history entries
        """
        try:
            history = await self.service.get_public_history(hours=hours)
            return history if history else []
        except Exception as e:
            logger.error(f"Failed to get public history: {e}")
            return []

    async def trigger_collection(self) -> TriggerResponse:
        """
        Manually trigger telemetry collection.

        Returns:
            Status message
        """
        try:
            summary = await self.service.collect_once()
            if summary:
                return {
                    "status": "success",
                    "message": f"Collected metrics for {summary.agents_total} agents",
                }
            else:
                return {"status": "error", "message": "Collection failed"}
        except Exception as e:
            logger.error(f"Manual collection failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def cleanup_old_data(self, days: int = Query(default=7, ge=1, le=30)) -> TriggerResponse:
        """
        Clean up old telemetry data.

        Args:
            days: Number of days to retain

        Returns:
            Status message
        """
        if not self.service.has_storage:
            raise HTTPException(status_code=503, detail="Cleanup not available (storage disabled)")

        try:
            await self.service.cleanup_old_data(days=days)
            return {"status": "success", "message": f"Cleaned up data older than {days} days"}
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))


def create_telemetry_router(telemetry_service: TelemetryService) -> APIRouter:
    """
    Create FastAPI router for telemetry endpoints.

    Args:
        telemetry_service: The telemetry service instance

    Returns:
        Configured API router
    """
    api = TelemetryAPI(telemetry_service)
    return api.router
