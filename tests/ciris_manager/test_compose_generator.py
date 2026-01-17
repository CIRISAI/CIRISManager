"""
Unit tests for ComposeGenerator.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from ciris_manager.compose_generator import ComposeGenerator


class TestComposeGenerator:
    """Test cases for ComposeGenerator."""

    @pytest.fixture
    def generator(self):
        """Create ComposeGenerator instance."""
        return ComposeGenerator(
            docker_registry="ghcr.io/cirisai", default_image="ciris-agent:latest"
        )

    @pytest.fixture
    def temp_agent_dir(self):
        """Create temporary agent directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    def test_initialization(self, generator):
        """Test ComposeGenerator initialization."""
        assert generator.docker_registry == "ghcr.io/cirisai"
        assert generator.default_image == "ciris-agent:latest"

    def test_generate_compose_basic(self, generator, temp_agent_dir):
        """Test basic compose generation."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
        )

        # Check structure
        assert "version" in compose
        assert compose["version"] == "3.8"
        assert "services" in compose
        assert "agent-scout" in compose["services"]
        assert "networks" in compose

        # Check service config
        service = compose["services"]["agent-scout"]
        assert service["container_name"] == "ciris-agent-scout"
        # Now uses image from GHCR instead of building locally
        assert "image" in service
        assert service["image"] == "ghcr.io/cirisai/ciris-agent:latest"
        assert service["platform"] == "linux/amd64"
        assert service["ports"] == ["8081:8080"]
        assert service["restart"] == "no"

        # Check environment
        env = service["environment"]
        # CIRIS_AGENT_NAME removed - display name derived from agent_id
        assert env["CIRIS_AGENT_ID"] == "agent-scout"
        assert env["CIRIS_TEMPLATE"] == "scout"
        assert env["CIRIS_API_HOST"] == "0.0.0.0"
        assert env["CIRIS_API_PORT"] == "8080"
        assert env["CIRIS_MOCK_LLM"] == "true"
        assert env["OAUTH_CALLBACK_BASE_URL"] == "https://agents.ciris.ai"

        # Check volumes - now using bind mounts
        volumes = service["volumes"]
        assert any("/data:/app/data" in v for v in volumes)
        assert any("/logs:/app/logs" in v for v in volumes)
        assert any("/.secrets:/app/.secrets" in v for v in volumes)
        assert any("/audit_keys:/app/audit_keys" in v for v in volumes)
        assert any("/init_permissions.sh:/init_permissions.sh:ro" in v for v in volumes)
        assert "/home/ciris/shared/oauth:/home/ciris/shared/oauth:ro" in volumes

        # Check entrypoint
        assert service.get("entrypoint") == ["/init_permissions.sh"]

        # Check healthcheck
        health = service["healthcheck"]
        assert health["test"] == ["CMD", "curl", "-f", "http://localhost:8080/v1/system/health"]
        assert health["interval"] == "30s"
        assert health["timeout"] == "10s"
        assert health["retries"] == 3
        assert health["start_period"] == "40s"

        # Check logging
        logging = service["logging"]
        assert logging["driver"] == "json-file"
        assert logging["options"]["max-size"] == "10m"
        assert logging["options"]["max-file"] == "3"

        # Check network
        network = compose["networks"]["default"]
        assert network["name"] == "ciris-agent-scout-network"

    def test_generate_compose_with_environment(self, generator, temp_agent_dir):
        """Test compose generation with additional environment."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            environment={
                "CUSTOM_VAR": "custom_value",
                "CIRIS_MOCK_LLM": "false",  # Override default
                "DEBUG": "true",
            },
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["CUSTOM_VAR"] == "custom_value"
        assert env["CIRIS_MOCK_LLM"] == "false"  # Overridden
        assert env["DEBUG"] == "true"
        # CIRIS_AGENT_NAME removed - display name derived from agent_id  # Base env still present

    def test_generate_compose_no_mock_llm(self, generator, temp_agent_dir):
        """Test compose generation without mock LLM."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            use_mock_llm=False,
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert "CIRIS_MOCK_LLM" not in env

    def test_generate_compose_with_discord(self, generator, temp_agent_dir):
        """Test compose generation with Discord adapter enabled."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            environment={"DISCORD_BOT_TOKEN": "test-token"},
            enable_discord=True,
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert "CIRIS_ADAPTER" in env
        assert "discord" in env["CIRIS_ADAPTER"]
        assert "api" in env["CIRIS_ADAPTER"]

    def test_generate_compose_custom_oauth_volume(self, generator, temp_agent_dir):
        """Test compose generation with custom OAuth volume."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            oauth_volume="/custom/oauth/path",
        )

        volumes = compose["services"]["agent-scout"]["volumes"]
        # Custom OAuth volume path should be used
        assert any("/data:/app/data" in v for v in volumes)
        assert any("/logs:/app/logs" in v for v in volumes)
        assert "/custom/oauth/path:/home/ciris/shared/oauth:ro" in volumes

    def test_write_compose_file(self, generator, temp_agent_dir):
        """Test writing compose file to disk."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
        )

        compose_path = temp_agent_dir / "docker-compose.yml"
        generator.write_compose_file(compose, compose_path)

        # Verify file exists
        assert compose_path.exists()

        # Verify content
        with open(compose_path, "r") as f:
            loaded = yaml.safe_load(f)

        assert loaded == compose

        # Verify formatting
        with open(compose_path, "r") as f:
            content = f.read()

        # Should be properly formatted
        assert "version: '3.8'" in content
        assert "  agent-scout:" in content  # Proper indentation

    def test_write_compose_file_creates_directory(self, generator, temp_agent_dir):
        """Test compose file writing creates parent directories."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
        )

        # Use nested path
        compose_path = temp_agent_dir / "nested" / "dir" / "docker-compose.yml"
        generator.write_compose_file(compose, compose_path)

        # Verify file and directories exist
        assert compose_path.exists()
        assert compose_path.parent.exists()

    def test_generate_env_file(self, generator, temp_agent_dir):
        """Test .env file generation."""
        env_vars = {
            "OPENAI_API_KEY": "sk-test123",
            "DISCORD_TOKEN": "discord.token.here",
            "CUSTOM_SECRET": "secret value with spaces",
        }

        env_path = temp_agent_dir / ".env"
        generator.generate_env_file(env_vars, env_path)

        # Verify file exists
        assert env_path.exists()

        # Verify content
        with open(env_path, "r") as f:
            content = f.read()

        assert "OPENAI_API_KEY=sk-test123" in content
        assert "DISCORD_TOKEN=discord.token.here" in content
        assert 'CUSTOM_SECRET="secret value with spaces"' in content  # Quoted

    def test_network_naming(self, generator, temp_agent_dir):
        """Test network naming for different agent names."""
        # Test with various agent IDs - network name is based on agent_id not agent_name
        test_cases = [
            ("agent-scout", "Scout", "ciris-agent-scout-network"),
            ("agent-sage", "SAGE", "ciris-agent-sage-network"),
            ("echo-core", "Echo-Core", "ciris-echo-core-network"),
            ("agent-123", "Agent 123", "ciris-agent-123-network"),
        ]

        for agent_id, agent_name, expected_network in test_cases:
            compose = generator.generate_compose(
                agent_id=agent_id,
                agent_name=agent_name,
                port=8080,
                template="default",
                agent_dir=temp_agent_dir,
            )

            assert compose["networks"]["default"]["name"] == expected_network

    def test_port_mapping(self, generator, temp_agent_dir):
        """Test various port mappings."""
        # Test different ports
        for port in [8080, 8081, 8200, 9000]:
            compose = generator.generate_compose(
                agent_id="agent-test",
                agent_name="Test",
                port=port,
                template="default",
                agent_dir=temp_agent_dir,
            )

            service = compose["services"]["agent-test"]
            assert service["ports"] == [f"{port}:8080"]

    def test_generate_compose_with_billing_enabled(self, generator, temp_agent_dir):
        """Test compose generation with billing enabled."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            billing_enabled=True,
            billing_api_key="test-billing-key-abc123",
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["CIRIS_BILLING_ENABLED"] == "true"
        assert env["CIRIS_BILLING_API_KEY"] == "test-billing-key-abc123"

    def test_generate_compose_with_billing_disabled(self, generator, temp_agent_dir):
        """Test compose generation with billing disabled (default)."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            billing_enabled=False,
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["CIRIS_BILLING_ENABLED"] == "false"
        assert "CIRIS_BILLING_API_KEY" not in env

    def test_generate_compose_billing_default(self, generator, temp_agent_dir):
        """Test compose generation with default billing settings."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
        )

        env = compose["services"]["agent-scout"]["environment"]
        # Should default to false
        assert env["CIRIS_BILLING_ENABLED"] == "false"
        assert "CIRIS_BILLING_API_KEY" not in env

    def test_generate_compose_billing_enabled_without_key(self, generator, temp_agent_dir):
        """Test compose generation with billing enabled but no API key provided."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            billing_enabled=True,
            billing_api_key=None,
        )

        env = compose["services"]["agent-scout"]["environment"]
        # Should still set enabled flag
        assert env["CIRIS_BILLING_ENABLED"] == "true"
        # But no API key should be present
        assert "CIRIS_BILLING_API_KEY" not in env

    def test_generate_compose_custom_oauth_hostname(self, generator, temp_agent_dir):
        """Test compose generation with custom OAuth callback hostname."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            oauth_callback_hostname="scoutapilb.ciris.ai",
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["OAUTH_CALLBACK_BASE_URL"] == "https://scoutapilb.ciris.ai"

    def test_generate_compose_default_oauth_hostname(self, generator, temp_agent_dir):
        """Test compose generation with default OAuth callback hostname."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            # No oauth_callback_hostname specified - should use default
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["OAUTH_CALLBACK_BASE_URL"] == "https://agents.ciris.ai"

    def test_generate_compose_with_adapter_configs(self, generator, temp_agent_dir):
        """Test compose generation with adapter_configs from wizard."""
        adapter_configs = {
            "home_assistant": {
                "enabled": True,
                "env_vars": {
                    "HOME_ASSISTANT_URL": "http://192.168.1.100:8123",
                    "HOME_ASSISTANT_TOKEN": "secret_token_123",
                },
            },
            "covenant_metrics": {
                "enabled": True,
                "consent_given": True,
                "env_vars": {
                    "CIRIS_COVENANT_METRICS_CONSENT": "true",
                },
            },
        }

        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            adapter_configs=adapter_configs,
        )

        env = compose["services"]["agent-scout"]["environment"]

        # Check adapter channels are added
        adapters = env["CIRIS_ADAPTER"].split(",")
        assert "api" in adapters
        assert "home_assistant" in adapters
        assert "covenant_metrics" in adapters

        # Check env vars are applied
        assert env["HOME_ASSISTANT_URL"] == "http://192.168.1.100:8123"
        assert env["HOME_ASSISTANT_TOKEN"] == "secret_token_123"
        assert env["CIRIS_COVENANT_METRICS_CONSENT"] == "true"

    def test_generate_compose_adapter_configs_with_discord(self, generator, temp_agent_dir):
        """Test that adapter_configs works alongside enable_discord flag."""
        adapter_configs = {
            "reddit": {
                "enabled": True,
                "env_vars": {
                    "REDDIT_CLIENT_ID": "my_client_id",
                    "REDDIT_CLIENT_SECRET": "my_secret",
                },
            },
        }

        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            environment={"DISCORD_BOT_TOKEN": "test_discord_token"},
            enable_discord=True,
            adapter_configs=adapter_configs,
        )

        env = compose["services"]["agent-scout"]["environment"]

        # Check both Discord (from enable_discord) and Reddit (from adapter_configs) are enabled
        adapters = env["CIRIS_ADAPTER"].split(",")
        assert "api" in adapters
        assert "discord" in adapters  # From enable_discord flag
        assert "reddit" in adapters  # From adapter_configs

        # Check env vars
        assert env["DISCORD_BOT_TOKEN"] == "test_discord_token"
        assert env["REDDIT_CLIENT_ID"] == "my_client_id"
        assert env["REDDIT_CLIENT_SECRET"] == "my_secret"

    def test_generate_compose_adapter_configs_disabled(self, generator, temp_agent_dir):
        """Test that disabled adapters are not added."""
        adapter_configs = {
            "home_assistant": {
                "enabled": False,  # Disabled
                "env_vars": {
                    "HOME_ASSISTANT_URL": "http://192.168.1.100:8123",
                },
            },
            "reddit": {
                "enabled": True,
                "env_vars": {
                    "REDDIT_CLIENT_ID": "my_id",
                },
            },
        }

        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            adapter_configs=adapter_configs,
        )

        env = compose["services"]["agent-scout"]["environment"]

        # home_assistant should NOT be in adapters (disabled)
        adapters = env["CIRIS_ADAPTER"].split(",")
        assert "home_assistant" not in adapters
        assert "reddit" in adapters

        # env vars for disabled adapter should NOT be applied
        assert "HOME_ASSISTANT_URL" not in env
        # env vars for enabled adapter should be applied
        assert env["REDDIT_CLIENT_ID"] == "my_id"

    def test_generate_compose_oauth_allowed_domains_default(self, generator, temp_agent_dir):
        """Test that OAUTH_ALLOWED_REDIRECT_DOMAINS defaults to callback hostname."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            oauth_callback_hostname="scoutapilb.ciris.ai",
        )

        env = compose["services"]["agent-scout"]["environment"]
        # Should default to the oauth_callback_hostname
        assert env["OAUTH_ALLOWED_REDIRECT_DOMAINS"] == "scoutapilb.ciris.ai"

    def test_generate_compose_oauth_allowed_domains_explicit(self, generator, temp_agent_dir):
        """Test OAUTH_ALLOWED_REDIRECT_DOMAINS with explicit list of domains."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            oauth_callback_hostname="agents.ciris.ai",
            oauth_allowed_domains=["agents.ciris.ai", "scoutapilb.ciris.ai", "localhost"],
        )

        env = compose["services"]["agent-scout"]["environment"]
        # Should use the explicit list, comma-separated
        assert (
            env["OAUTH_ALLOWED_REDIRECT_DOMAINS"] == "agents.ciris.ai,scoutapilb.ciris.ai,localhost"
        )

    def test_generate_compose_oauth_allowed_domains_single(self, generator, temp_agent_dir):
        """Test OAUTH_ALLOWED_REDIRECT_DOMAINS with a single explicit domain."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            oauth_allowed_domains=["custom.domain.com"],
        )

        env = compose["services"]["agent-scout"]["environment"]
        assert env["OAUTH_ALLOWED_REDIRECT_DOMAINS"] == "custom.domain.com"

    def test_generate_compose_oauth_allowed_domains_with_default_hostname(
        self, generator, temp_agent_dir
    ):
        """Test OAUTH_ALLOWED_REDIRECT_DOMAINS uses default agents.ciris.ai when neither specified."""
        compose = generator.generate_compose(
            agent_id="agent-scout",
            agent_name="Scout",
            port=8081,
            template="scout",
            agent_dir=temp_agent_dir,
            # Neither oauth_callback_hostname nor oauth_allowed_domains specified
        )

        env = compose["services"]["agent-scout"]["environment"]
        # Should use default callback hostname (agents.ciris.ai)
        assert env["OAUTH_CALLBACK_BASE_URL"] == "https://agents.ciris.ai"
        assert env["OAUTH_ALLOWED_REDIRECT_DOMAINS"] == "agents.ciris.ai"
