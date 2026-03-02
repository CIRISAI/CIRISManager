"""
Unit tests for AgentRegistry.
"""

import pytest
import tempfile
import json
from pathlib import Path
from ciris_manager.agent_registry import AgentRegistry, RegisteredAgent


class TestRegisteredAgent:
    """Test cases for RegisteredAgent class."""

    def test_initialization(self):
        """Test AgentInfo initialization."""
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
        )

        assert agent.agent_id == "agent-test"
        assert agent.name == "Test"
        assert agent.port == 8080
        assert agent.template == "scout"
        assert agent.compose_file == "/path/to/compose.yml"
        assert agent.created_at is not None
        assert "T" in agent.created_at  # ISO format
        assert "+00:00" in agent.created_at or agent.created_at.endswith("Z")  # UTC timezone

    def test_initialization_with_created_at(self):
        """Test AgentInfo initialization with created_at."""
        created_at = "2025-01-21T10:00:00Z"
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            created_at=created_at,
        )

        assert agent.created_at == created_at

    def test_to_dict(self):
        """Test converting AgentInfo to dict."""
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
        )

        data = agent.to_dict()
        assert data["name"] == "Test"
        assert data["port"] == 8080
        assert data["template"] == "scout"
        assert data["compose_file"] == "/path/to/compose.yml"
        assert "created_at" in data
        # agent_id is included when agent_id contains dashes (to avoid parsing ambiguity)
        assert data["agent_id"] == "agent-test"
        assert data["server_id"] == "main"  # Default server

    def test_server_id_default(self):
        """Test that server_id defaults to 'main'."""
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
        )

        assert agent.server_id == "main"

    def test_server_id_explicit(self):
        """Test setting explicit server_id."""
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            server_id="scout",
        )

        assert agent.server_id == "scout"

    def test_server_id_in_to_dict(self):
        """Test server_id is included in dict."""
        agent = RegisteredAgent(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            server_id="scout",
        )

        data = agent.to_dict()
        assert data["server_id"] == "scout"

    def test_from_dict(self):
        """Test creating AgentInfo from dict."""
        data = {
            "name": "Test",
            "port": 8080,
            "template": "scout",
            "compose_file": "/path/to/compose.yml",
            "created_at": "2025-01-21T10:00:00Z",
        }

        agent = RegisteredAgent.from_dict("agent-test", data)
        assert agent.agent_id == "agent-test"
        assert agent.name == "Test"
        assert agent.port == 8080
        assert agent.template == "scout"
        assert agent.compose_file == "/path/to/compose.yml"
        assert agent.created_at == "2025-01-21T10:00:00Z"
        assert agent.server_id == "main"  # Default when not in dict

    def test_from_dict_with_server_id(self):
        """Test creating AgentInfo from dict with server_id."""
        data = {
            "name": "Test",
            "port": 8080,
            "template": "scout",
            "compose_file": "/path/to/compose.yml",
            "created_at": "2025-01-21T10:00:00Z",
            "server_id": "scout",
        }

        agent = RegisteredAgent.from_dict("agent-test", data)
        assert agent.agent_id == "agent-test"
        assert agent.server_id == "scout"


