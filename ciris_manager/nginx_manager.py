"""
NGINX configuration management for CIRIS agents.

This module handles complete nginx configuration generation including
all routes for GUI, manager API, and dynamic agent routes.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional
import logging
import json

from ciris_manager.models import AgentInfo
from ciris_manager.logging_config import log_nginx_operation

logger = logging.getLogger("ciris_manager.nginx")


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
        logger.info(f"Checking nginx config directory: {self.config_dir}")
        if not self.config_dir.exists():
            logger.error(f"Nginx config directory does not exist: {self.config_dir}")
            raise RuntimeError(
                f"Nginx config directory {self.config_dir} does not exist. "
                "This should be created by deployment scripts with proper permissions."
            )

        # Check if we can write to the directory
        logger.info(f"Testing write permissions for nginx directory: {self.config_dir}")
        test_file = self.config_dir / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            logger.info(f"Write permissions OK for {self.config_dir}")
        except PermissionError as e:
            import pwd

            logger.error(f"No write permission for nginx directory: {self.config_dir}")
            try:
                current_user = pwd.getpwuid(os.getuid()).pw_name
            except Exception:
                current_user = f"uid={os.getuid()}"
            logger.error(f"Current user: {current_user}")
            logger.error(f"Directory owner: {self.config_dir.stat().st_uid}")
            logger.error(f"Directory permissions: {oct(self.config_dir.stat().st_mode)}")
            raise RuntimeError(f"No write permission for nginx directory {self.config_dir}: {e}")

    def update_config(self, agents: List[AgentInfo]) -> bool:
        """
        Update nginx configuration with current agent list.

        Args:
            agents: List of agent dictionaries with id, name, port info

        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()

        # Log the operation start with detailed agent info
        agent_info = [{"id": a.agent_id, "name": a.agent_name, "port": a.api_port} for a in agents]
        logger.info(f"Starting nginx config update for {len(agents)} agents")
        logger.debug(f"Agents to configure: {json.dumps(agent_info)}")

        try:
            # 1. Generate new config
            logger.debug("Generating new nginx configuration...")
            new_config = self.generate_config(agents)
            config_lines = len(new_config.splitlines())

            # Log agent routes that will be created
            for agent in agents:
                if agent.has_port:
                    logger.debug(
                        f"Will create routes for {agent.agent_id}: /api/{agent.agent_id}/* -> port {agent.api_port}"
                    )

            # 2. Write to temporary file
            try:
                logger.debug(
                    f"Writing {len(new_config)} bytes ({config_lines} lines) to: {self.new_config_path}"
                )
                self.new_config_path.write_text(new_config)
                logger.info(f"Generated new nginx config with {len(agents)} agents")
            except PermissionError as e:
                import pwd

                logger.error(
                    f"Permission denied writing nginx config to {self.new_config_path}: {e}"
                )
                try:
                    current_user = pwd.getpwuid(os.getuid()).pw_name
                    current_uid = os.getuid()
                    current_gid = os.getgid()
                except Exception:
                    current_user = "unknown"
                    current_uid = os.getuid()
                    current_gid = os.getgid()

                logger.error(f"Running as: {current_user} (uid={current_uid}, gid={current_gid})")
                logger.error(f"Directory: {self.config_dir}")
                logger.error(f"Directory exists: {self.config_dir.exists()}")
                if self.config_dir.exists():
                    stat = self.config_dir.stat()
                    logger.error(f"Directory owner: uid={stat.st_uid}, gid={stat.st_gid}")
                    logger.error(f"Directory perms: {oct(stat.st_mode)}")

                logger.error(
                    f"Ensure the CIRISManager process has write access to {self.config_dir}"
                )
                return False

            # 3. Backup current config if it exists
            if self.config_path.exists():
                shutil.copy2(self.config_path, self.backup_path)
                logger.info("Backed up current nginx config")

            # 4. Write in-place to preserve inode for Docker bind mounts
            # CRITICAL: Do NOT use os.rename() as it creates a new inode
            # which breaks Docker bind mounts. Write directly to the file.
            try:
                with open(self.config_path, "w") as f:
                    with open(self.new_config_path, "r") as new_f:
                        f.write(new_f.read())
                logger.info(
                    "Updated nginx config in-place (preserving inode for Docker bind mount)"
                )

                # Clean up temp file
                self.new_config_path.unlink()
            except Exception as e:
                logger.error(f"Failed to write nginx config in-place: {e}")
                return False

            # 5. Validate and reload nginx
            logger.info("Validating nginx configuration...")
            if self._validate_config():
                logger.info("Nginx configuration validated successfully")

                logger.info("Reloading nginx...")
                if self._reload_nginx():
                    duration_ms = int((time.time() - start_time) * 1000)
                    logger.info(f"✅ Nginx config updated successfully in {duration_ms}ms")

                    # Log success with structured data
                    log_nginx_operation(
                        operation="update_config",
                        success=True,
                        details={
                            "agent_count": len(agents),
                            "config_size": len(new_config),
                            "duration_ms": duration_ms,
                            "agents": agent_info,
                        },
                    )
                    return True
                else:
                    logger.error("❌ Nginx reload failed, rolling back")
                    self._rollback()
                    log_nginx_operation(
                        operation="update_config",
                        success=False,
                        error="Nginx reload failed after config update",
                    )
                    return False
            else:
                logger.error("❌ Nginx validation failed, rolling back")
                self._rollback()
                log_nginx_operation(
                    operation="update_config", success=False, error="Nginx config validation failed"
                )
                return False

        except Exception as e:
            logger.error(f"❌ Failed to update nginx config: {e}", exc_info=True)
            self._rollback()
            log_nginx_operation(operation="update_config", success=False, error=str(e))
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
    # Redirect HTTP to HTTPS (with health check exception)
    server {
        listen 80;
        server_name agents.ciris.ai;
        
        # Health check endpoint (must be available on HTTP for Docker health check)
        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
        
        # Redirect everything else to HTTPS
        location / {
            return 301 https://$server_name$request_uri;
        }
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
        
        # Manager UI static files (HTML, JS, CSS)
        location /manager/ {
            root /home/ciris/static;
            try_files $uri $uri/ /manager/index.html;
            
            # Add appropriate headers
            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
        }
        
        # Public Dashboard (no auth required)
        location /dashboard/ {
            root /home/ciris/static;
            try_files $uri $uri/ /dashboard/index.html;
            
            # Add appropriate headers
            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
            add_header Cache-Control "public, max-age=300";
        }
        
        # Telemetry SDK for dashboard
        location /static/ciristelemetry-sdk.min.js {
            alias /home/ciris/static/sdk/ciristelemetry-sdk.min.js;
            add_header Content-Type "application/javascript";
            add_header Cache-Control "public, max-age=3600";
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
        
        # Alternative callback path (frontend compatibility)
        location /manager/callback {
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
        
        # Public telemetry endpoints (no auth required)
        location /telemetry/public/ {
            proxy_pass http://manager/manager/v1/telemetry/public/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Enable CORS for public API
            add_header Access-Control-Allow-Origin "*";
            add_header Access-Control-Allow-Methods "GET, OPTIONS";
            add_header Access-Control-Allow-Headers "Content-Type, Authorization";
        }
"""

        # === AGENT API ROUTES - Must come before root location ===
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
        
        # {agent.agent_name} Documentation endpoints (FastAPI automatic)
        location ~ ^/api/{agent.agent_id}/(docs|redoc|openapi\\.json)$ {{
            proxy_pass http://agent_{agent.agent_id}/$1$is_args$args;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }}
        
        # {agent.agent_name} API routes
        location ~ ^/api/{agent.agent_id}/v1/(.*)$ {{
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

        # OAuth GUI callback routes - must come before root catch-all
        server += """
        # GUI OAuth callback routes (for post-auth redirect from agents)
        location ~ ^/oauth/([^/]+)/([^/]+)/callback {
            proxy_pass http://agent_gui/oauth/$1/$2/callback$is_args$args;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        # Root and all GUI routes - Agent GUI (login page) handles routing internally
        # This MUST be last as it catches all unmatched routes
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
    }
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

        # First try reload - it's faster and doesn't drop connections
        result = subprocess.run(
            ["docker", "exec", self.container_name, "nginx", "-s", "reload"], capture_output=True
        )

        if result.returncode != 0:
            stderr = result.stderr.decode()
            stdout = result.stdout.decode()
            logger.warning(f"Nginx reload failed with return code {result.returncode}")
            logger.warning(f"STDERR: {stderr}")
            logger.warning(f"STDOUT: {stdout}")

            # If reload fails, try restart as fallback
            logger.info("Attempting nginx container restart as fallback")
            restart_result = subprocess.run(
                ["docker", "restart", self.container_name], capture_output=True
            )

            if restart_result.returncode != 0:
                logger.error(f"Nginx restart also failed: {restart_result.stderr.decode()}")
                return False
            else:
                logger.info("Nginx container restarted successfully")
                # Give nginx a moment to start up
                time.sleep(2)
                return True

        # Log any warnings from nginx (like the http2 deprecation)
        if result.stderr:
            logger.warning(f"Nginx reload warnings: {result.stderr.decode()}")

        return True

    def _rollback(self) -> None:
        """Rollback to previous configuration."""
        if self.backup_path.exists():
            try:
                # Write in-place to preserve inode for Docker bind mounts
                with open(self.config_path, "w") as f:
                    with open(self.backup_path, "r") as backup_f:
                        f.write(backup_f.read())
                self._reload_nginx()
                logger.info("Rolled back to previous nginx config (in-place)")
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
