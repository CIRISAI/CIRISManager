"""
NGINX configuration management for CIRIS agents.

This module handles complete nginx configuration generation including
all routes for GUI, manager API, and dynamic agent routes.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional
import logging

from ciris_manager.models import AgentInfo

logger = logging.getLogger(__name__)


class NginxManager:
    """Manages nginx configuration using template generation."""

    def __init__(self, config_dir: str = "/home/ciris/nginx", container_name: str = "ciris-nginx"):
        """
        Initialize nginx manager.

        Args:
            config_dir: Directory for nginx configuration files
            container_name: Name of the nginx Docker container
        """
        self.config_dir = Path(config_dir)
        self.container_name = container_name
        self.config_path = self.config_dir / "nginx.conf"
        self.new_config_path = self.config_dir / "nginx.conf.new"
        self.backup_path = self.config_dir / "nginx.conf.backup"

        # Verify directory exists but don't try to create it
        # The directory should be created by deployment/docker setup
        if not self.config_dir.exists():
            raise RuntimeError(
                f"Nginx config directory {self.config_dir} does not exist. "
                "This should be created by deployment scripts with proper permissions."
            )

    def update_config(self, agents: List[AgentInfo]) -> bool:
        """
        Update nginx configuration with current agent list.

        Args:
            agents: List of agent dictionaries with id, name, port info

        Returns:
            True if successful, False otherwise
        """
        try:
            # 1. Generate new config
            new_config = self.generate_config(agents)

            # 2. Write to temporary file
            try:
                self.new_config_path.write_text(new_config)
                logger.info(f"Generated new nginx config with {len(agents)} agents")
            except PermissionError as e:
                logger.error(
                    f"Permission denied writing nginx config to {self.new_config_path}: {e}"
                )
                logger.error(
                    f"Ensure the CIRISManager process has write access to {self.config_dir}"
                )
                return False

            # 3. Backup current config if it exists
            if self.config_path.exists():
                shutil.copy2(self.config_path, self.backup_path)
                logger.info("Backed up current nginx config")

            # 4. Atomic replace
            os.rename(self.new_config_path, self.config_path)
            logger.info("Installed new nginx config")

            # 5. Validate and reload nginx
            if self._validate_config():
                if self._reload_nginx():
                    logger.info("Nginx reloaded successfully")
                    return True
                else:
                    logger.error("Nginx reload failed, rolling back")
                    self._rollback()
                    return False
            else:
                logger.error("Nginx validation failed, rolling back")
                self._rollback()
                return False

        except Exception as e:
            logger.error(f"Failed to update nginx config: {e}")
            self._rollback()
            return False

    def generate_config(self, agents: List[AgentInfo]) -> str:
        """
        Generate complete nginx configuration from agent list.

        Args:
            agents: List of agent dictionaries

        Returns:
            Complete nginx.conf content
        """
        config = self._generate_base_config()
        config += self._generate_upstreams(agents)
        config += self._generate_server_block(agents)
        return config

    def _generate_base_config(self) -> str:
        """Generate base nginx configuration."""
        return """events {
    worker_connections 1024;
}

