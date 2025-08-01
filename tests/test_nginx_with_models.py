"""Test nginx config generation with typed models."""

import tempfile
from pathlib import Path

from ciris_manager.nginx_manager import NginxManager
from ciris_manager.models import AgentInfo


def test_nginx_config_with_typed_agents():
    """Test nginx config generation using AgentInfo models."""
    
    # Create test agents using our model
    agents = [
        AgentInfo(
            agent_id="datum",
            agent_name="Datum",
            container_name="ciris-agent-datum",
            api_port=8080,
            status="running",
        ),
        AgentInfo(
            agent_id="sage",
            agent_name="Sage",
            container_name="ciris-agent-sage",
            api_port=8081,
            status="running",
        ),
        AgentInfo(
            agent_id="stopped",
            agent_name="Stopped Agent",
            container_name="ciris-agent-stopped",
            status="stopped",
            # No port - should be skipped
        ),
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = NginxManager(config_dir=tmpdir, container_name="test-nginx")
        
        # Generate config
        config = manager.generate_config(agents)
        
        # Verify the config
        assert "upstream agent_datum" in config
        assert "upstream agent_sage" in config
        assert "upstream agent_stopped" not in config  # No port, should be skipped
        
        # Check routes
        assert "/api/datum/" in config
        assert "/api/sage/" in config
        assert "/api/stopped/" not in config
        
        # Verify NO default route
        assert "location /v1/" not in config
        
        # Verify static file serving for Manager GUI
        assert "root /home/ciris/CIRISManager/static" in config
        
        print("✓ Nginx config generation works with typed models")


def test_empty_agents_list():
    """Test nginx config with no agents."""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = NginxManager(config_dir=tmpdir, container_name="test-nginx")
        
        # Generate config with empty list
        config = manager.generate_config([])
        
        # Should still have basic structure
        assert "upstream agent_gui" in config
        assert "upstream manager" in config
        assert "root /home/ciris/CIRISManager/static" in config
        
        # But no agent routes
        assert "upstream agent_" not in config.replace("upstream agent_gui", "")
        
        print("✓ Empty agent list generates valid config")


if __name__ == "__main__":
    test_nginx_config_with_typed_agents()
    test_empty_agents_list()
    print("\nAll tests passed! 🎉")