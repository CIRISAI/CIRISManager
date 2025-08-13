"""
Unit tests for agent operational metrics collector.

Tests the AgentMetricsCollector implementation with mocked API calls.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import httpx

from ciris_manager.telemetry.collectors.agent_collector import AgentMetricsCollector
from ciris_manager.telemetry.schemas import (
    CognitiveState,
)
from ciris_manager.models import AgentInfo


class TestAgentMetricsCollector:
    """Test AgentMetricsCollector functionality."""

    @pytest.fixture
    def mock_discovery(self):
        """Create mock agent discovery."""
        discovery = Mock()

        # Create sample agents using models.AgentInfo
        agents = [
            AgentInfo(
                agent_id="datum-abc123",
                agent_name="Datum",
                container_name="ciris-agent-datum",
                api_port=8080,
                status="running",
                version="1.4.0",
                template="default",
                oauth_status="configured",
                health="healthy",
            ),
            AgentInfo(
                agent_id="sage-def456",
                agent_name="Sage",
                container_name="ciris-agent-sage",
                api_port=8081,
                status="running",
                version="1.3.0",
                template="default",
                health="healthy",
            ),
            AgentInfo(
                agent_id="echo-ghi789",
                agent_name="Echo",
                container_name="ciris-agent-echo",
                api_port=8082,
                status="running",
                version="1.4.0",
                template="default",
                oauth_status="configured",
                health="healthy",
            ),
        ]

        discovery.discover_agents.return_value = agents
        return discovery

    @pytest.fixture
    def mock_health_response(self):
        """Create mock health check response."""
        return {
            "status": "healthy",
            "version": "1.4.0",
            "uptime_seconds": 3600,
            "cognitive_state": "WORK",
            "recent_incidents_count": 2,
            "messages_24h": 1000,
            "cost_24h_cents": 250,
        }

    @pytest.mark.asyncio
    async def test_initialization(self, mock_discovery):
        """Test collector initialization."""
        collector = AgentMetricsCollector(None)
        collector.discovery = mock_discovery

        assert collector.name == "AgentMetricsCollector"
        assert collector.timeout_seconds == 10
        assert collector.discovery == mock_discovery

    @pytest.mark.asyncio
    async def test_is_available(self, mock_discovery):
        """Test availability check."""
        collector = AgentMetricsCollector(None)
        collector.discovery = mock_discovery

        # Should be available if discovery has agents
        is_available = await collector.is_available()
        assert is_available is True

        # Not available if no agents
        mock_discovery.discover_agents.return_value = []
        is_available = await collector.is_available()
        assert is_available is False

    @pytest.mark.asyncio
    async def test_collect_single_agent(self, mock_discovery, mock_health_response):
        """Test collecting metrics for a single agent."""
        # Set up discovery with one agent
        agents = mock_discovery.discover_agents.return_value
        mock_discovery.discover_agents.return_value = [agents[0]]  # Just Datum

        collector = AgentMetricsCollector(None)
        collector.discovery = mock_discovery

        # Mock HTTP client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_health_response
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        assert len(metrics) == 1
        metric = metrics[0]

        # Verify agent info
        assert metric.agent_id == "datum-abc123"
        assert metric.agent_name == "Datum"
        assert metric.version == "1.4.0"
        assert metric.api_port == 8080

        # Verify operational metrics
        assert metric.cognitive_state == CognitiveState.WORK
        assert metric.api_healthy is True
        assert metric.api_response_time_ms > 0  # Calculated based on actual request time
        assert metric.uptime_seconds == 3600
        assert metric.incident_count_24h == 2
        assert metric.message_count_24h == 1000
        assert metric.cost_cents_24h == 250

        # Verify OAuth info
        assert metric.oauth_configured is True
        assert metric.oauth_providers == []  # Collector doesn't fetch providers list

        # Verify API was called correctly
        mock_client.get.assert_called_once_with(
            "http://localhost:8080/v1/system/health", timeout=5.0
        )

    @pytest.mark.asyncio
    async def test_collect_multiple_agents(self, mock_agent_registry):
        """Test collecting metrics for multiple agents."""
        collector = AgentMetricsCollector(mock_agent_registry)

        # Mock different responses for each agent
        responses = [
            {
                "status": "healthy",
                "version": "1.4.0",
                "uptime_seconds": 3600,
                "cognitive_state": "WORK",
                "metrics": {
                    "messages_24h": 1000,
                    "incidents_24h": 2,
                    "cost_cents_24h": 250,
                    "response_time_ms": 150,
                },
            },
            {
                "status": "healthy",
                "version": "1.3.0",
                "uptime_seconds": 7200,
                "cognitive_state": "DREAM",
                "metrics": {
                    "messages_24h": 500,
                    "incidents_24h": 0,
                    "cost_cents_24h": 100,
                    "response_time_ms": 200,
                },
            },
            {
                "status": "degraded",
                "version": "1.4.0",
                "uptime_seconds": 1800,
                "cognitive_state": "SOLITUDE",
                "metrics": {
                    "messages_24h": 100,
                    "incidents_24h": 5,
                    "cost_cents_24h": 50,
                    "response_time_ms": 500,
                },
            },
        ]

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [
            Mock(status_code=200, json=Mock(return_value=resp)) for resp in responses
        ]

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        assert len(metrics) == 3

        # Verify each agent's metrics
        datum = next(m for m in metrics if m.agent_name == "Datum")
        assert datum.cognitive_state == CognitiveState.WORK
        assert datum.message_count_24h == 1000

        sage = next(m for m in metrics if m.agent_name == "Sage")
        assert sage.cognitive_state == CognitiveState.DREAM
        assert sage.uptime_seconds == 7200

        echo = next(m for m in metrics if m.agent_name == "Echo")
        assert echo.cognitive_state == CognitiveState.SOLITUDE
        assert echo.api_healthy is False  # degraded status

    @pytest.mark.asyncio
    async def test_handle_api_timeout(self, mock_agent_registry):
        """Test handling API timeout."""
        collector = AgentMetricsCollector(mock_agent_registry)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("Request timeout")

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        # Should return empty list on timeout
        assert metrics == []

    @pytest.mark.asyncio
    async def test_handle_api_error(self, mock_agent_registry):
        """Test handling API errors."""
        collector = AgentMetricsCollector(mock_agent_registry)

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Mix of successful and failed responses
        mock_client.get.side_effect = [
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        "version": "1.4.0",
                        "uptime_seconds": 3600,
                        "cognitive_state": "WORK",
                        "metrics": {
                            "messages_24h": 1000,
                            "incidents_24h": 2,
                            "cost_cents_24h": 250,
                            "response_time_ms": 150,
                        },
                    }
                ),
            ),
            Mock(status_code=500),  # Server error
            Mock(status_code=404),  # Not found
        ]

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        # Should only get metrics for successful responses
        assert len(metrics) == 1
        assert metrics[0].agent_name == "Datum"

    @pytest.mark.asyncio
    async def test_handle_malformed_response(self, mock_agent_registry):
        """Test handling malformed API responses."""
        collector = AgentMetricsCollector(mock_agent_registry)

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Responses with missing fields
        mock_client.get.side_effect = [
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        # Missing required fields
                    }
                ),
            ),
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        "version": "1.3.0",
                        "uptime_seconds": 7200,
                        "cognitive_state": "INVALID_STATE",  # Invalid enum
                        "metrics": {},
                    }
                ),
            ),
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        "version": "1.4.0",
                        "uptime_seconds": 1800,
                        "cognitive_state": "PLAY",
                        "metrics": {
                            "messages_24h": 100,
                            "incidents_24h": 0,
                            "cost_cents_24h": 10,
                            "response_time_ms": 100,
                        },
                    }
                ),
            ),
        ]

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        # Should only get valid metrics
        assert len(metrics) == 1
        assert metrics[0].agent_name == "Echo"
        assert metrics[0].cognitive_state == CognitiveState.PLAY

    @pytest.mark.asyncio
    async def test_cognitive_state_mapping(self, mock_agent_registry):
        """Test mapping of cognitive states."""
        collector = AgentMetricsCollector(mock_agent_registry)

        # Test all valid cognitive states
        states = ["WAKEUP", "WORK", "PLAY", "SOLITUDE", "DREAM", "SHUTDOWN"]

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        responses = []

        for state in states:
            responses.append(
                Mock(
                    status_code=200,
                    json=Mock(
                        return_value={
                            "status": "healthy",
                            "version": "1.0.0",
                            "uptime_seconds": 100,
                            "cognitive_state": state,
                            "metrics": {
                                "messages_24h": 0,
                                "incidents_24h": 0,
                                "cost_cents_24h": 0,
                                "response_time_ms": 100,
                            },
                        }
                    ),
                )
            )

        # Only test first 3 agents
        mock_agent_registry.get_all_agents.return_value = dict(
            list(mock_agent_registry.get_all_agents.return_value.items())[:3]
        )

        # Test first 3 states
        for i in range(3):
            mock_client.get.side_effect = [responses[i]] * 3

            with patch("httpx.AsyncClient", return_value=mock_client):
                metrics = await collector.collect()

            if i == 0:
                assert metrics[0].cognitive_state == CognitiveState.WAKEUP
            elif i == 1:
                assert metrics[0].cognitive_state == CognitiveState.WORK
            elif i == 2:
                assert metrics[0].cognitive_state == CognitiveState.PLAY

    @pytest.mark.asyncio
    async def test_unknown_cognitive_state(self, mock_agent_registry):
        """Test handling unknown cognitive state."""
        # Single agent for simplicity
        mock_agent_registry.get_all_agents.return_value = {
            "datum": mock_agent_registry.get_all_agents.return_value["datum"]
        }

        collector = AgentMetricsCollector(mock_agent_registry)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "status": "healthy",
                    "version": "1.0.0",
                    "uptime_seconds": 100,
                    "cognitive_state": "UNKNOWN_STATE",
                    "metrics": {
                        "messages_24h": 0,
                        "incidents_24h": 0,
                        "cost_cents_24h": 0,
                        "response_time_ms": 100,
                    },
                }
            ),
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            metrics = await collector.collect()

        assert len(metrics) == 1
        assert metrics[0].cognitive_state == CognitiveState.UNKNOWN

    @pytest.mark.asyncio
    async def test_parallel_collection(self, mock_agent_registry):
        """Test that agent health checks are made in parallel."""
        collector = AgentMetricsCollector(mock_agent_registry)

        call_times = []

        async def mock_get(url, timeout):
            """Track when each call is made."""
            call_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.1)  # Simulate API delay
            return Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        "version": "1.0.0",
                        "uptime_seconds": 100,
                        "cognitive_state": "WORK",
                        "metrics": {
                            "messages_24h": 0,
                            "incidents_24h": 0,
                            "cost_cents_24h": 0,
                            "response_time_ms": 100,
                        },
                    }
                ),
            )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            start = asyncio.get_event_loop().time()
            metrics = await collector.collect()
            duration = asyncio.get_event_loop().time() - start

        assert len(metrics) == 3

        # If sequential, would take 0.3s (3 * 0.1s)
        # If parallel, should take ~0.1s
        assert duration < 0.2  # Allow some overhead

        # All calls should start at nearly the same time
        if call_times:
            time_spread = max(call_times) - min(call_times)
            assert time_spread < 0.05  # Should all start within 50ms
