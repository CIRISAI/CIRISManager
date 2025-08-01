"""Test the simple models."""

import pytest
from ciris_manager.models import AgentInfo


def test_agent_info_basic():
    """Test basic AgentInfo creation."""
    agent = AgentInfo(
        agent_id="datum",
        agent_name="Datum",
        container_name="ciris-agent-datum",
        api_port=8080,
        status="running",
    )
    
    assert agent.agent_id == "datum"
    assert agent.is_running is True
    assert agent.has_port is True


def test_agent_info_no_port():
    """Test agent without port."""
    agent = AgentInfo(
        agent_id="stopped",
        agent_name="Stopped Agent",
        container_name="ciris-agent-stopped",
        status="stopped",
    )
    
    assert agent.api_port is None
    assert agent.is_running is False
    assert agent.has_port is False


def test_agent_info_validation():
    """Test that required fields are enforced."""
    # Should fail without required fields
    with pytest.raises(ValueError):
        AgentInfo()  # type: ignore
    
    # Should work with minimal required fields
    agent = AgentInfo(
        agent_id="test",
        agent_name="Test",
        container_name="test-container",
    )
    assert agent.status == "stopped"  # default value