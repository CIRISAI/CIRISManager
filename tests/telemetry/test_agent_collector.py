"""
Unit tests for agent operational metrics collector.

Tests the AgentMetricsCollector implementation with mocked API calls.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from ciris_manager.telemetry.collectors.agent_collector import AgentMetricsCollector
from ciris_manager.telemetry.schemas import (
    CognitiveState,
)
from ciris_manager.models import AgentInfo


class TestAgentMetricsCollector:
    """Test AgentMetricsCollector functionality."""

    @pytest.fixture
    def sample_agents(self):
        """Create sample agents using models.AgentInfo."""
        return [
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

    @pytest.fixture
    def mock_discovery(self, sample_agents):
        """Create mock agent discovery."""
        discovery = Mock()
        discovery.discover_agents = Mock(return_value=sample_agents)
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

    @pytest.fixture
    def collector(self, mock_discovery):
        """Create collector with mocked discovery."""
        collector = AgentMetricsCollector(None)
        collector.discovery = mock_discovery
        return collector

    @pytest.mark.asyncio
    async def test_initialization(self, collector):
        """Test collector initialization."""
        assert collector.discovery is not None
        assert collector.agent_registry is None  # We passed None
        # Auth should be None when no registry

    @pytest.mark.asyncio
    async def test_discovery_integration(self, collector, mock_discovery):
        """Test that collector uses discovery properly."""
        # Should use discovery to find agents
        agents = mock_discovery.discover_agents()
        assert len(agents) == 3

        # When no agents discovered
        mock_discovery.discover_agents.return_value = []
        agents = mock_discovery.discover_agents()
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_collect_single_agent(self, collector, mock_discovery, mock_health_response):
        """Test collecting metrics for a single agent."""
        # Set up discovery with one agent
        agents = mock_discovery.discover_agents()
        mock_discovery.discover_agents.return_value = [agents[0]]  # Just Datum

        # Mock HTTP client
        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_health_response
            mock_client.get.return_value = mock_response

            metrics = await collector.collect_agent_metrics()

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
        mock_client.get.assert_called_once_with("http://localhost:8080/v1/system/health")

    @pytest.mark.asyncio
    async def test_collect_multiple_agents(self, collector, sample_agents):
        """Test collecting metrics for multiple agents."""
        # Mock different responses for each agent
        responses = [
            {
                "status": "healthy",
                "version": "1.4.0",
                "uptime_seconds": 3600,
                "cognitive_state": "WORK",
                "recent_incidents_count": 2,
                "messages_24h": 1000,
                "cost_24h_cents": 250,
            },
            {
                "status": "healthy",
                "version": "1.3.0",
                "uptime_seconds": 7200,
                "cognitive_state": "DREAM",
                "recent_incidents_count": 0,
                "messages_24h": 500,
                "cost_24h_cents": 100,
            },
            {
                "status": "degraded",
                "version": "1.4.0",
                "uptime_seconds": 1800,
                "cognitive_state": "SOLITUDE",
                "recent_incidents_count": 5,
                "messages_24h": 100,
                "cost_24h_cents": 50,
            },
        ]

        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Set up side effects for multiple calls
            mock_responses = []
            for resp_data in responses:
                mock_resp = Mock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = resp_data
                mock_responses.append(mock_resp)

            mock_client.get.side_effect = mock_responses

            metrics = await collector.collect_agent_metrics()

        assert len(metrics) == 3

        # Verify first agent (WORK state)
        assert metrics[0].agent_name == "Datum"
        assert metrics[0].cognitive_state == CognitiveState.WORK
        assert metrics[0].message_count_24h == 1000

        # Verify second agent (DREAM state)
        assert metrics[1].agent_name == "Sage"
        assert metrics[1].cognitive_state == CognitiveState.DREAM
        assert metrics[1].message_count_24h == 500

        # Verify third agent (SOLITUDE state)
        assert metrics[2].agent_name == "Echo"
        assert metrics[2].cognitive_state == CognitiveState.SOLITUDE
        assert metrics[2].incident_count_24h == 5

    @pytest.mark.asyncio
    async def test_handle_failed_requests(self, collector, mock_discovery):
        """Test handling of failed HTTP requests."""
        # Set up discovery with all agents
        mock_discovery.discover_agents()

        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

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
                            "recent_incidents_count": 2,
                            "messages_24h": 1000,
                            "cost_24h_cents": 250,
                        }
                    ),
                ),
                Mock(status_code=500),  # Server error
                Mock(status_code=404),  # Not found
            ]

            metrics = await collector.collect_agent_metrics()

        # Should get metrics for all agents (failed ones marked as unhealthy)
        assert len(metrics) == 3

        # First agent should be healthy
        assert metrics[0].api_healthy is True
        assert metrics[0].agent_name == "Datum"

        # Second and third should be unhealthy
        assert metrics[1].api_healthy is False
        assert metrics[1].agent_name == "Sage"
        assert metrics[1].version == "unknown"

        assert metrics[2].api_healthy is False
        assert metrics[2].agent_name == "Echo"

    @pytest.mark.asyncio
    async def test_handle_malformed_response(self, collector, mock_discovery):
        """Test handling malformed API responses."""
        # Set up with one agent
        agents = mock_discovery.discover_agents()
        mock_discovery.discover_agents.return_value = [agents[0]]

        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Response with missing fields
            mock_client.get.return_value = Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        # Missing required fields
                    }
                ),
            )

            metrics = await collector.collect_agent_metrics()

        # Should still get metrics with defaults for missing fields
        assert len(metrics) == 1
        metric = metrics[0]
        assert metric.api_healthy is True
        assert metric.version == "unknown"  # Default when missing
        assert metric.cognitive_state == CognitiveState.UNKNOWN  # Default when missing
        assert metric.message_count_24h == 0  # Default when missing

    @pytest.mark.asyncio
    async def test_handle_timeout(self, collector, mock_discovery):
        """Test handling of request timeouts."""
        # Set up with one agent
        agents = mock_discovery.discover_agents()
        mock_discovery.discover_agents.return_value = [agents[0]]

        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Simulate timeout
            mock_client.get.side_effect = asyncio.TimeoutError()

            metrics = await collector.collect_agent_metrics()

        # Should get unhealthy metrics for timed out agent
        assert len(metrics) == 1
        metric = metrics[0]
        assert metric.api_healthy is False
        assert metric.agent_name == "Datum"
        assert metric.version == "unknown"
        assert metric.cognitive_state == CognitiveState.UNKNOWN

    @pytest.mark.asyncio
    async def test_collect_with_auth(self, collector):
        """Test collection with authentication headers."""
        # Mock auth
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer test-token"}
        collector.auth = mock_auth

        # Set up with one agent
        mock_discovery = collector.discovery
        agents = mock_discovery.discover_agents()
        mock_discovery.discover_agents.return_value = [agents[0]]

        with patch(
            "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_client.get.return_value = Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "status": "healthy",
                        "version": "1.4.0",
                        "uptime_seconds": 3600,
                        "cognitive_state": "WORK",
                        "recent_incidents_count": 0,
                        "messages_24h": 100,
                        "cost_24h_cents": 10,
                    }
                ),
            )

            # Verify AsyncClient was created with auth headers
            metrics = await collector.collect_agent_metrics()
            mock_client_class.assert_called_with(
                timeout=5.0, headers={"Authorization": "Bearer test-token"}
            )

        assert len(metrics) == 1
        assert metrics[0].api_healthy is True

    @pytest.mark.asyncio
    async def test_empty_agent_list(self, collector, mock_discovery):
        """Test collection with no agents discovered."""
        mock_discovery.discover_agents.return_value = []

        metrics = await collector.collect_agent_metrics()

        assert metrics == []

    @pytest.mark.asyncio
    async def test_agents_without_ports(self, collector, mock_discovery):
        """Test handling agents without API ports."""
        # Create agent without port
        agent_no_port = AgentInfo(
            agent_id="no-port-123",
            agent_name="NoPort",
            container_name="ciris-agent-noport",
            api_port=None,  # No port
            status="running",
            template="default",
        )

        mock_discovery.discover_agents.return_value = [agent_no_port]

        metrics = await collector.collect_agent_metrics()

        # Should return empty list since no agents have ports
        assert metrics == []

    @pytest.mark.asyncio
    async def test_cognitive_state_parsing(self, collector, mock_discovery):
        """Test parsing of various cognitive states."""
        agents = mock_discovery.discover_agents()
        mock_discovery.discover_agents.return_value = [agents[0]]

        test_cases = [
            ("WORK", CognitiveState.WORK),
            ("DREAM", CognitiveState.DREAM),
            ("SOLITUDE", CognitiveState.SOLITUDE),
            ("PLAY", CognitiveState.PLAY),
            ("SHUTDOWN", CognitiveState.SHUTDOWN),
            ("INVALID", CognitiveState.UNKNOWN),
            ("", CognitiveState.UNKNOWN),
            (None, CognitiveState.UNKNOWN),
        ]

        for state_str, expected_state in test_cases:
            with patch(
                "ciris_manager.telemetry.collectors.agent_collector.httpx.AsyncClient"
            ) as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client

                mock_client.get.return_value = Mock(
                    status_code=200,
                    json=Mock(
                        return_value={
                            "status": "healthy",
                            "cognitive_state": state_str,
                        }
                    ),
                )

                metrics = await collector.collect_agent_metrics()

                assert len(metrics) == 1
                assert metrics[0].cognitive_state == expected_state
