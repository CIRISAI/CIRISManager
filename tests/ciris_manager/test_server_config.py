"""
Unit tests for ServerConfig and multi-server configuration.
"""

from ciris_manager.config.settings import ServerConfig, CIRISManagerConfig


class TestServerConfig:
    """Test cases for ServerConfig model."""

    def test_local_server_config(self):
        """Test local server configuration."""
        config = ServerConfig(
            server_id="main",
            hostname="agents.ciris.ai",
            is_local=True,
        )

        assert config.server_id == "main"
        assert config.hostname == "agents.ciris.ai"
        assert config.is_local is True
        assert config.vpc_ip is None
        assert config.docker_host is None
        assert config.tls_ca is None
        assert config.tls_cert is None
        assert config.tls_key is None

    def test_remote_server_config(self):
        """Test remote server configuration with TLS."""
        config = ServerConfig(
            server_id="scout",
            hostname="scoutapi.ciris.ai",
            is_local=False,
            vpc_ip="10.2.96.4",
            docker_host="tcp://10.2.96.4:2376",
            tls_ca="/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem",
            tls_cert="/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem",
            tls_key="/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem",
        )

        assert config.server_id == "scout"
        assert config.hostname == "scoutapi.ciris.ai"
        assert config.is_local is False
        assert config.vpc_ip == "10.2.96.4"
        assert config.docker_host == "tcp://10.2.96.4:2376"
        assert config.tls_ca == "/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem"
        assert (
            config.tls_cert == "/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem"
        )
        assert config.tls_key == "/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem"

    def test_server_config_defaults(self):
        """Test server configuration with minimal fields."""
        config = ServerConfig(
            server_id="test",
            hostname="test.example.com",
        )

        assert config.server_id == "test"
        assert config.hostname == "test.example.com"
        assert config.is_local is False  # Default
        assert config.vpc_ip is None
        assert config.docker_host is None


class TestCIRISManagerConfigServers:
    """Test cases for servers configuration in CIRISManagerConfig."""

    def test_default_config_has_main_server(self):
        """Test that default configuration includes main server."""
        config = CIRISManagerConfig()

        assert len(config.servers) == 1
        assert config.servers[0].server_id == "main"
        assert config.servers[0].hostname == "agents.ciris.ai"
        assert config.servers[0].is_local is True

    def test_config_with_multiple_servers(self):
        """Test configuration with multiple servers."""
        config = CIRISManagerConfig(
            servers=[
                ServerConfig(
                    server_id="main",
                    hostname="agents.ciris.ai",
                    is_local=True,
                ),
                ServerConfig(
                    server_id="scout",
                    hostname="scoutapi.ciris.ai",
                    is_local=False,
                    vpc_ip="10.2.96.4",
                    docker_host="tcp://10.2.96.4:2376",
                    tls_ca="/certs/ca.pem",
                    tls_cert="/certs/client-cert.pem",
                    tls_key="/certs/client-key.pem",
                ),
            ]
        )

        assert len(config.servers) == 2

        # Check main server
        main = config.servers[0]
        assert main.server_id == "main"
        assert main.is_local is True

        # Check scout server
        scout = config.servers[1]
        assert scout.server_id == "scout"
        assert scout.is_local is False
        assert scout.vpc_ip == "10.2.96.4"
        assert scout.docker_host == "tcp://10.2.96.4:2376"

    def test_config_serialization_with_servers(self):
        """Test configuration can be serialized and deserialized."""
        config = CIRISManagerConfig(
            servers=[
                ServerConfig(
                    server_id="main",
                    hostname="agents.ciris.ai",
                    is_local=True,
                ),
                ServerConfig(
                    server_id="scout",
                    hostname="scoutapi.ciris.ai",
                    is_local=False,
                    vpc_ip="10.2.96.4",
                    docker_host="tcp://10.2.96.4:2376",
                ),
            ]
        )

        # Serialize to dict
        config_dict = config.model_dump()

        # Verify servers in dict
        assert "servers" in config_dict
        assert len(config_dict["servers"]) == 2
        assert config_dict["servers"][0]["server_id"] == "main"
        assert config_dict["servers"][1]["server_id"] == "scout"

        # Deserialize back
        reloaded = CIRISManagerConfig(**config_dict)
        assert len(reloaded.servers) == 2
        assert reloaded.servers[0].server_id == "main"
        assert reloaded.servers[1].server_id == "scout"

    def test_config_yaml_roundtrip(self, tmp_path):
        """Test configuration can be saved and loaded from YAML."""

        config = CIRISManagerConfig(
            servers=[
                ServerConfig(
                    server_id="main",
                    hostname="agents.ciris.ai",
                    is_local=True,
                ),
                ServerConfig(
                    server_id="scout",
                    hostname="scoutapi.ciris.ai",
                    is_local=False,
                    vpc_ip="10.2.96.4",
                    docker_host="tcp://10.2.96.4:2376",
                    tls_ca="/certs/ca.pem",
                    tls_cert="/certs/client-cert.pem",
                    tls_key="/certs/client-key.pem",
                ),
            ]
        )

        # Save to YAML
        config_path = tmp_path / "config.yml"
        config.save(str(config_path))

        # Load from YAML
        loaded = CIRISManagerConfig.from_file(str(config_path))

        # Verify
        assert len(loaded.servers) == 2
        assert loaded.servers[0].server_id == "main"
        assert loaded.servers[1].server_id == "scout"
        assert loaded.servers[1].vpc_ip == "10.2.96.4"
        assert loaded.servers[1].tls_ca == "/certs/ca.pem"