class TestAgentRegistry:
    """Test cases for AgentRegistry."""

    @pytest.fixture
    def temp_metadata_path(self):
        """Create temporary metadata file path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    @pytest.fixture
    def registry(self, temp_metadata_path):
        """Create AgentRegistry instance."""
        return AgentRegistry(temp_metadata_path)

    def test_initialization(self, registry):
        """Test AgentRegistry initialization."""
        assert len(registry.agents) == 0
        assert registry.metadata_path.exists()
        assert registry.metadata_path.parent.exists()

    def test_register_agent(self, registry):
        """Test agent registration."""
        agent = registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        assert agent.agent_id == "agent-scout"
        assert agent.name == "Scout"
        assert agent.port == 8081
        assert agent.template == "scout"
        assert agent.compose_file == "/etc/agents/scout/docker-compose.yml"
        assert agent.server_id == "main"  # Default server

        # Verify in registry (now uses composite key)
        composite_key = "agent-scout-main"  # agent_id-server_id format
        assert composite_key in registry.agents
        assert registry.agents[composite_key] == agent

        # Verify metadata saved
        assert registry.metadata_path.exists()

    def test_register_agent_with_server_id(self, registry):
        """Test agent registration with explicit server_id."""
        agent = registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
            server_id="scout",
        )

        assert agent.agent_id == "agent-scout"
        assert agent.server_id == "scout"

        # Verify in registry (now uses composite key)
        composite_key = "agent-scout-scout"  # agent_id-server_id format
        assert composite_key in registry.agents
        assert registry.agents[composite_key].server_id == "scout"

    def test_unregister_agent(self, registry):
        """Test agent unregistration."""
        # Register first
        registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        # Unregister
        removed = registry.unregister_agent("agent-scout")
        assert removed is not None
        assert removed.agent_id == "agent-scout"
        assert "agent-scout" not in registry.agents

        # Unregister non-existent
        removed = registry.unregister_agent("agent-nonexistent")
        assert removed is None

    def test_get_agent(self, registry):
        """Test getting agent by ID."""
        # Register
        original = registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        # Get existing
        agent = registry.get_agent("agent-scout")
        assert agent == original

        # Get non-existent
        agent = registry.get_agent("agent-nonexistent")
        assert agent is None

    def test_get_agent_by_name(self, registry):
        """Test getting agent by name."""
        # Register
        original = registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        # Get by exact name
        agent = registry.get_agent_by_name("Scout")
        assert agent == original

        # Get by lowercase name
        agent = registry.get_agent_by_name("scout")
        assert agent == original

        # Get non-existent
        agent = registry.get_agent_by_name("Unknown")
        assert agent is None

    def test_list_agents(self, registry):
        """Test listing agents."""
        # Initially empty
        agents = registry.list_agents()
        assert len(agents) == 0

        # Register multiple
        agent1 = registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        agent2 = registry.register_agent(
            agent_id="agent-sage",
            name="Sage",
            port=8082,
            template="sage",
            compose_file="/etc/agents/sage/docker-compose.yml",
        )

        # List
        agents = registry.list_agents()
        assert len(agents) == 2
        assert agent1 in agents
        assert agent2 in agents

    def test_get_allocated_ports(self, registry):
        """Test getting allocated ports mapping."""
        # Register agents
        registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        registry.register_agent(
            agent_id="agent-sage",
            name="Sage",
            port=8082,
            template="sage",
            compose_file="/etc/agents/sage/docker-compose.yml",
        )

        # Get ports (now uses composite keys)
        ports = registry.get_allocated_ports()
        assert ports == {"agent-scout-main": 8081, "agent-sage-main": 8082}

    def test_persistence(self, temp_metadata_path):
        """Test metadata persistence across instances."""
        # Create and register
        registry1 = AgentRegistry(temp_metadata_path)
        registry1.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        # Create new instance
        registry2 = AgentRegistry(temp_metadata_path)

        # Should have loaded data
        assert len(registry2.agents) == 1
        agent = registry2.get_agent("agent-scout")
        assert agent is not None
        assert agent.name == "Scout"
        assert agent.port == 8081

    def test_metadata_format(self, registry, temp_metadata_path):
        """Test metadata file format."""
        # Register agent
        registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml",
        )

        # Read metadata
        with open(temp_metadata_path, "r") as f:
            data = json.load(f)

        assert "version" in data
        assert data["version"] == "1.0"
        assert "updated_at" in data
        assert "agents" in data

        # Now uses composite key format
        composite_key = "agent-scout-main"
        assert composite_key in data["agents"]

        agent_data = data["agents"][composite_key]
        assert agent_data["name"] == "Scout"
        assert agent_data["port"] == 8081
        assert agent_data["template"] == "scout"
        assert agent_data["compose_file"] == "/etc/agents/scout/docker-compose.yml"
        assert "created_at" in agent_data

    def test_concurrent_registration(self, registry):
        """Test thread safety of registration."""
        import threading

        errors = []

        def register_agent(agent_id, name, port):
            try:
                registry.register_agent(
                    agent_id=agent_id,
                    name=name,
                    port=port,
                    template="scout",
                    compose_file=f"/etc/agents/{name.lower()}/docker-compose.yml",
                )
            except Exception as e:
                errors.append(e)

        # Create threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=register_agent, args=(f"agent-{i}", f"Agent{i}", 8080 + i))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Verify
        assert len(errors) == 0
        assert len(registry.agents) == 5

        # Verify metadata integrity
        with open(registry.metadata_path, "r") as f:
            data = json.load(f)
            assert len(data["agents"]) == 5

    def test_occurrence_id_initialization(self):
        """Test RegisteredAgent initialization with occurrence_id."""
        agent = RegisteredAgent(
            agent_id="scout-abc123",
            name="Scout",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        assert agent.occurrence_id == "scout_lb_1"
        assert agent.agent_id == "scout-abc123"
        assert agent.server_id == "main"

    def test_occurrence_id_in_to_dict(self):
        """Test occurrence_id is included in dict."""
        agent = RegisteredAgent(
            agent_id="scout-abc123",
            name="Scout",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
        )

        data = agent.to_dict()
        assert data["occurrence_id"] == "scout_lb_1"

    def test_occurrence_id_from_dict(self):
        """Test creating AgentInfo from dict with occurrence_id."""
        data = {
            "name": "Scout",
            "port": 8080,
            "template": "scout",
            "compose_file": "/path/to/compose.yml",
            "occurrence_id": "scout_lb_1",
        }

        agent = RegisteredAgent.from_dict("scout-abc123", data)
        assert agent.occurrence_id == "scout_lb_1"


class TestAgentRegistryCompositeKeys:
    """Test cases for AgentRegistry composite key functionality."""

    @pytest.fixture
    def temp_metadata_path(self):
        """Create temporary metadata file path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

    @pytest.fixture
    def registry(self, temp_metadata_path):
        """Create AgentRegistry instance."""
        return AgentRegistry(temp_metadata_path)

    def test_composite_key_make_key(self, registry):
        """Test _make_key helper for composite keys."""
        # With occurrence_id
        key = registry._make_key("scout-abc123", "scout_lb_1", "main")
        assert key == "scout-abc123-scout_lb_1-main"

        # Without occurrence_id (backward compatibility)
        key = registry._make_key("scout-abc123", None, "main")
        assert key == "scout-abc123-main"

    def test_composite_key_parse_key(self, registry):
        """Test _parse_key helper for composite keys.

        Note: _parse_key has ambiguity with agent_ids containing dashes.
        It works correctly in _load_metadata() where metadata provides context.
        """
        # With occurrence_id - works when occurrence_id doesn't look like server_id
        agent_id, occurrence_id, server_id = registry._parse_key("scout-scout_lb_1-main")
        assert agent_id == "scout"
        assert occurrence_id == "scout_lb_1"
        assert server_id == "main"

        # Simple case: no dashes in agent_id
        agent_id, occurrence_id, server_id = registry._parse_key("datum-main")
        assert agent_id == "datum"
        assert occurrence_id is None
        assert server_id == "main"

        # Old format (single part, no server_id)
        agent_id, occurrence_id, server_id = registry._parse_key("datum")
        assert agent_id == "datum"
        assert occurrence_id is None
        assert server_id == "main"

    def test_register_agent_with_occurrence_id(self, registry):
        """Test registering agent with occurrence_id."""
        agent = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        assert agent.occurrence_id == "scout_lb_1"
        assert agent.agent_id == "scout-abc123"

        # Verify stored with composite key
        composite_key = "scout-abc123-scout_lb_1-main"
        assert composite_key in registry.agents
        assert registry.agents[composite_key] == agent

    def test_register_multiple_instances_same_agent_id(self, registry):
        """Test registering multiple instances with same agent_id but different occurrence_ids."""
        # Register first instance
        agent1 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose1.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        # Register second instance with same agent_id but different occurrence_id
        agent2 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose2.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )

        # Register third instance on different server
        agent3 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 3",
            port=8082,
            template="scout",
            compose_file="/path/to/compose3.yml",
            occurrence_id="scout_lb_3",
            server_id="scout",
        )

        # Verify all registered
        assert len(registry.agents) == 3
        assert agent1.occurrence_id == "scout_lb_1"
        assert agent2.occurrence_id == "scout_lb_2"
        assert agent3.occurrence_id == "scout_lb_3"

    def test_get_agent_with_composite_key(self, registry):
        """Test getting agent by composite key."""
        # Register instances
        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )

        # Get by full composite key
        agent1 = registry.get_agent("scout-abc123", occurrence_id="scout_lb_1", server_id="main")
        assert agent1 is not None
        assert agent1.occurrence_id == "scout_lb_1"
        assert agent1.port == 8080

        # Get by different composite key
        agent2 = registry.get_agent("scout-abc123", occurrence_id="scout_lb_2", server_id="main")
        assert agent2 is not None
        assert agent2.occurrence_id == "scout_lb_2"
        assert agent2.port == 8081

        # Get non-existent composite key
        agent3 = registry.get_agent("scout-abc123", occurrence_id="scout_lb_99", server_id="main")
        assert agent3 is None

    def test_get_agents_by_agent_id(self, registry):
        """Test getting all instances with the same agent_id."""
        # Register multiple instances
        agent1 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        agent2 = registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )

        # Register different agent
        agent3 = registry.register_agent(
            agent_id="sage-xyz789",
            name="Sage",
            port=8082,
            template="sage",
            compose_file="/path/to/compose.yml",
        )

        # Get all scout instances
        scout_instances = registry.get_agents_by_agent_id("scout-abc123")
        assert len(scout_instances) == 2
        assert agent1 in scout_instances
        assert agent2 in scout_instances
        assert agent3 not in scout_instances

        # Get sage instances (only one)
        sage_instances = registry.get_agents_by_agent_id("sage-xyz789")
        assert len(sage_instances) == 1
        assert agent3 in sage_instances

    def test_unregister_agent_with_composite_key(self, registry):
        """Test unregistering agent with composite key."""
        # Register instances
        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 2",
            port=8081,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_2",
            server_id="main",
        )

        # Unregister first instance
        removed = registry.unregister_agent(
            "scout-abc123", occurrence_id="scout_lb_1", server_id="main"
        )
        assert removed is not None
        assert removed.occurrence_id == "scout_lb_1"

        # Verify only second instance remains
        remaining = registry.get_agents_by_agent_id("scout-abc123")
        assert len(remaining) == 1
        assert remaining[0].occurrence_id == "scout_lb_2"

    def test_update_agent_state_with_composite_key(self, registry):
        """Test updating agent state with composite key."""
        # Register instance
        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        # Update state
        success = registry.update_agent_state(
            "scout-abc123",
            version="1.2.0",
            cognitive_state="WORK",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        assert success is True

        # Verify state updated (version is in current_version, not metadata)
        agent = registry.get_agent("scout-abc123", occurrence_id="scout_lb_1", server_id="main")
        assert agent.current_version == "1.2.0"
        # Cognitive state is not stored in metadata, just tracked via version_transitions
        assert len(agent.version_transitions) > 0

    def test_set_deployment_with_composite_key(self, registry):
        """Test setting deployment with composite key."""
        # Register instance
        registry.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        # Set deployment
        success = registry.set_deployment(
            "scout-abc123",
            "CIRIS_DISCORD_PILOT",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        assert success is True

        # Verify deployment set
        agent = registry.get_agent("scout-abc123", occurrence_id="scout_lb_1", server_id="main")
        assert agent.metadata.get("deployment") == "CIRIS_DISCORD_PILOT"

    def test_composite_key_persistence(self, temp_metadata_path):
        """Test composite keys persist across registry instances."""
        # Create and register with occurrence_id
        registry1 = AgentRegistry(temp_metadata_path)
        agent1 = registry1.register_agent(
            agent_id="scout-abc123",
            name="Scout LB 1",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            occurrence_id="scout_lb_1",
            server_id="main",
        )

        # Verify it was registered correctly
        assert agent1 is not None
        assert agent1.occurrence_id == "scout_lb_1"

        # Verify metadata file exists and has content
        assert temp_metadata_path.exists()
        with open(temp_metadata_path, "r") as f:
            content = f.read()
            assert len(content) > 0, "Metadata file is empty"

        # Create new instance
        registry2 = AgentRegistry(temp_metadata_path)

        # Should have loaded composite key data
        agent = registry2.get_agent("scout-abc123", occurrence_id="scout_lb_1", server_id="main")
        assert (
            agent is not None
        ), f"Agent not found. Registry has {len(registry2.agents)} agents: {list(registry2.agents.keys())}"
        assert agent.occurrence_id == "scout_lb_1"
        assert agent.port == 8080
