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
        # Default use_ssl=False (Cloudflare mode)
        manager = NginxManager(temp_nginx_dir)
        agents = []

        config = manager.generate_config(agents)

        # Check that HTTP server block has health endpoint
        assert "listen 80;" in config
        assert "location /health {" in config

        # Verify health endpoint is in HTTP block
        assert 'return 200 "healthy' in config
        assert "access_log off;" in config

        # With use_ssl=False, there should be no HTTPS redirect
        # The root location should proxy to agent_gui, not redirect
        assert "proxy_pass http://agent_gui;" in config

    def test_health_endpoint_with_ssl(self, temp_nginx_dir):
        """Test that health endpoint is available on both HTTP and HTTPS when SSL enabled."""
        # use_ssl=True for Let's Encrypt mode
        manager = NginxManager(temp_nginx_dir, use_ssl=True)
        agents = []

        config = manager.generate_config(agents)

        # Check that HTTPS server block also has health endpoint
        assert "listen 443 ssl" in config

        # Find the HTTPS server block
        https_server_start = config.find("listen 443")
        https_block = config[https_server_start:]

        # Verify health endpoint is also in HTTPS block
        assert "location /health {" in https_block

        # Verify HTTP to HTTPS redirect
        assert "return 301 https://$server_name$request_uri;" in config

    def test_http_only_config_structure(self, temp_nginx_dir):
        """Test the HTTP-only nginx config structure (Cloudflare Flexible SSL mode)."""
        manager = NginxManager(temp_nginx_dir, use_ssl=False)

        # Create a test agent
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
        )

        config = manager.generate_config([agent])

        # With use_ssl=False, there should only be HTTP server block
        assert "listen 80;" in config
        assert "listen 443 ssl" not in config

        # Verify health endpoint
        assert "location /health {" in config

        # Verify upstream for the agent
        assert "upstream agent_test-agent {" in config
        assert "server 127.0.0.1:8080;" in config

    def test_ssl_config_structure(self, temp_nginx_dir):
        """Test the SSL nginx config structure (Let's Encrypt mode)."""
        manager = NginxManager(temp_nginx_dir, use_ssl=True)

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
        assert "listen 80;" in config
        assert "listen 443 ssl" in config

        # Verify health endpoint appears at least twice (HTTP and HTTPS)
        assert config.count("location /health {") >= 2

        # Verify HTTP redirect for non-health paths
        assert "return 301 https://" in config

        # Verify SSL certificate paths
        assert "ssl_certificate /etc/letsencrypt/live/" in config
        assert "ssl_certificate_key /etc/letsencrypt/live/" in config

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
