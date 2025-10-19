"""
Docker Compose file generator for CIRIS agents.

Generates individual docker-compose.yml files for each agent.
"""

import yaml
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ComposeGenerator:
    """Generates Docker Compose configurations for agents."""

    def __init__(self, docker_registry: str, default_image: str):
        """
        Initialize compose generator.

        Args:
            docker_registry: Docker registry URL
            default_image: Default agent image name
        """
        self.docker_registry = docker_registry
        self.default_image = default_image

    def generate_compose(
        self,
        agent_id: str,
        agent_name: str,
        port: int,
        template: str,
        agent_dir: Path,
        environment: Optional[Dict[str, str]] = None,
        use_mock_llm: bool = True,
        enable_discord: bool = False,
        oauth_volume: str = "/home/ciris/shared/oauth",
        billing_enabled: bool = False,
        billing_api_key: Optional[str] = None,
        database_url: Optional[str] = None,
        database_ssl_cert_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate docker-compose configuration for an agent.

        Args:
            agent_id: Unique agent identifier
            agent_name: Human-friendly agent name
            port: Allocated port number
            template: Template name
            agent_dir: Agent's directory path
            environment: Additional environment variables
            use_mock_llm: Whether to use mock LLM
            enable_discord: Whether to enable Discord adapter
            oauth_volume: Path to shared OAuth configuration
            billing_enabled: Whether to enable paid billing (default: False)
            billing_api_key: Billing API key (required if billing_enabled=True)
            database_url: PostgreSQL database URL
            database_ssl_cert_path: Path to SSL certificate for database connection

        Returns:
            Docker compose configuration dict
        """
        # Base environment
        base_env = {
            "CIRIS_AGENT_ID": agent_id,
            "CIRIS_TEMPLATE": template,
            "CIRIS_API_HOST": "0.0.0.0",
            "CIRIS_API_PORT": "8080",
            # OAuth configuration for agent authentication
            "OAUTH_CALLBACK_BASE_URL": "https://agents.ciris.ai",
        }

        if use_mock_llm:
            base_env["CIRIS_MOCK_LLM"] = "true"

        # Add billing configuration
        if billing_enabled:
            base_env["CIRIS_BILLING_ENABLED"] = "true"
            if billing_api_key:
                base_env["CIRIS_BILLING_API_KEY"] = billing_api_key
        else:
            base_env["CIRIS_BILLING_ENABLED"] = "false"

        # Add database configuration
        if database_url:
            base_env["CIRIS_DB_URL"] = database_url
        if database_ssl_cert_path:
            base_env["PGSSLROOTCERT"] = database_ssl_cert_path

        # Merge with additional environment
        if environment:
            base_env.update(environment)

        # Determine communication channels based on configuration
        channels = []

        # API is always enabled for management and monitoring
        channels.append("api")
        logger.info("Communication channel enabled: API (Web GUI access)")

        # Check if Discord should be enabled
        if enable_discord:
            # Verify Discord token is provided
            discord_token_keys = [
                "DISCORD_BOT_TOKEN",
                "DISCORD_TOKEN",
            ]
            has_discord_token = any(
                key in base_env and base_env.get(key) for key in discord_token_keys
            )

            if has_discord_token:
                channels.append("discord")
                logger.info("Communication channel enabled: Discord")
            else:
                logger.warning(
                    "Discord adapter requested but no DISCORD_BOT_TOKEN provided in environment"
                )

        # Future: Add support for other platforms
        # if enable_slack and "SLACK_BOT_TOKEN" in base_env:
        #     channels.append("slack")
        #     logger.info("Communication channel enabled: Slack")

        # Set the final adapter configuration
        base_env["CIRIS_ADAPTER"] = ",".join(channels)
        logger.info(f"Agent will be accessible via: {', '.join(channels)}")

        # Build compose configuration
        compose_config = {
            "version": "3.8",
            "services": {
                agent_id: {
                    "container_name": f"ciris-{agent_id}",
                    "image": f"{self.docker_registry}/{self.default_image}",
                    "platform": "linux/amd64",
                    "ports": [f"{port}:8080"],
                    "entrypoint": ["/init_permissions.sh"],
                    "command": ["python", "main.py", "--template", template],
                    "environment": base_env,
                    "volumes": self._build_volumes(agent_dir, oauth_volume, database_ssl_cert_path),
                    "restart": "no",
                    "healthcheck": {
                        "test": ["CMD", "curl", "-f", "http://localhost:8080/v1/system/health"],
                        "interval": "30s",
                        "timeout": "10s",
                        "retries": 3,
                        "start_period": "40s",
                    },
                    "logging": {
                        "driver": "json-file",
                        "options": {"max-size": "10m", "max-file": "3"},
                    },
                    "labels": {
                        "ai.ciris.agents.id": agent_id,
                        "ai.ciris.agents.created": datetime.now(timezone.utc).isoformat(),
                        "ai.ciris.agents.template": template,
                        "ai.ciris.agents.deployment_group": "general",
                    },
                }
            },
            "networks": {"default": {"name": f"ciris-{agent_id}-network"}},
        }

        return compose_config

    def _build_volumes(
        self, agent_dir: Path, oauth_volume: str, database_ssl_cert_path: Optional[str] = None
    ) -> list:
        """
        Build volume mount list for agent container.

        Args:
            agent_dir: Agent's directory path
            oauth_volume: Path to shared OAuth configuration
            database_ssl_cert_path: Optional path to SSL certificate for database

        Returns:
            List of volume mount strings
        """
        volumes = [
            f"{agent_dir}/data:/app/data",
            f"{agent_dir}/data_archive:/app/data_archive",
            f"{agent_dir}/logs:/app/logs",
            f"{agent_dir}/config:/app/config",
            f"{agent_dir}/audit_keys:/app/audit_keys",
            f"{agent_dir}/.secrets:/app/.secrets",
            f"{agent_dir}/init_permissions.sh:/init_permissions.sh:ro",
            f"{oauth_volume}:/home/ciris/shared/oauth:ro",
        ]

        # Add database SSL certificate volume mount if provided
        if database_ssl_cert_path:
            volumes.append(f"{database_ssl_cert_path}:{database_ssl_cert_path}:ro")

        return volumes

    def write_compose_file(self, compose_config: Dict[str, Any], compose_path: Path) -> None:
        """
        Write compose configuration to file.

        Args:
            compose_config: Docker compose configuration
            compose_path: Path to write the file
        """
        # Ensure directory exists
        compose_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with proper formatting
        with open(compose_path, "w") as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False, width=120)

        logger.info(f"Wrote docker-compose.yml to {compose_path}")

    def generate_env_file(self, env_vars: Dict[str, str], env_path: Path) -> None:
        """
        Generate .env file for sensitive environment variables.

        Args:
            env_vars: Environment variables
            env_path: Path to .env file
        """
        with open(env_path, "w") as f:
            for key, value in env_vars.items():
                # Quote values that contain spaces
                if " " in value:
                    value = f'"{value}"'
                f.write(f"{key}={value}\n")

        logger.info(f"Wrote .env file to {env_path}")
