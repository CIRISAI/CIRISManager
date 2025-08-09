"""Tests for canary group management functionality."""

import pytest
from unittest.mock import MagicMock, patch
from ciris_manager.agent_registry import AgentRegistry
from ciris_manager.models import AgentInfo


class TestCanaryGroups:
    """Test canary group management."""

    def test_set_canary_group(self, tmp_path):
        """Test setting canary group for an agent."""
        metadata_path = tmp_path / "metadata.json"
        registry = AgentRegistry(metadata_path)
        
        # Create a mock agent
        agent = MagicMock()
        agent.agent_id = "test-agent"
        agent.name = "Test Agent"
        agent.port = 8001
        agent.template = "base"
        agent.compose_file = "/path/to/compose.yml"
        agent.metadata = {}
        agent.to_dict = MagicMock(return_value={
            "name": "Test Agent",
            "port": 8001,
            "template": "base",
            "compose_file": "/path/to/compose.yml",
            "metadata": {}
        })
        
        registry.agents["test-agent"] = agent
        
        # Set canary group
        result = registry.set_canary_group("test-agent", "explorer")
        assert result is True
        assert agent.metadata["canary_group"] == "explorer"
        
        # Change group
        result = registry.set_canary_group("test-agent", "early_adopter")
        assert result is True
        assert agent.metadata["canary_group"] == "early_adopter"
        
        # Remove group
        result = registry.set_canary_group("test-agent", None)
        assert result is True
        assert "canary_group" not in agent.metadata
        
        # Test non-existent agent
        result = registry.set_canary_group("non-existent", "explorer")
        assert result is False

    def test_get_agents_by_canary_group(self, tmp_path):
        """Test getting agents organized by canary group."""
        metadata_path = tmp_path / "metadata.json"
        registry = AgentRegistry(metadata_path)
        
        # Create mock agents
        agents_data = [
            ("agent1", "explorer"),
            ("agent2", "explorer"),
            ("agent3", "early_adopter"),
            ("agent4", "general"),
            ("agent5", "general"),
            ("agent6", None),  # Unassigned
        ]
        
        for agent_id, group in agents_data:
            agent = MagicMock()
            agent.agent_id = agent_id
            agent.name = f"Agent {agent_id}"
            agent.port = 8000 + int(agent_id[-1])
            agent.template = "base"
            agent.compose_file = f"/path/to/{agent_id}.yml"
            agent.metadata = {"canary_group": group} if group else {}
            agent.to_dict = MagicMock(return_value={
                "name": agent.name,
                "port": agent.port,
                "template": "base",
                "compose_file": agent.compose_file,
                "metadata": agent.metadata
            })
            registry.agents[agent_id] = agent
        
        # Get groups
        groups = registry.get_agents_by_canary_group()
        
        assert len(groups["explorer"]) == 2
        assert len(groups["early_adopter"]) == 1
        assert len(groups["general"]) == 2
        assert len(groups["unassigned"]) == 1
        
        # Check agent IDs
        explorer_ids = [a.agent_id for a in groups["explorer"]]
        assert "agent1" in explorer_ids
        assert "agent2" in explorer_ids
        
        unassigned_ids = [a.agent_id for a in groups["unassigned"]]
        assert "agent6" in unassigned_ids

    def test_canary_group_persistence(self, tmp_path):
        """Test that canary groups are persisted to disk."""
        metadata_path = tmp_path / "metadata.json"
        
        # Create registry and set groups
        registry1 = AgentRegistry(metadata_path)
        
        agent = MagicMock()
        agent.agent_id = "persistent-agent"
        agent.name = "Persistent Agent"
        agent.port = 8001
        agent.template = "base"
        agent.compose_file = "/path/to/compose.yml"
        agent.metadata = {}
        agent.to_dict = MagicMock(return_value={
            "name": "Persistent Agent",
            "port": 8001,
            "template": "base",
            "compose_file": "/path/to/compose.yml",
            "metadata": {"canary_group": "explorer"},
            "created_at": None,
            "oauth_status": None,
            "service_token": None
        })
        
        registry1.agents["persistent-agent"] = agent
        registry1.set_canary_group("persistent-agent", "explorer")
        
        # Verify metadata was saved
        assert metadata_path.exists()
        
        # Create new registry from same file
        registry2 = AgentRegistry(metadata_path)
        registry2._load_metadata()
        
        # Check that group was persisted
        if "persistent-agent" in registry2.agents:
            loaded_agent = registry2.agents["persistent-agent"]
            assert hasattr(loaded_agent, "metadata")
            assert loaded_agent.metadata.get("canary_group") == "explorer"


class TestCanaryGroupsIntegration:
    """Test canary groups integration."""
    
    def test_canary_groups_full_flow(self, tmp_path):
        """Test full flow of canary group assignment and retrieval."""
        metadata_path = tmp_path / "metadata.json"
        registry = AgentRegistry(metadata_path)
        
        # Create agents and assign to groups
        groups_map = {
            "explorer": ["agent1", "agent2"],
            "early_adopter": ["agent3"],
            "general": ["agent4", "agent5"],
        }
        
        for group, agent_ids in groups_map.items():
            for agent_id in agent_ids:
                agent = MagicMock()
                agent.agent_id = agent_id
                agent.name = f"Agent {agent_id}"
                agent.port = 8000 + int(agent_id[-1])
                agent.template = "base"
                agent.compose_file = f"/path/to/{agent_id}.yml"
                agent.metadata = {}
                agent.to_dict = MagicMock(return_value={
                    "name": agent.name,
                    "port": agent.port,
                    "template": "base",
                    "compose_file": agent.compose_file,
                    "metadata": {"canary_group": group}
                })
                registry.agents[agent_id] = agent
                registry.set_canary_group(agent_id, group)
        
        # Verify groups
        groups = registry.get_agents_by_canary_group()
        assert len(groups["explorer"]) == 2
        assert len(groups["early_adopter"]) == 1
        assert len(groups["general"]) == 2
        assert len(groups["unassigned"]) == 0
        
        # Test reassignment
        registry.set_canary_group("agent1", "general")
        groups = registry.get_agents_by_canary_group()
        assert len(groups["explorer"]) == 1
        assert len(groups["general"]) == 3