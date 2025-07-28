"""
Unit tests for AgentRegistry.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
from ciris_manager.agent_registry import AgentRegistry, AgentInfo


class TestAgentInfo:
    """Test cases for AgentInfo class."""
    
    def test_initialization(self):
        """Test AgentInfo initialization."""
        agent = AgentInfo(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml"
        )
        
        assert agent.agent_id == "agent-test"
        assert agent.name == "Test"
        assert agent.port == 8080
        assert agent.template == "scout"
        assert agent.compose_file == "/path/to/compose.yml"
        assert agent.created_at is not None
        assert "T" in agent.created_at  # ISO format
        assert agent.created_at.endswith("Z")
    
    def test_initialization_with_created_at(self):
        """Test AgentInfo initialization with created_at."""
        created_at = "2025-01-21T10:00:00Z"
        agent = AgentInfo(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml",
            created_at=created_at
        )
        
        assert agent.created_at == created_at
    
    def test_to_dict(self):
        """Test converting AgentInfo to dict."""
        agent = AgentInfo(
            agent_id="agent-test",
            name="Test",
            port=8080,
            template="scout",
            compose_file="/path/to/compose.yml"
        )
        
        data = agent.to_dict()
        assert data["name"] == "Test"
        assert data["port"] == 8080
        assert data["template"] == "scout"
        assert data["compose_file"] == "/path/to/compose.yml"
        assert "created_at" in data
        assert "agent_id" not in data  # Not included in dict
    
    def test_from_dict(self):
        """Test creating AgentInfo from dict."""
        data = {
            "name": "Test",
            "port": 8080,
            "template": "scout",
            "compose_file": "/path/to/compose.yml",
            "created_at": "2025-01-21T10:00:00Z"
        }
        
        agent = AgentInfo.from_dict("agent-test", data)
        assert agent.agent_id == "agent-test"
        assert agent.name == "Test"
        assert agent.port == 8080
        assert agent.template == "scout"
        assert agent.compose_file == "/path/to/compose.yml"
        assert agent.created_at == "2025-01-21T10:00:00Z"


class TestAgentRegistry:
    """Test cases for AgentRegistry."""
    
    @pytest.fixture
    def temp_metadata_path(self):
        """Create temporary metadata file path."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
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
            compose_file="/etc/agents/scout/docker-compose.yml"
        )
        
        assert agent.agent_id == "agent-scout"
        assert agent.name == "Scout"
        assert agent.port == 8081
        assert agent.template == "scout"
        assert agent.compose_file == "/etc/agents/scout/docker-compose.yml"
        
        # Verify in registry
        assert "agent-scout" in registry.agents
        assert registry.agents["agent-scout"] == agent
        
        # Verify metadata saved
        assert registry.metadata_path.exists()
    
    def test_unregister_agent(self, registry):
        """Test agent unregistration."""
        # Register first
        registry.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml"
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
            compose_file="/etc/agents/scout/docker-compose.yml"
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
            compose_file="/etc/agents/scout/docker-compose.yml"
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
            compose_file="/etc/agents/scout/docker-compose.yml"
        )
        
        agent2 = registry.register_agent(
            agent_id="agent-sage",
            name="Sage",
            port=8082,
            template="sage",
            compose_file="/etc/agents/sage/docker-compose.yml"
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
            compose_file="/etc/agents/scout/docker-compose.yml"
        )
        
        registry.register_agent(
            agent_id="agent-sage",
            name="Sage",
            port=8082,
            template="sage",
            compose_file="/etc/agents/sage/docker-compose.yml"
        )
        
        # Get ports
        ports = registry.get_allocated_ports()
        assert ports == {
            "agent-scout": 8081,
            "agent-sage": 8082
        }
    
    def test_persistence(self, temp_metadata_path):
        """Test metadata persistence across instances."""
        # Create and register
        registry1 = AgentRegistry(temp_metadata_path)
        registry1.register_agent(
            agent_id="agent-scout",
            name="Scout",
            port=8081,
            template="scout",
            compose_file="/etc/agents/scout/docker-compose.yml"
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
            compose_file="/etc/agents/scout/docker-compose.yml"
        )
        
        # Read metadata
        with open(temp_metadata_path, 'r') as f:
            data = json.load(f)
        
        assert "version" in data
        assert data["version"] == "1.0"
        assert "updated_at" in data
        assert "agents" in data
        assert "agent-scout" in data["agents"]
        
        agent_data = data["agents"]["agent-scout"]
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
                    compose_file=f"/etc/agents/{name.lower()}/docker-compose.yml"
                )
            except Exception as e:
                errors.append(e)
        
        # Create threads
        threads = []
        for i in range(5):
            t = threading.Thread(
                target=register_agent,
                args=(f"agent-{i}", f"Agent{i}", 8080 + i)
            )
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
        with open(registry.metadata_path, 'r') as f:
            data = json.load(f)
            assert len(data["agents"]) == 5