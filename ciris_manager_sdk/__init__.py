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

        # Allow only safe characters in endpoint: alphanumeric, -, _, /, {}, ?, =, &
        # The {} is for path parameters, ?=& for query strings
        if not re.match(r"^/[a-zA-Z0-9/_\-{}?=&%]+$", endpoint):
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

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get details for a specific agent."""
        self._validate_agent_id(agent_id)
        # Use URL encoding to prevent injection
        safe_id = quote(agent_id, safe="")
        response = self._request("GET", f"/manager/v1/agents/{safe_id}")
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

    def start_agent(self, agent_id: str) -> Dict[str, Any]:
        """Start an agent."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("POST", f"/manager/v1/agents/{safe_id}/start")
        return response.json()

    def stop_agent(self, agent_id: str) -> Dict[str, Any]:
        """Stop an agent."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("POST", f"/manager/v1/agents/{safe_id}/stop")
        return response.json()

    def restart_agent(self, agent_id: str) -> Dict[str, Any]:
        """Restart an agent."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request("POST", f"/manager/v1/agents/{safe_id}/restart")
        return response.json()

    def get_agent_logs(self, agent_id: str, lines: int = 100) -> str:
        """Get agent logs."""
        self._validate_agent_id(agent_id)
        safe_id = quote(agent_id, safe="")
        response = self._request(
            "GET", f"/manager/v1/agents/{safe_id}/logs", params={"lines": lines}
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

    # Utility Methods

    def ping(self) -> bool:
        """Check if the API is reachable."""
        try:
            self.get_health()
            return True
        except Exception:
            return False
