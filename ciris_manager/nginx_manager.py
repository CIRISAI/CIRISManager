"""
NGINX configuration management for CIRIS agents.

This module handles complete nginx configuration generation including
all routes for GUI, manager API, and dynamic agent routes.

Includes crash loop detection and automatic rollback for nginx container.
"""

import os
import shutil
import subprocess
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import logging
import json

from ciris_manager.models import AgentInfo
from ciris_manager.logging_config import log_nginx_operation

logger = logging.getLogger("ciris_manager.nginx")

# Constants for crash loop detection
NGINX_CRASH_LOOP_MAX_ROLLBACKS = 3
NGINX_CONTAINER_START_TIMEOUT = 10  # seconds to wait for container to stabilize


class NginxManager:
    """Manages nginx configuration using template generation."""

    def __init__(
        self,
        config_dir: str = "/home/ciris/nginx",
        container_name: str = "ciris-nginx",
        hostname: str = "agents.ciris.ai",
    ):
        """
        Initialize nginx manager.

        Args:
            config_dir: Directory for nginx configuration files
            container_name: Name of the nginx Docker container
            hostname: Hostname for this nginx instance (e.g., agents.ciris.ai, scoutapi.ciris.ai)
        """
        self.config_dir = Path(config_dir)
        self.container_name = container_name
        self.hostname = hostname
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

    def _create_timestamped_backup(self) -> Optional[Path]:
        """
        Create a timestamped backup of the current nginx config.

        Returns:
            Path to backup file if created, None if no config to backup
        """
        if not self.config_path.exists():
            logger.debug("No existing config to backup")
            return None

        # Check if current config is empty (nothing to backup)
        if self.config_path.stat().st_size == 0:
            logger.warning("Current nginx config is empty, skipping backup")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.config_dir / f"nginx.conf.backup.{timestamp}"

        try:
            shutil.copy2(self.config_path, backup_file)
            logger.info(f"📦 Created timestamped backup: {backup_file.name}")
            return backup_file
        except Exception as e:
            logger.error(f"Failed to create timestamped backup: {e}")
            return None

    def _get_backup_files(self) -> List[Path]:
        """
        Get all backup files sorted by timestamp (newest first).

        Returns:
            List of backup file paths, newest first
        """
        backups = list(self.config_dir.glob("nginx.conf.backup.*"))
        # Sort by modification time, newest first
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return backups

    def _cleanup_old_backups(self, keep_count: int = 10) -> None:
        """
        Remove old backup files, keeping only the most recent ones.

        Args:
            keep_count: Number of recent backups to keep
        """
        backups = self._get_backup_files()
        if len(backups) > keep_count:
            for old_backup in backups[keep_count:]:
                try:
                    old_backup.unlink()
                    logger.debug(f"Removed old backup: {old_backup.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {old_backup.name}: {e}")

    def _is_nginx_healthy(self, timeout: int = NGINX_CONTAINER_START_TIMEOUT) -> bool:
        """
        Check if the nginx container is running and healthy.

        Args:
            timeout: Seconds to wait for container to stabilize

        Returns:
            True if nginx is healthy, False otherwise
        """
        try:
            # Wait a moment for container to stabilize after restart/reload
            time.sleep(2)

            # Check container status
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", self.container_name],
                capture_output=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error(f"Failed to inspect nginx container: {result.stderr.decode()}")
                return False

            status = result.stdout.decode().strip()

            if status == "running":
                # Also verify nginx can validate its config
                validate_result = subprocess.run(
                    ["docker", "exec", self.container_name, "nginx", "-t"],
                    capture_output=True,
                    timeout=10,
                )
                if validate_result.returncode == 0:
                    logger.debug("Nginx container is healthy")
                    return True
                else:
                    logger.warning(f"Nginx config invalid: {validate_result.stderr.decode()}")
                    return False
            elif status == "restarting":
                logger.warning("Nginx container is in restart loop")
                return False
            else:
                logger.warning(f"Nginx container status: {status}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Timeout checking nginx container health")
            return False
        except Exception as e:
            logger.error(f"Error checking nginx health: {e}")
            return False

    def _rollback_to_backup(self, backup_path: Path) -> bool:
        """
        Rollback to a specific backup file.

        Args:
            backup_path: Path to the backup file to restore

        Returns:
            True if rollback successful and nginx is healthy
        """
        if not backup_path.exists():
            logger.error(f"Backup file does not exist: {backup_path}")
            return False

        try:
            logger.info(f"🔄 Rolling back to: {backup_path.name}")

            # Write backup content in-place to preserve inode
            with open(self.config_path, "w") as f:
                with open(backup_path, "r") as backup_f:
                    f.write(backup_f.read())

            # Reload nginx
            reload_result = subprocess.run(
                ["docker", "exec", self.container_name, "nginx", "-s", "reload"],
                capture_output=True,
                timeout=30,
            )

            if reload_result.returncode != 0:
                # If reload fails, try restarting the container
                logger.warning("Nginx reload failed, trying container restart")
                restart_result = subprocess.run(
                    ["docker", "restart", self.container_name],
                    capture_output=True,
                    timeout=60,
                )
                if restart_result.returncode != 0:
                    logger.error(f"Container restart failed: {restart_result.stderr.decode()}")
                    return False

            # Check if nginx is now healthy
            if self._is_nginx_healthy():
                logger.info(f"✅ Successfully rolled back to {backup_path.name}")
                return True
            else:
                logger.warning(f"Nginx not healthy after rollback to {backup_path.name}")
                return False

        except Exception as e:
            logger.error(f"Rollback to {backup_path.name} failed: {e}")
            return False

    def _handle_nginx_crash_loop(self) -> tuple[bool, str]:
        """
        Handle nginx crash loop by trying progressively older backups.

        Attempts to rollback through up to NGINX_CRASH_LOOP_MAX_ROLLBACKS backups
        until nginx starts successfully.

        Returns:
            Tuple of (success: bool, error_message: str)
        """
        backups = self._get_backup_files()

        if not backups:
            error_msg = "No backup files available to rollback to"
            logger.error(f"❌ {error_msg}")
            return False, error_msg

        logger.warning(
            f"🔄 Nginx crash loop detected! Attempting rollback through "
            f"{min(len(backups), NGINX_CRASH_LOOP_MAX_ROLLBACKS)} backups..."
        )

        for i, backup in enumerate(backups[:NGINX_CRASH_LOOP_MAX_ROLLBACKS]):
            logger.info(f"Rollback attempt {i + 1}/{NGINX_CRASH_LOOP_MAX_ROLLBACKS}: {backup.name}")

            if self._rollback_to_backup(backup):
                logger.info(f"✅ Nginx recovered using backup: {backup.name}")
                return True, ""

            logger.warning(f"Backup {backup.name} did not fix the issue, trying next...")

        error_msg = (
            f"Failed to recover nginx after {NGINX_CRASH_LOOP_MAX_ROLLBACKS} rollback attempts. "
            "Manual intervention required!"
        )
        logger.critical(f"❌ {error_msg}")
        return False, error_msg

    def update_config(self, agents: List[AgentInfo]) -> tuple[bool, str]:
        """
        Update nginx configuration with current agent list.

        Args:
            agents: List of agent dictionaries with id, name, port info

        Returns:
            Tuple of (success: bool, error_message: str)
            error_message is empty string on success
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

                error_msg = f"Permission denied writing to {self.new_config_path}"
                logger.error(
                    f"Ensure the CIRISManager process has write access to {self.config_dir}"
                )
                return False, error_msg

            # 3. Create timestamped backup before making changes
            backup_file = self._create_timestamped_backup()
            if backup_file:
                logger.info(f"Created backup before update: {backup_file.name}")

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
                error_msg = f"Failed to write nginx config in-place: {e}"
                logger.error(error_msg)
                return False, error_msg

            # 5. Validate and reload nginx
            logger.info("Validating nginx configuration...")
            if self._validate_config():
                logger.info("Nginx configuration validated successfully")

                logger.info("Reloading nginx...")
                if self._reload_nginx():
                    # Verify nginx is actually healthy after reload
                    if self._is_nginx_healthy():
                        duration_ms = int((time.time() - start_time) * 1000)
                        logger.info(f"✅ Nginx config updated successfully in {duration_ms}ms")

                        # Clean up old backups after successful update
                        self._cleanup_old_backups(keep_count=10)

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
                        return True, ""
                    else:
                        # Nginx reload succeeded but container is unhealthy (crash loop)
                        logger.error("❌ Nginx reload succeeded but container is unhealthy")
                        recovered, recovery_msg = self._handle_nginx_crash_loop()
                        if recovered:
                            error_msg = "Config update caused crash loop, recovered using backup"
                            logger.warning(error_msg)
                        else:
                            error_msg = f"Nginx crash loop, recovery failed: {recovery_msg}"
                        log_nginx_operation(
                            operation="update_config",
                            success=False,
                            error=error_msg,
                        )
                        return False, error_msg
                else:
                    # Nginx reload command failed - try crash loop recovery
                    logger.error("❌ Nginx reload failed, attempting crash loop recovery")
                    recovered, recovery_msg = self._handle_nginx_crash_loop()
                    if recovered:
                        error_msg = "Nginx reload failed, recovered using backup"
                        logger.warning(error_msg)
                    else:
                        error_msg = f"Nginx reload failed, recovery failed: {recovery_msg}"
                    log_nginx_operation(
                        operation="update_config",
                        success=False,
                        error=error_msg,
                    )
                    return False, error_msg
            else:
                # Config validation failed - try crash loop recovery
                validation_error = self._get_validation_error()
                logger.error(f"❌ Nginx validation failed: {validation_error}")

                # Check if nginx is in crash loop and try to recover
                if not self._is_nginx_healthy():
                    logger.warning("Nginx unhealthy after validation failure, attempting recovery")
                    recovered, recovery_msg = self._handle_nginx_crash_loop()
                    if recovered:
                        error_msg = (
                            f"Validation failed ({validation_error}), recovered using backup"
                        )
                    else:
                        error_msg = f"Validation failed ({validation_error}), recovery failed: {recovery_msg}"
                else:
                    # Nginx still healthy, just the new config is bad
                    self._rollback()
                    error_msg = f"Nginx config validation failed: {validation_error}"

                log_nginx_operation(operation="update_config", success=False, error=error_msg)
                return False, error_msg

        except Exception as e:
            error_msg = f"Exception during nginx config update: {e}"
            logger.error(f"❌ {error_msg}", exc_info=True)

            # Try crash loop recovery on any exception
            if not self._is_nginx_healthy():
                recovered, recovery_msg = self._handle_nginx_crash_loop()
                if not recovered:
                    error_msg = f"{error_msg} (recovery also failed: {recovery_msg})"
            else:
                self._rollback()

            log_nginx_operation(operation="update_config", success=False, error=error_msg)
            return False, error_msg

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

    # WebSocket connection upgrade mapping
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

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

    def _is_main_server(self) -> bool:
        """Check if this is the main server (agents.ciris.ai)."""
        return self.hostname == "agents.ciris.ai"

    def _generate_upstreams(self, agents: List[AgentInfo]) -> str:
        """Generate upstream blocks for all services."""
        upstreams = "    # === UPSTREAMS ===\n"

        # Main server upstreams (GUI, Manager, CIRISLens, eee.ciris.ai)
        if self._is_main_server():
            upstreams += """    # Agent GUI upstream (multi-tenant container from CIRISAgent)
    upstream agent_gui {
        server 127.0.0.1:3000;
    }

    # Manager API upstream
    upstream manager {
        server 127.0.0.1:8888;
    }

    # CIRISLens API upstream
    upstream cirislens {
        server 127.0.0.1:8000;
    }

    # eee.ciris.ai upstreams
    upstream oauth2_proxy {
        server 127.0.0.1:4180;
    }

    upstream engine {
        server 127.0.0.1:8080;
    }