http {
    # Default MIME types and settings
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Performance settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    
    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    
    # Size limits
    client_max_body_size 10M;
    
"""

    def _generate_upstreams(self, agents: List[AgentInfo]) -> str:
        """Generate upstream blocks for all services."""
        # When nginx runs in host network mode, use localhost
        # This is the default for production deployments
        upstreams = """    # === UPSTREAMS ===
    # Agent GUI upstream (multi-tenant container from CIRISAgent)
    upstream agent_gui {
        server 127.0.0.1:3000;
    }
    
    # Manager API upstream  
    upstream manager {
        server 127.0.0.1:8888;
    }
"""

        # Add agent upstreams
        if agents:
            upstreams += "\n    # Agent upstreams\n"
            for agent in agents:
                # Skip agents without valid ports
                if not agent.has_port:
                    logger.warning(f"Skipping agent {agent.agent_id} - no valid port")
                    continue

                # Use localhost for host network mode (production default)
                upstreams += f"""    upstream agent_{agent.agent_id} {{
        server 127.0.0.1:{agent.api_port};
    }}
"""

        return upstreams + "\n"

    def _generate_server_block(self, agents: List[AgentInfo]) -> str:
        """Generate main server block with all routes."""

        server = """    # === MAIN SERVER ===
    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name agents.ciris.ai;
        return 301 https://$server_name$request_uri;
    }

    # HTTPS Server
    server {
        listen 443 ssl http2;
        server_name agents.ciris.ai;
        
        # SSL configuration
        ssl_certificate /etc/letsencrypt/live/agents.ciris.ai/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/agents.ciris.ai/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        
        # Health check endpoint
        location /health {
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }
        
        # Root and all GUI routes - Next.js handles routing internally
        location / {
            proxy_pass http://agent_gui;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        # Manager UI routes
        location /manager/ {
            proxy_pass http://manager/manager/v1/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        # Agent GUI (multi-tenant container)
        location ~ ^/agent/([^/]+) {
            proxy_pass http://agent_gui;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_set_header Host $host;
            proxy_cache_bypass $http_upgrade;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        # Manager OAuth callback (for Google OAuth compatibility)
        location /manager/oauth/callback {
            proxy_pass http://manager/manager/oauth/callback;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        # Manager routes
        location /manager/v1/ {
            proxy_pass http://manager/manager/v1/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
"""

        # NO DEFAULT ROUTE - every API call must specify agent

        # Add agent-specific routes
        if agents:
            server += "\n        # === AGENT ROUTES ===\n"
            for agent in agents:
                # Skip agents without valid ports
                if not agent.has_port:
                    continue

                # OAuth callback route
                server += f"""
        # {agent.agent_name} OAuth callbacks
        location ~ ^/v1/auth/oauth/{agent.agent_id}/(.+)/callback$ {{
            proxy_pass http://agent_{agent.agent_id}/v1/auth/oauth/$1/callback$is_args$args;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }}
        
        # {agent.agent_name} API routes
        location ~ ^/api/{agent.agent_id}/(.*)$ {{
            proxy_pass http://agent_{agent.agent_id}/v1/$1$is_args$args;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
            
            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }}
"""

        server += """    }
}
"""
        return server

    def _validate_config(self) -> bool:
        """Validate nginx configuration using docker exec."""
        # Config is already at the right place via volume mount
        result = subprocess.run(
            [
                "docker",
                "exec",
                self.container_name,
                "nginx",
                "-t",
            ],
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(f"Nginx validation failed: {result.stderr.decode()}")
            return False

        return True

    def _reload_nginx(self) -> bool:
        """Reload nginx configuration."""
        logger.info(f"Reloading nginx container: {self.container_name}")
        # Just reload - config is already in place via volume mount
        result = subprocess.run(
            ["docker", "exec", self.container_name, "nginx", "-s", "reload"], capture_output=True
        )

        if result.returncode != 0:
            stderr = result.stderr.decode()
            stdout = result.stdout.decode()
            logger.error(f"Nginx reload failed with return code {result.returncode}")
            logger.error(f"STDERR: {stderr}")
            logger.error(f"STDOUT: {stdout}")
            return False

        # Log any warnings from nginx (like the http2 deprecation)
        if result.stderr:
            logger.warning(f"Nginx reload warnings: {result.stderr.decode()}")

        return True

    def _rollback(self) -> None:
        """Rollback to previous configuration."""
        if self.backup_path.exists():
            try:
                shutil.copy2(self.backup_path, self.config_path)
                self._reload_nginx()
                logger.info("Rolled back to previous nginx config")
            except Exception as e:
                logger.error(f"Rollback failed: {e}")

        # Clean up temporary file
        if self.new_config_path.exists():
            self.new_config_path.unlink()

    def remove_agent_routes(self, agent_id: str, agents: List[AgentInfo]) -> bool:
        """
        Remove routes for a specific agent by regenerating config without it.

        Args:
            agent_id: ID of agent to remove
            agents: Current list of ALL agents (will filter out the one to remove)

        Returns:
            True if successful
        """
        # Filter out the agent to remove
        remaining_agents = [a for a in agents if a.agent_id != agent_id]

        # Regenerate config with remaining agents
        return self.update_config(remaining_agents)

    def get_current_config(self) -> Optional[str]:
        """Get current nginx configuration."""
        if self.config_path.exists():
            return self.config_path.read_text()
        return None
