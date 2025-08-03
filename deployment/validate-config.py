#!/usr/bin/env python3
"""
CIRIS Manager Configuration Validator
Validates production configuration before deployment
"""

import sys
import os
import yaml
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ConfigValidator:
    def __init__(self, config_path: str, env_path: str = None):
        self.config_path = Path(config_path)
        self.env_path = Path(env_path) if env_path else None
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(self) -> Tuple[bool, List[str], List[str]]:
        """Validate configuration and return (success, errors, warnings)"""
        # Check file existence
        if not self.config_path.exists():
            self.errors.append(f"Configuration file not found: {self.config_path}")
            return False, self.errors, self.warnings

        # Load and validate YAML
        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
        except Exception as e:
            self.errors.append(f"Failed to parse YAML: {e}")
            return False, self.errors, self.warnings

        # Validate configuration sections
        self._validate_manager_config(config.get("manager", {}))
        self._validate_auth_config(config.get("auth", {}))
        self._validate_docker_config(config.get("docker", {}))
        self._validate_ports_config(config.get("ports", {}))
        self._validate_api_config(config.get("api", {}))
        self._validate_nginx_config(config.get("nginx", {}))
        self._validate_security_config(config.get("security", {}))

        # Validate environment file if provided
        if self.env_path:
            self._validate_environment()

        return len(self.errors) == 0, self.errors, self.warnings

    def _validate_manager_config(self, config: Dict[str, Any]):
        """Validate manager configuration section"""
        required = ["host", "port", "agents_directory"]
        for field in required:
            if field not in config:
                self.errors.append(f"Missing required field: manager.{field}")

        # Validate port
        port = config.get("port", 0)
        if not isinstance(port, int) or port < 1 or port > 65535:
            self.errors.append(f"Invalid port: {port}")

        # Check directories exist
        agents_dir = config.get("agents_directory")
        if agents_dir and not Path(agents_dir).exists():
            self.warnings.append(f"Agents directory does not exist: {agents_dir}")

    def _validate_auth_config(self, config: Dict[str, Any]):
        """Validate authentication configuration"""
        mode = config.get("mode", "disabled")

        if mode != "production":
            self.errors.append(
                f"Auth mode must be 'production' for production deployment, got: {mode}"
            )

        # Check JWT settings
        if "jwt_algorithm" not in config:
            self.warnings.append("JWT algorithm not specified, will use default")

    def _validate_docker_config(self, config: Dict[str, Any]):
        """Validate Docker configuration"""
        # Check Docker socket
        docker_socket = Path("/var/run/docker.sock")
        if not docker_socket.exists():
            self.errors.append("Docker socket not found at /var/run/docker.sock")

        # Validate registry
        registry = config.get("registry", "")
        if not registry:
            self.warnings.append("Docker registry not specified")

    def _validate_ports_config(self, config: Dict[str, Any]):
        """Validate port allocation configuration"""
        start = config.get("start", 0)
        end = config.get("end", 0)

        if start >= end:
            self.errors.append(f"Invalid port range: {start}-{end}")

        reserved = config.get("reserved", [])
        if not isinstance(reserved, list):
            self.errors.append("Reserved ports must be a list")

        # Check for conflicts
        for port in reserved:
            if start <= port <= end:
                self.warnings.append(f"Reserved port {port} is within allocation range")

    def _validate_api_config(self, config: Dict[str, Any]):
        """Validate API configuration"""
        cors_origins = config.get("cors_origins", [])
        if not cors_origins:
            self.warnings.append("No CORS origins configured")

        # Validate rate limiting
        rate_limit = config.get("rate_limit", {})
        if rate_limit.get("enabled", False):
            if "requests_per_minute" not in rate_limit:
                self.errors.append("Rate limiting enabled but requests_per_minute not set")

    def _validate_nginx_config(self, config: Dict[str, Any]):
        """Validate nginx configuration"""
        if config.get("enabled", False):
            # Check nginx is installed
            if not Path("/usr/sbin/nginx").exists():
                self.errors.append("Nginx enabled but nginx binary not found")

            # Check SSL paths
            ssl_cert = config.get("ssl_cert_path")
            ssl_key = config.get("ssl_key_path")

            if ssl_cert and not Path(ssl_cert).exists():
                self.warnings.append(f"SSL certificate not found: {ssl_cert}")
            if ssl_key and not Path(ssl_key).exists():
                self.warnings.append(f"SSL key not found: {ssl_key}")

    def _validate_security_config(self, config: Dict[str, Any]):
        """Validate security configuration"""
        if not config.get("force_https", False):
            self.warnings.append("HTTPS not enforced in production")

        allowed_hosts = config.get("allowed_hosts", [])
        if not allowed_hosts:
            self.warnings.append("No allowed hosts configured")

    def _validate_environment(self):
        """Validate environment file"""
        if not self.env_path.exists():
            self.errors.append(f"Environment file not found: {self.env_path}")
            return

        # Check permissions
        stat = self.env_path.stat()
        if stat.st_mode & 0o077:
            self.warnings.append(
                f"Environment file has insecure permissions: {oct(stat.st_mode)[-3:]}"
            )

        # Parse environment file
        env_vars = {}
        try:
            with open(self.env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key] = value
        except Exception as e:
            self.errors.append(f"Failed to parse environment file: {e}")
            return

        # Check required variables
        required_vars = [
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "MANAGER_JWT_SECRET",
            "CIRIS_MANAGER_CONFIG",
        ]

        for var in required_vars:
            if var not in env_vars:
                self.errors.append(f"Missing required environment variable: {var}")
            elif not env_vars[var] or "your-" in env_vars[var] or "CHANGE_THIS" in env_vars[var]:
                self.errors.append(f"Environment variable {var} not properly configured")

        # Check auth mode
        auth_mode = env_vars.get("CIRIS_AUTH_MODE", "")
        if auth_mode and auth_mode != "production":
            self.errors.append(f"CIRIS_AUTH_MODE must be 'production', got: {auth_mode}")


def main():
    """Main validation function"""
    import argparse

    parser = argparse.ArgumentParser(description="Validate CIRIS Manager configuration")
    parser.add_argument("config", help="Path to config.yml")
    parser.add_argument("--env", help="Path to environment file")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    validator = ConfigValidator(args.config, args.env)
    success, errors, warnings = validator.validate()

    if args.json:
        result = {"valid": success, "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2))
    else:
        print("CIRIS Manager Configuration Validator")
        print("=" * 40)
        print(f"Config file: {args.config}")
        if args.env:
            print(f"Environment file: {args.env}")
        print()

        if errors:
            print("ERRORS:")
            for error in errors:
                print(f"  ✗ {error}")
            print()

        if warnings:
            print("WARNINGS:")
            for warning in warnings:
                print(f"  ⚠ {warning}")
            print()

        if success:
            print("✓ Configuration is valid for production")
        else:
            print("✗ Configuration has errors that must be fixed")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