"""

        # Add agent upstreams (all servers)
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
        """Generate server block with routes (main-only or agent-only)."""

        is_main = self._is_main_server()

        server = f"""    # === {'MAIN' if is_main else 'AGENT'} SERVER ({self.hostname}) ===
    # Redirect HTTP to HTTPS (with health check exception)
    server {{
        listen 80;
        server_name {self.hostname};

        # Health check endpoint (must be available on HTTP for Docker health check)
        location /health {{
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }}

        # Redirect everything else to HTTPS
        location / {{
            return 301 https://$server_name$request_uri;
        }}
    }}

    # HTTPS Server
    server {{
        listen 443 ssl http2;
        server_name {self.hostname};

        # SSL configuration
        ssl_certificate /etc/letsencrypt/live/{self.hostname}/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/{self.hostname}/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # Health check endpoint
        location /health {{
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }}
"""

        # Main server only: Manager UI, Jailbreaker, Agent GUI, CIRISLens
        if is_main:
            server += """
        # Manager UI static files (HTML, JS, CSS)
        location /manager/ {
            root /home/ciris/static;
            try_files $uri $uri/ /manager/index.html;

            # Add appropriate headers
            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
        }

        # Jailbreaker static files (HTML, JS, CSS)
        location /jailbreaker/ {
            root /home/ciris/static;
            try_files $uri $uri/ /jailbreaker/index.html;

            # Add appropriate headers
            add_header X-Frame-Options "SAMEORIGIN";
            add_header X-Content-Type-Options "nosniff";
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

        # CIRISLens Grafana dashboards
        location = /lens {
            return 301 /lens/;
        }

        # Grafana WebSocket endpoint (for live metrics)
        location /lens/api/live/ws {
            proxy_pass http://127.0.0.1:3001/api/live/ws;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 86400s;
        }

        # CIRISLens Log Ingestion API (specific route - must be before /lens/api/ catch-all)
        location /lens/api/v1/logs/ {
            proxy_pass http://127.0.0.1:8000/api/v1/logs/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # CIRISLens Admin API (specific route)
        location /lens/api/admin/ {
            proxy_pass http://127.0.0.1:8000/api/admin/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Grafana API (everything else under /lens/api/ goes to Grafana)
        location /lens/api/ {
            proxy_pass http://127.0.0.1:3001/api/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Main Grafana UI
        location /lens/ {
            proxy_pass http://127.0.0.1:3001/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Server $host;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;

            # WebSocket support for live metrics
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
        }

        # CIRISLens Admin UI (OAuth protected)
        location /lens/admin/ {
            proxy_pass http://127.0.0.1:8000/admin/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
"""

        # === AGENT API ROUTES (all servers) ===
        # Use agent-specific routes for all servers (main and remote)
        # This ensures OAuth callbacks and multi-agent support work correctly
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

            # Disable buffering for SSE/streaming responses
            proxy_buffering off;
            proxy_cache off;
            proxy_set_header X-Accel-Buffering no;

            # WebSocket support
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }}
"""

        # Main server only: GUI OAuth callbacks, Grafana assets, root location
        if is_main:
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

        # Grafana public assets (fonts, images, plugins, etc.) - must come before root catch-all
        location /public/ {
            proxy_pass http://127.0.0.1:3001/public/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Cache static assets
            expires 1d;
            add_header Cache-Control "public, immutable";
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
"""
        else:
            # Remote servers: simple 404 for root
            server += """
        # Remote server - no GUI, return 404 for unmatched routes
        location / {
            return 404 "Agent server - API only\\n";
            add_header Content-Type text/plain;
        }
"""

        server += "    }\n"

        # NOTE: Legacy eee.ciris.ai server block removed
        # The new infrastructure uses Cloudflare for SSL termination
        # and doesn't require the eee.ciris.ai domain configuration

        server += "}\n"
        return server

    def deploy_remote_config(
        self, config_content: str, docker_client, container_name: str = "ciris-nginx"
    ) -> bool:
        """
        Deploy nginx config to remote server via Docker API.

        Args:
            config_content: The nginx configuration content
            docker_client: Docker client for the remote server
            container_name: Name of the nginx container on remote server

        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()
        config_size = len(config_content)
        config_lines = len(config_content.splitlines())

        logger.info(f"[Remote Deploy] Starting deployment to {container_name} on {self.hostname}")
        logger.info(f"[Remote Deploy] Config size: {config_size} bytes, {config_lines} lines")
        logger.debug(f"[Remote Deploy] First 300 chars:\n{config_content[:300]}")

        try:
            # Get the nginx container
            logger.debug(f"[Remote Deploy] Getting container: {container_name}")
            container = docker_client.containers.get(container_name)
            logger.info(
                f"[Remote Deploy] ✓ Found container {container_name} (status: {container.status})"
            )

            # Write config to container using exec
            # We write to a temp file first, validate, then move to final location
            temp_path = "/tmp/nginx.conf.new"
            final_path = "/etc/nginx/nginx.conf"

            # Step 1: Write config to temp file using base64 encoding
            # Base64 encoding avoids all shell escaping issues with quotes, newlines, etc.
            logger.info(f"[Remote Deploy] Step 1/4: Writing config to {temp_path}")
            encoded_config = base64.b64encode(config_content.encode()).decode()
            write_cmd = f"sh -c 'echo {encoded_config} | base64 -d > {temp_path}'"
            logger.debug(
                f"[Remote Deploy] Encoded config size: {len(encoded_config)} bytes (base64)"
            )

            exec_result = container.exec_run(write_cmd)

            if exec_result.exit_code != 0:
                error_msg = exec_result.output.decode()
                logger.error(f"[Remote Deploy] ✗ Step 1 failed: Write to {temp_path}")
                logger.error(f"[Remote Deploy] Exit code: {exec_result.exit_code}")
                logger.error(f"[Remote Deploy] Error output:\n{error_msg}")
                return False

            logger.info(f"[Remote Deploy] ✓ Step 1 complete: Config written to {temp_path}")

            # Verify what was written by reading it back
            logger.debug("[Remote Deploy] Verifying written config...")
            verify_cmd = f"head -20 {temp_path}"
            verify_result = container.exec_run(verify_cmd)
            if verify_result.exit_code == 0:
                logger.debug(
                    f"[Remote Deploy] First 20 lines of written config:\n{verify_result.output.decode()}"
                )
            else:
                logger.warning(
                    f"[Remote Deploy] Could not verify written config: {verify_result.output.decode()}"
                )

            # Step 2: Validate config
            logger.info("[Remote Deploy] Step 2/4: Validating config with nginx -t")
            validate_cmd = f"nginx -t -c {temp_path}"
            exec_result = container.exec_run(validate_cmd)

            if exec_result.exit_code != 0:
                error_output = exec_result.output.decode()
                logger.error("[Remote Deploy] ✗ Step 2 failed: Nginx validation")
                logger.error(f"[Remote Deploy] Exit code: {exec_result.exit_code}")
                logger.error(f"[Remote Deploy] Validation error:\n{error_output}")

                # Try to show the problematic line from the config
                if "line" in error_output:
                    import re

                    line_match = re.search(r"line (\d+)", error_output)
                    if line_match:
                        line_num = int(line_match.group(1))
                        logger.error(f"[Remote Deploy] Problem around line {line_num}:")
                        lines = config_content.splitlines()
                        start = max(0, line_num - 3)
                        end = min(len(lines), line_num + 2)
                        for i in range(start, end):
                            prefix = ">>>" if i == line_num - 1 else "   "
                            logger.error(f"[Remote Deploy]   {prefix} {i+1:4d}: {lines[i]}")

                # Clean up temp file
                logger.debug(f"[Remote Deploy] Cleaning up {temp_path}")
                container.exec_run(f"rm -f {temp_path}")
                return False

            logger.info("[Remote Deploy] ✓ Step 2 complete: Config validation passed")
            if exec_result.output:
                logger.debug(f"[Remote Deploy] Validation output:\n{exec_result.output.decode()}")

            # Step 3: Write directly to final location using cat
            # This works even when the file is open, unlike cp/mv
            logger.info(f"[Remote Deploy] Step 3/4: Writing config to {final_path}")
            write_final_cmd = f"cat {temp_path} > {final_path}"
            exec_result = container.exec_run(["sh", "-c", write_final_cmd])

            if exec_result.exit_code != 0:
                error_msg = exec_result.output.decode()
                logger.error("[Remote Deploy] ✗ Step 3 failed: Write to final location")
                logger.error(f"[Remote Deploy] Exit code: {exec_result.exit_code}")
                logger.error(f"[Remote Deploy] Error output:\n{error_msg}")
                # Clean up temp file
                container.exec_run(f"rm -f {temp_path}")
                return False

            logger.info(f"[Remote Deploy] ✓ Step 3 complete: Config written to {final_path}")

            # Clean up temp file
            logger.debug(f"[Remote Deploy] Cleaning up {temp_path}")
            container.exec_run(f"rm -f {temp_path}")

            # Step 4: Reload nginx
            logger.info("[Remote Deploy] Step 4/4: Reloading nginx")
            reload_cmd = "nginx -s reload"
            exec_result = container.exec_run(reload_cmd)

            if exec_result.exit_code != 0:
                error_msg = exec_result.output.decode()
                logger.error("[Remote Deploy] ✗ Step 4 failed: Nginx reload")
                logger.error(f"[Remote Deploy] Exit code: {exec_result.exit_code}")
                logger.error(f"[Remote Deploy] Error output:\n{error_msg}")
                return False

            logger.info("[Remote Deploy] ✓ Step 4 complete: Nginx reloaded")
            if exec_result.output:
                logger.debug(f"[Remote Deploy] Reload output:\n{exec_result.output.decode()}")

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"[Remote Deploy] ✅ Successfully deployed config to {self.hostname} in {duration_ms}ms"
            )

            # Log success with structured data
            log_nginx_operation(
                operation="deploy_remote_config",
                success=True,
                details={
                    "hostname": self.hostname,
                    "container": container_name,
                    "config_size": config_size,
                    "config_lines": config_lines,
                    "duration_ms": duration_ms,
                },
            )
            return True

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                f"[Remote Deploy] ❌ Failed to deploy remote nginx config after {duration_ms}ms"
            )
            logger.error(f"[Remote Deploy] Exception: {e}", exc_info=True)
            log_nginx_operation(
                operation="deploy_remote_config",
                success=False,
                error=str(e),
                details={"hostname": self.hostname, "container": container_name},
            )
            return False

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

        # Store the last validation error for retrieval
        self._last_validation_error = result.stderr.decode() if result.returncode != 0 else ""

        if result.returncode != 0:
            logger.error(f"Nginx validation failed: {self._last_validation_error}")
            return False

        return True

    def _get_validation_error(self) -> str:
        """Get the last nginx validation error message."""
        return getattr(self, "_last_validation_error", "Unknown validation error")

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
        """Rollback to the most recent backup configuration."""
        backups = self._get_backup_files()

        if backups:
            # Try the most recent backup
            if self._rollback_to_backup(backups[0]):
                logger.info(f"Rolled back to most recent backup: {backups[0].name}")
            else:
                logger.error("Rollback to most recent backup failed")
        elif self.backup_path.exists():
            # Fallback to legacy backup file if exists
            try:
                with open(self.config_path, "w") as f:
                    with open(self.backup_path, "r") as backup_f:
                        f.write(backup_f.read())
                self._reload_nginx()
                logger.info("Rolled back to legacy backup (nginx.conf.backup)")
            except Exception as e:
                logger.error(f"Legacy rollback failed: {e}")
        else:
            logger.error("No backup files available for rollback")

        # Clean up temporary file
        if self.new_config_path.exists():
            self.new_config_path.unlink()

    def remove_agent_routes(self, agent_id: str, agents: List[AgentInfo]) -> tuple[bool, str]:
        """
        Remove routes for a specific agent by regenerating config without it.

        Args:
            agent_id: ID of agent to remove
            agents: Current list of ALL agents (will filter out the one to remove)

        Returns:
            Tuple of (success: bool, error_message: str)
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
