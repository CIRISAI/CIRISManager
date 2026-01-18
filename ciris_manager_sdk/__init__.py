"""
CIRISManager SDK - Python client for interacting with CIRISManager API.
"""
# mypy: ignore-errors

from typing import Dict, List, Optional, Any
import requests
from pathlib import Path
import json
from datetime import datetime
from urllib.parse import quote


class CIRISManagerError(Exception):
    """Base exception for CIRISManager SDK."""

    pass


class AuthenticationError(CIRISManagerError):
    """Authentication related errors."""

    pass


class APIError(CIRISManagerError):
    """API request errors."""

    def __init__(
        self, message: str, status_code: Optional[int] = None, response: Optional[Dict] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class CIRISManagerClient:
    """Client for interacting with CIRISManager API."""

    def __init__(self, base_url: str = "https://agents.ciris.ai", token: Optional[str] = None):
        """
        Initialize the CIRISManager client.

        Args:
            base_url: Base URL for the CIRISManager API
            token: Authentication token (if not provided, will try to load from config)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token or self._load_token()
        self.session = requests.Session()
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def _validate_agent_id(self, agent_id: str) -> None:
        """Validate agent ID format to prevent injection attacks."""
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", agent_id):
            raise ValueError(f"Invalid agent ID format: {agent_id}")

    def _load_token(self) -> Optional[str]:
        """Load token from config file."""
        # Try ~/.manager_token first (simple token file)
        token_file = Path.home() / ".manager_token"
        if token_file.exists():
            try:
                return token_file.read_text().strip()
            except Exception:
                pass

        # Fall back to config file with expiry
        config_file = Path.home() / ".config" / "ciris-manager" / "token.json"
        if config_file.exists():
            try:
                with open(config_file) as f:
                    data = json.load(f)
                    # Check if token is expired
                    expires_at = datetime.fromisoformat(data.get("expires_at", ""))
                    if datetime.utcnow() < expires_at:
                        return data.get("token")
            except Exception:
                pass
        return None

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an authenticated request to the API."""
        if not self.token:
            raise AuthenticationError("No authentication token available. Please login first.")

        # Validate endpoint to prevent injection attacks
        # Endpoint should start with / and only contain safe characters
        import re

        if not endpoint.startswith("/"):
            raise ValueError("Endpoint must start with /")

        # Allow only safe characters in endpoint: alphanumeric, -, _, /, {}, ?, =, &, .
        # The {} is for path parameters, ?=& for query strings, . for filenames
        if not re.match(r"^/[a-zA-Z0-9/_\-{}?=&%.]+$", endpoint):
            raise ValueError("Invalid endpoint format")

        url = f"{self.base_url}{endpoint}"
        response = self.session.request(method, url, **kwargs)

        if response.status_code == 401:
            raise AuthenticationError("Authentication failed. Token may be expired.")
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("detail", f"API error: {response.status_code}")
            except Exception:
                message = f"API error: {response.status_code}"
            raise APIError(
                message, response.status_code, response.json() if response.text else None
            )

        return response

    # Agent Management

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all agents."""
        response = self._request("GET", "/manager/v1/agents")
        data = response.json()
        return data.get("agents", data) if isinstance(data, dict) else data

    def get_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get details for a specific agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Agent details dict
        """
        self._validate_agent_id(agent_id)
        # Use URL encoding to prevent injection
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}",
            params=params if params else None,
        )
        return response.json()

    def get_agent_config(self, agent_id: str) -> Dict[str, Any]:
        """
        Get agent configuration including environment variables.

        Returns:
            Dictionary with agent_id, environment dict, and compose_file path
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("GET", f"/manager/v1/agents/{safe_id}/config")
        return response.json()

    def create_agent(
        self,
        name: str,
        template: str = "basic",
        environment: Optional[Dict[str, str]] = None,
        mounts: Optional[List[Dict[str, str]]] = None,
        use_mock_llm: bool = False,
        enable_discord: bool = False,
        server_id: Optional[str] = None,
        billing_enabled: bool = False,
        billing_api_key: Optional[str] = None,
        database_url: Optional[str] = None,
        database_ssl_cert_path: Optional[str] = None,
        agent_occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new agent.

        Args:
            name: Name for the agent
            template: Template to use (default: "basic")
            environment: Environment variables for the agent
            mounts: Volume mounts for the agent
            use_mock_llm: Use mock LLM instead of real one
            enable_discord: Enable Discord adapter
            server_id: Target server ID (e.g., "main", "scout")
            billing_enabled: Enable paid billing
            billing_api_key: Billing API key (required if billing_enabled=True)
            database_url: PostgreSQL database URL
            database_ssl_cert_path: Path to SSL certificate for database
            agent_occurrence_id: Unique occurrence ID for database isolation (enables multiple agents on same DB)

        Returns:
            Created agent details
        """
        payload = {
            "name": name,
            "template": template,
            "environment": environment or {},
            "use_mock_llm": use_mock_llm,
            "enable_discord": enable_discord,
        }
        if mounts:
            payload["mounts"] = mounts
        if server_id:
            payload["server_id"] = server_id
        if billing_enabled:
            payload["billing_enabled"] = billing_enabled
        if billing_api_key:
            payload["billing_api_key"] = billing_api_key
        if database_url:
            payload["database_url"] = database_url
        if database_ssl_cert_path:
            payload["database_ssl_cert_path"] = database_ssl_cert_path
        if agent_occurrence_id:
            payload["agent_occurrence_id"] = agent_occurrence_id

        response = self._request("POST", "/manager/v1/agents", json=payload)
        return response.json()

    def update_agent_config(self, agent_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update agent configuration."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("PATCH", f"/manager/v1/agents/{safe_id}/config", json=config)
        return response.json()

    def delete_agent(self, agent_id: str) -> Dict[str, Any]:
        """Delete an agent."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("DELETE", f"/manager/v1/agents/{safe_id}")
        return response.json()

    def start_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Start result dict
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/start",
            params=params if params else None,
        )
        return response.json()

    def stop_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Stop an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Stop result dict
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/stop",
            params=params if params else None,
        )
        return response.json()

    def restart_agent(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Restart an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Restart result dict
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/restart",
            params=params if params else None,
        )
        return response.json()

    def get_agent_logs(
        self,
        agent_id: str,
        lines: int = 100,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> str:
        """
        Get agent logs.

        Args:
            agent_id: Agent identifier
            lines: Number of log lines to retrieve
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Log output as string
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params: Dict[str, Any] = {"lines": lines}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET", f"/manager/v1/agents/{safe_id}/logs", params=params
        )
        return response.text

    def get_agent_log_file(
        self,
        agent_id: str,
        filename: str = "latest.log",
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> str:
        """
        Get a specific log file from an agent container.

        Args:
            agent_id: Agent identifier
            filename: Log filename - 'latest.log' or 'incidents_latest.log'
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Full contents of the log file as string
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_filename = quote(filename, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/logs/file/{safe_filename}",
            params=params if params else None,
        )
        return response.text

    # Template Management

    def list_templates(self) -> List[str]:
        """List available templates."""
        response = self._request("GET", "/manager/v1/templates")
        data = response.json()
        return data.get("templates", data) if isinstance(data, dict) else data

    # System Information

    def get_status(self) -> Dict[str, Any]:
        """Get manager status."""
        response = self._request("GET", "/manager/v1/status")
        return response.json()

    def get_health(self) -> Dict[str, Any]:
        """Get health check."""
        response = self._request("GET", "/manager/v1/health")
        return response.json()

    def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics."""
        response = self._request("GET", "/manager/v1/metrics")
        return response.json()

    # Update Management

    def get_update_status(self) -> Dict[str, Any]:
        """Get update/deployment status."""
        response = self._request("GET", "/manager/v1/updates/status")
        return response.json()

    def notify_update(
        self,
        agent_image: str,
        gui_image: Optional[str] = None,
        strategy: str = "canary",
        message: str = "",
    ) -> Dict[str, Any]:
        """
        Notify agents of available update.

        Args:
            agent_image: Docker image for agents
            gui_image: Docker image for GUI (optional)
            strategy: Deployment strategy ("canary" or "immediate")
            message: Update message

        Returns:
            Update notification response
        """
        payload = {"agent_image": agent_image, "strategy": strategy, "message": message}
        if gui_image:
            payload["gui_image"] = gui_image

        response = self._request("POST", "/manager/v1/updates/notify", json=payload)
        return response.json()

    def deploy_single_agent(
        self,
        agent_id: str,
        agent_image: str,
        message: str = "Single agent deployment",
        strategy: str = "docker",
        metadata: Optional[Dict[str, Any]] = None,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deploy a specific version to a single agent.

        Args:
            agent_id: Target agent ID
            agent_image: Docker image for the agent (e.g., "ghcr.io/cirisai/ciris-agent:1.3.3")
            message: Deployment message
            strategy: Deployment strategy ("manual", "immediate", or "docker")
                - manual: Consensual deployment (agent decides when to apply)
                - immediate: API forced shutdown (agent shuts down via API)
                - docker: Manager forced restart (Docker restart, bypasses agent)
            metadata: Optional metadata for the deployment
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Deployment response with deployment_id and status
        """
        self._validate_agent_id(agent_id)
        payload = {
            "agent_id": agent_id,
            "agent_image": agent_image,
            "message": message,
            "strategy": strategy,
        }
        if metadata:
            payload["metadata"] = metadata
        if occurrence_id:
            payload["occurrence_id"] = occurrence_id
        if server_id:
            payload["server_id"] = server_id

        response = self._request("POST", "/manager/v1/updates/deploy-single", json=payload)
        return response.json()

    def cancel_deployment(
        self, deployment_id: str, reason: str = "Cancelled via SDK"
    ) -> Dict[str, Any]:
        """
        Cancel a stuck or failed deployment.

        Note: For pending/staged deployments, use reject_deployment() instead.

        Args:
            deployment_id: ID of the deployment to cancel
            reason: Reason for cancellation

        Returns:
            Cancellation response with status
        """
        payload = {"deployment_id": deployment_id, "reason": reason}
        response = self._request("POST", "/manager/v1/updates/cancel", json=payload)
        return response.json()

    def reject_deployment(
        self, deployment_id: str, reason: str = "Rejected via SDK"
    ) -> Dict[str, Any]:
        """
        Reject a pending/staged deployment.

        Use this for deployments that are staged but not yet started.

        Args:
            deployment_id: ID of the deployment to reject
            reason: Reason for rejection

        Returns:
            Rejection response with status
        """
        payload = {"deployment_id": deployment_id, "reason": reason}
        response = self._request("POST", "/manager/v1/updates/reject", json=payload)
        return response.json()

    def start_deployment(self, deployment_id: str) -> Dict[str, Any]:
        """
        Start/launch a pending deployment.

        Args:
            deployment_id: ID of the deployment to start

        Returns:
            Response with status and deployment_id
        """
        payload = {"deployment_id": deployment_id}
        response = self._request("POST", "/manager/v1/updates/launch", json=payload)
        return response.json()

    def retry_deployment(self, deployment_id: str) -> Dict[str, Any]:
        """
        Retry a failed/cancelled deployment.

        Creates a new deployment using the original notification from the failed deployment.

        Args:
            deployment_id: ID of the failed deployment to retry

        Returns:
            Response with new_deployment_id and status
        """
        payload = {"deployment_id": deployment_id}
        response = self._request("POST", "/manager/v1/updates/retry", json=payload)
        return response.json()

    def get_deployment_status(
        self, deployment_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get deployment status.

        Args:
            deployment_id: Optional deployment ID. If not provided, returns current/latest deployment.

        Returns:
            Deployment status information, or None if no active deployment
        """
        endpoint = "/manager/v1/updates/status"
        if deployment_id:
            endpoint = f"{endpoint}?deployment_id={quote(deployment_id, safe='')}"
        response = self._request("GET", endpoint)
        result = response.json()
        return result if result is not None else None

    def get_pending_deployments(self) -> Dict[str, Any]:
        """
        Get all pending/staged deployments.

        Returns:
            Dict with 'deployments' list, 'latest_tag' info, and 'total_pending' count
        """
        response = self._request("GET", "/manager/v1/updates/pending/all")
        return response.json()

    # Maintenance Mode

    def get_maintenance_status(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get maintenance mode status for an agent.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with agent_id, do_not_autostart, and maintenance_mode fields
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/maintenance",
            params=params if params else None,
        )
        return response.json()

    def set_maintenance_mode(
        self,
        agent_id: str,
        enable: bool = True,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enable or disable maintenance mode for an agent.

        When maintenance mode is enabled, the container manager will not
        automatically restart the agent if it crashes or stops, and
        deployments will skip this agent.

        Args:
            agent_id: Agent identifier
            enable: True to enable maintenance mode, False to disable
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with status, agent_id, do_not_autostart, and message
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        payload = {"do_not_autostart": enable}
        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/maintenance",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    # Adapter Management

    def list_adapters(self, agent_id: str) -> Dict[str, Any]:
        """
        List all running adapters on an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Dict with adapter data
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("GET", f"/manager/v1/agents/{safe_id}/adapters")
        return response.json()

    def list_adapter_types(
        self,
        agent_id: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List available adapter types on an agent.

        Args:
            agent_id: Agent identifier
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with available adapter types
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/adapters/types",
            params=params if params else None,
        )
        return response.json()

    def get_adapter(
        self,
        agent_id: str,
        adapter_id: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get status of a specific adapter.

        Args:
            agent_id: Agent identifier
            adapter_id: Adapter ID
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with adapter status
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_adapter_id = quote(adapter_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_adapter_id}",
            params=params if params else None,
        )
        return response.json()

    def load_adapter(
        self,
        agent_id: str,
        adapter_type: str,
        config: Optional[Dict[str, Any]] = None,
        auto_start: bool = True,
        adapter_id: Optional[str] = None,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Load/create a new adapter on an agent.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter to load
            config: Adapter configuration
            auto_start: Whether to start adapter immediately
            adapter_id: Optional custom adapter ID
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with load result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")

        payload: Dict[str, Any] = {"auto_start": auto_start}
        if config:
            payload["config"] = config

        params = {}
        if adapter_id:
            params["adapter_id"] = adapter_id
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    def reload_adapter(
        self,
        agent_id: str,
        adapter_id: str,
        config: Optional[Dict[str, Any]] = None,
        auto_start: bool = True,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reload an adapter with new configuration.

        Args:
            agent_id: Agent identifier
            adapter_id: Adapter ID
            config: New configuration
            auto_start: Whether to start adapter after reload
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with reload result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_adapter_id = quote(adapter_id, safe="")

        payload: Dict[str, Any] = {"auto_start": auto_start}
        if config:
            payload["config"] = config

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "PUT",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_adapter_id}/reload",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    def unload_adapter(
        self,
        agent_id: str,
        adapter_id: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Unload/stop an adapter on an agent.

        Args:
            agent_id: Agent identifier
            adapter_id: Adapter ID
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with unload result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_adapter_id = quote(adapter_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "DELETE",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_adapter_id}",
            params=params if params else None,
        )
        return response.json()

    def list_adapter_manifests(
        self,
        agent_id: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all available adapters with their status.

        Returns summary info including status (not_configured, configured, enabled).

        Args:
            agent_id: Agent identifier
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with adapters list
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/adapters/manifests",
            params=params if params else None,
        )
        return response.json()

    def get_adapter_manifest(
        self,
        agent_id: str,
        adapter_type: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get full manifest for a specific adapter type.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with adapter manifest
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}/manifest",
            params=params if params else None,
        )
        return response.json()

    def get_adapter_configs(
        self,
        agent_id: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all persisted adapter configurations for an agent.

        Args:
            agent_id: Agent identifier
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with configs per adapter type
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/adapters/configs",
            params=params if params else None,
        )
        return response.json()

    def remove_adapter_config(
        self,
        agent_id: str,
        adapter_type: str,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Remove adapter configuration from registry.

        Also attempts to unload the adapter from the agent.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with removal result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "DELETE",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}/config",
            params=params if params else None,
        )
        return response.json()

    def start_adapter_wizard(
        self,
        agent_id: str,
        adapter_type: str,
        resume_from: Optional[str] = None,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start a wizard session for configuring an adapter.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter to configure
            resume_from: Optional session ID to resume
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with session info (session_id, current_step, steps_remaining, etc.)
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        payload: Dict[str, Any] = {}
        if resume_from:
            payload["resume_from"] = resume_from

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}/wizard/start",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    def execute_wizard_step(
        self,
        agent_id: str,
        adapter_type: str,
        session_id: str,
        step_id: str,
        data: Optional[Dict[str, Any]] = None,
        action: str = "execute",
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a wizard step.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter
            session_id: Wizard session ID
            step_id: Step ID to execute
            data: Step input data
            action: "execute" or "skip"
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with step result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")
        safe_session = quote(session_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        payload = {
            "step_id": step_id,
            "action": action,
            "data": data or {},
        }

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}/wizard/{safe_session}/step",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    def complete_adapter_wizard(
        self,
        agent_id: str,
        adapter_type: str,
        session_id: str,
        confirm: bool = True,
        server_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete the wizard and apply configuration.

        Args:
            agent_id: Agent identifier
            adapter_type: Type of adapter
            session_id: Wizard session ID
            confirm: Must be True to confirm completion
            server_id: Optional server ID for multi-server agents
            occurrence_id: Optional occurrence ID for multi-instance agents

        Returns:
            Dict with completion result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        safe_type = quote(adapter_type, safe="")
        safe_session = quote(session_id, safe="")

        params = {}
        if server_id:
            params["server_id"] = server_id
        if occurrence_id:
            params["occurrence_id"] = occurrence_id

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/adapters/{safe_type}/wizard/{safe_session}/complete",
            params=params if params else None,
            json={"confirm": confirm},
        )
        return response.json()

    # LLM Configuration Methods

    def get_llm_config(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get LLM configuration for an agent.

        Returns configuration with API keys redacted for security.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server setups

        Returns:
            Dict with LLM config (keys redacted) or null if not configured
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/llm",
            params=params if params else None,
        )
        return response.json()

    def set_llm_config(
        self,
        agent_id: str,
        primary_provider: str,
        primary_api_key: str,
        primary_model: str,
        primary_api_base: Optional[str] = None,
        backup_provider: Optional[str] = None,
        backup_api_key: Optional[str] = None,
        backup_model: Optional[str] = None,
        backup_api_base: Optional[str] = None,
        validate: bool = True,
        restart: bool = True,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Set LLM configuration for an agent.

        Args:
            agent_id: Agent identifier
            primary_provider: Primary provider (openai, together, groq, openrouter, custom)
            primary_api_key: Primary API key
            primary_model: Primary model identifier
            primary_api_base: Primary custom API base URL (optional)
            backup_provider: Backup provider (optional)
            backup_api_key: Backup API key (optional)
            backup_model: Backup model (optional)
            backup_api_base: Backup custom API base URL (optional)
            validate: Validate API keys before saving (default: True)
            restart: Restart container after update (default: True)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server setups

        Returns:
            Dict with result including validation status
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {
            "validate": str(validate).lower(),
            "restart": str(restart).lower(),
        }
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        payload = {
            "primary_provider": primary_provider,
            "primary_api_key": primary_api_key,
            "primary_model": primary_model,
        }
        if primary_api_base:
            payload["primary_api_base"] = primary_api_base
        if backup_provider:
            payload["backup_provider"] = backup_provider
        if backup_api_key:
            payload["backup_api_key"] = backup_api_key
        if backup_model:
            payload["backup_model"] = backup_model
        if backup_api_base:
            payload["backup_api_base"] = backup_api_base

        response = self._request(
            "PUT",
            f"/manager/v1/agents/{safe_id}/llm",
            params=params,
            json=payload,
        )
        return response.json()

    def delete_llm_config(
        self,
        agent_id: str,
        restart: bool = True,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Delete LLM configuration for an agent.

        After deletion, the agent will use environment variables.

        Args:
            agent_id: Agent identifier
            restart: Restart container after deletion (default: True)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server setups

        Returns:
            Dict with deletion result
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {"restart": str(restart).lower()}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "DELETE",
            f"/manager/v1/agents/{safe_id}/llm",
            params=params,
        )
        return response.json()

    def validate_llm_config(
        self,
        agent_id: str,
        provider: str,
        api_key: str,
        model: str,
        api_base: Optional[str] = None,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate LLM configuration without saving.

        Tests the API key by calling the provider's /v1/models endpoint.
        Does not consume tokens or modify agent configuration.

        Args:
            agent_id: Agent identifier (for auth context)
            provider: Provider name (openai, together, groq, openrouter, custom)
            api_key: API key to validate
            model: Model identifier to check
            api_base: Custom API base URL (optional)
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server setups

        Returns:
            Dict with validation result: {valid: bool, error: str|null, models_available: list|null}
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        payload = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
        }
        if api_base:
            payload["api_base"] = api_base

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/llm/validate",
            params=params if params else None,
            json=payload,
        )
        return response.json()

    # Admin Actions (Infrastructure Operations)

    def list_admin_actions(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List available admin actions for an agent.

        These are infrastructure-level actions that the manager can perform.
        Agent-side actions (pause/resume) must go through the H3ERE pipeline.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with agent_id and available actions list
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        params = {}
        if occurrence_id:
            params["occurrence_id"] = occurrence_id
        if server_id:
            params["server_id"] = server_id

        response = self._request(
            "GET",
            f"/manager/v1/agents/{safe_id}/admin/actions",
            params=params if params else None,
        )
        return response.json()

    def execute_admin_action(
        self,
        agent_id: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        force: bool = False,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an admin action on an agent.

        Available actions:
        - identity-update: Update agent identity from template (modifies compose, restarts)
        - restart: Restart agent container
        - pull-image: Pull latest agent image without restart

        Args:
            agent_id: Agent identifier
            action: Action to execute (identity-update, restart, pull-image)
            params: Optional action parameters
            force: Force execution even if agent is busy
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with success, action, agent_id, message, and details
        """
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")

        query_params = {}
        if occurrence_id:
            query_params["occurrence_id"] = occurrence_id
        if server_id:
            query_params["server_id"] = server_id

        payload = {
            "action": action,
            "force": force,
        }
        if params:
            payload["params"] = params

        response = self._request(
            "POST",
            f"/manager/v1/agents/{safe_id}/admin/actions",
            params=query_params if query_params else None,
            json=payload,
        )
        return response.json()

    def trigger_identity_update(
        self,
        agent_id: str,
        template: Optional[str] = None,
        force: bool = False,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Trigger identity update for an agent.

        Modifies the docker-compose.yml to add --identity-update flag
        and restarts the container. On next boot, the agent will
        regenerate its identity from the template.

        Args:
            agent_id: Agent identifier
            template: Optional template name override
            force: Force even if agent is busy
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with action result
        """
        params = {}
        if template:
            params["template"] = template
        return self.execute_admin_action(
            agent_id,
            "identity-update",
            params=params if params else None,
            force=force,
            occurrence_id=occurrence_id,
            server_id=server_id,
        )

    def pull_agent_image(
        self,
        agent_id: str,
        occurrence_id: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pull latest Docker image for an agent without restarting.

        Args:
            agent_id: Agent identifier
            occurrence_id: Optional occurrence ID for multi-instance agents
            server_id: Optional server ID for multi-server agents

        Returns:
            Dict with pull result including image name
        """
        return self.execute_admin_action(
            agent_id,
            "pull-image",
            occurrence_id=occurrence_id,
            server_id=server_id,
        )

    # Utility Methods

    def ping(self) -> bool:
        """Check if the API is reachable."""
        try:
            self.get_health()
            return True
        except Exception:
            return False
