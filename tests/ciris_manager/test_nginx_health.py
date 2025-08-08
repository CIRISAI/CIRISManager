"""
Test nginx health check configuration.
"""

import pytest
import tempfile
import shutil
from ciris_manager.nginx_manager import NginxManager
from ciris_manager.models import AgentInfo


class TestNginxHealth:
    """Test nginx health check configuration."""

    @pytest.fixture
    def temp_nginx_dir(self):
        """Create a temporary directory for nginx config."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_health_endpoint_on_http(self, temp_nginx_dir):
        """Test that health endpoint is available on HTTP port 80."""
        manager = NginxManager(temp_nginx_dir)
        agents = []

        config = manager.generate_config(agents)

        # Check that HTTP server block has health endpoint
        assert "listen 80;" in config
        assert "location /health {" in config

        # Find the HTTP server block
        http_server_start = config.find("listen 80;")
        http_server_end = config.find("listen 443", http_server_start)
        http_block = config[http_server_start:http_server_end]

        # Verify health endpoint is in HTTP block
        assert "location /health {" in http_block
        assert 'return 200 "healthy' in http_block
        assert "access_log off;" in http_block

        # Verify redirect is still there for other paths
        assert "location / {" in http_block
        assert "return 301 https://$server_name$request_uri;" in http_block

    def test_health_endpoint_also_on_https(self, temp_nginx_dir):
        """Test that health endpoint is also available on HTTPS."""
        manager = NginxManager(temp_nginx_dir)
        agents = []

        config = manager.generate_config(agents)

        # Check that HTTPS server block also has health endpoint
        assert "listen 443 ssl" in config

        # Find the HTTPS server block
        https_server_start = config.find("listen 443")
        https_block = config[https_server_start:]

        # Verify health endpoint is also in HTTPS block
        assert "location /health {" in https_block

    def test_full_config_structure(self, temp_nginx_dir):
        """Test the overall nginx config structure with health checks."""
        manager = NginxManager(temp_nginx_dir)

        # Create a test agent
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
        )

        config = manager.generate_config([agent])

        # Verify both server blocks exist
        assert config.count("server {") >= 2

        # Verify health endpoint appears at least twice (HTTP and HTTPS)
        assert config.count("location /health {") >= 2

        # Verify HTTP redirect for non-health paths
        assert "location / {" in config
        assert "return 301 https://" in config

        # Verify upstream for the agent
        assert "upstream agent_test-agent {" in config
        assert "server 127.0.0.1:8080;" in config

    def test_health_endpoint_returns_plain_text(self, temp_nginx_dir):
        """Test that health endpoint returns plain text."""
        manager = NginxManager(temp_nginx_dir)
        config = manager.generate_config([])

        # Check Content-Type header is set
        assert "add_header Content-Type text/plain;" in config

        # Check it returns a simple text response
        assert 'return 200 "healthy\\n";' in config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
