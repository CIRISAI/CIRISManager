"""
Test deployment field functionality in CIRISManager.
"""

from pathlib import Path
from ciris_manager.agent_registry import RegisteredAgent, AgentRegistry
from ciris_manager.models import AgentInfo


def test_registered_agent_default_deployment():
    """Test that RegisteredAgent gets default deployment field."""
    agent = RegisteredAgent(
        agent_id="test-agent",
        name="Test Agent",
        port=8080,
        template="default",
        compose_file="/path/to/compose.yml",
    )

    assert agent.metadata["deployment"] == "CIRIS_DISCORD_PILOT"


def test_registered_agent_custom_deployment():
    """Test setting custom deployment field."""
    agent = RegisteredAgent(
        agent_id="test-agent",
        name="Test Agent",
        port=8080,
        template="default",
        compose_file="/path/to/compose.yml",
        metadata={"deployment": "CUSTOM_PILOT"},
    )

    assert agent.metadata["deployment"] == "CUSTOM_PILOT"


def test_models_agent_info_deployment_field():
    """Test that models.AgentInfo has deployment field."""
    agent = AgentInfo(
        agent_id="test-agent", agent_name="Test Agent", container_name="test-container"
    )

    assert agent.deployment == "CIRIS_DISCORD_PILOT"  # Default value


def test_agent_registry_set_deployment():
    """Test setting deployment through registry."""
    registry = AgentRegistry(Path("/tmp/test"))

    # Register an agent
    registry.register_agent(
        agent_id="test-agent",
        name="Test Agent",
        port=8080,
        template="default",
        compose_file="/path/to/compose.yml",
    )

    # Set deployment
    result = registry.set_deployment("test-agent", "NEW_DEPLOYMENT")
    assert result is True

    # Verify it was set
    updated_agent = registry.get_agent("test-agent")
    assert updated_agent.metadata["deployment"] == "NEW_DEPLOYMENT"


def test_agent_registry_get_agents_by_deployment():
    """Test getting agents by deployment."""
    registry = AgentRegistry(Path("/tmp/test"))

    # Register multiple agents
    registry.register_agent("agent1", "Agent 1", 8080, "default", "/compose1.yml")
    registry.register_agent("agent2", "Agent 2", 8081, "default", "/compose2.yml")
    registry.register_agent("agent3", "Agent 3", 8082, "default", "/compose3.yml")

    # Set different deployments
    registry.set_deployment("agent1", "PILOT_A")
    registry.set_deployment("agent2", "PILOT_A")
    registry.set_deployment("agent3", "PILOT_B")

    # Get agents by deployment
    pilot_a_agents = registry.get_agents_by_deployment("PILOT_A")
    assert len(pilot_a_agents) == 2
    assert all(a.metadata["deployment"] == "PILOT_A" for a in pilot_a_agents)

    pilot_b_agents = registry.get_agents_by_deployment("PILOT_B")
    assert len(pilot_b_agents) == 1
    assert pilot_b_agents[0].agent_id == "agent3"

    default_agents = registry.get_agents_by_deployment("CIRIS_DISCORD_PILOT")
    assert len(default_agents) == 0  # All were reassigned


def test_agent_registry_nonexistent_agent():
    """Test setting deployment for nonexistent agent."""
    registry = AgentRegistry(Path("/tmp/test"))

    result = registry.set_deployment("nonexistent", "DEPLOYMENT")
    assert result is False
