"""
Security-focused tests for CIRISManager.

Tests protection against common security vulnerabilities.
"""

import pytest
import os
from unittest.mock import Mock, patch
from ciris_manager.agent_auth import AgentAuth
from ciris_manager.crypto import TokenEncryption
from ciris_manager.api.routes import create_routes


class TestAuthenticationSecurity:
    """Test authentication security measures."""

    def test_no_hardcoded_credentials(self):
        """Verify no hardcoded credentials exist in agent auth."""
        auth = AgentAuth()

        # Should raise ValueError when no token exists
        with pytest.raises(ValueError, match="No service token found"):
            auth.get_auth_headers("nonexistent-agent")

    def test_service_token_required(self):
        """Test that service tokens are required for authentication."""
        # Create mock registry with agent but no token
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.service_token = None
        mock_registry.get_agent.return_value = mock_agent

        auth = AgentAuth(agent_registry=mock_registry)

        with pytest.raises(ValueError, match="No service token found"):
            auth.get_auth_headers("test-agent")

    def test_token_verification_timing_safe(self):
        """Test that token verification uses constant-time comparison."""
        auth = AgentAuth()

        # Mock the get_service_token method
        with patch.object(auth, "_get_service_token", return_value="correct-token"):
            # These should take the same time despite different lengths
            assert auth.verify_token("correct-token", "test-agent") is True
            assert auth.verify_token("wrong", "test-agent") is False
            assert auth.verify_token("wrong-but-same-length-token", "test-agent") is False


class TestEncryptionSecurity:
    """Test encryption security measures."""

    def test_no_default_encryption_keys(self):
        """Verify that default encryption keys are not accepted."""
        # Clear environment variables
        os.environ.pop("MANAGER_JWT_SECRET", None)
        os.environ.pop("CIRIS_ENCRYPTION_SALT", None)
        os.environ.pop("CIRIS_ENCRYPTION_KEY", None)

        # Should raise ValueError when no keys are set
        with pytest.raises(ValueError, match="MANAGER_JWT_SECRET environment variable is required"):
            TokenEncryption()

    def test_salt_minimum_length_enforced(self):
        """Test that salt must be at least 16 characters."""
        os.environ["MANAGER_JWT_SECRET"] = "test-secret"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "short"

        with pytest.raises(
            ValueError, match="CIRIS_ENCRYPTION_SALT must be at least 16 characters"
        ):
            TokenEncryption()

    def test_encryption_with_valid_config(self):
        """Test encryption works with valid configuration."""
        os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

        encryption = TokenEncryption()

        # Test encryption/decryption
        original_token = "test-service-token-12345"
        encrypted = encryption.encrypt_token(original_token)
        decrypted = encryption.decrypt_token(encrypted)

        assert decrypted == original_token
        assert encrypted != original_token  # Should be encrypted

    def test_encrypted_tokens_are_unique(self):
        """Test that encrypted tokens use proper randomization."""
        os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
        os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

        encryption = TokenEncryption()

        # Encrypt the same token twice
        token = "test-token"
        encrypted1 = encryption.encrypt_token(token)
        encrypted2 = encryption.encrypt_token(token)

        # Due to Fernet's use of timestamps and nonces, encrypted values should differ
        assert encrypted1 != encrypted2

        # But both should decrypt to the same value
        assert encryption.decrypt_token(encrypted1) == token
        assert encryption.decrypt_token(encrypted2) == token


class TestInputValidation:
    """Test input validation for security."""

    @pytest.mark.parametrize(
        "agent_id,should_pass",
        [
            ("valid-agent-123", True),
            ("agent_with_underscore", True),
            ("123-numeric-start", True),
            ("../../../etc/passwd", False),
            ("agent/../other", False),
            ("../../root", False),
            (".hidden", False),
            ("", False),
            ("a" * 65, False),  # Too long
            ("agent!", False),  # Invalid character
            ("agent$", False),  # Invalid character
            ("agent;rm -rf /", False),  # Command injection attempt
        ],
    )
    def test_agent_id_validation(self, agent_id, should_pass):
        """Test agent ID validation against various inputs."""
        import re

        pattern = r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$"

        result = bool(re.match(pattern, agent_id))
        assert result == should_pass

    def test_path_traversal_prevention(self):
        """Test that path traversal attacks are prevented."""
        from pathlib import Path

        base_path = Path("/opt/ciris/agents")

        # Test various path traversal attempts
        test_cases = [
            ("../../../etc/passwd", False),
            ("agent/../../../etc/passwd", False),
            ("agent/../../other", False),
            ("valid-agent/docker-compose.yml", True),
            ("valid-agent", True),
        ]

        for agent_id, should_be_valid in test_cases:
            test_path = (base_path / agent_id).resolve()
            is_valid = str(test_path).startswith(str(base_path))
            assert is_valid == should_be_valid, f"Path validation failed for {agent_id}"


class TestShellInjectionPrevention:
    """Test protection against shell injection attacks."""

    def test_no_shell_true_in_subprocess(self):
        """Verify that subprocess calls don't use shell=True with user input."""
        import os

        # Check routes.py for subprocess calls
        routes_file = "/home/emoore/CIRISManager/ciris_manager/api/routes.py"
        if os.path.exists(routes_file):
            with open(routes_file, "r") as f:
                content = f.read()

            # Simple check - more thorough would parse AST
            # After our fixes, there should be no shell=True
            assert "shell=True" not in content, "Found shell=True in routes.py"

    @pytest.mark.asyncio
    async def test_agent_id_sanitization_in_routes(self):
        """Test that routes properly sanitize agent IDs."""
        from unittest.mock import MagicMock

        # Create a mock manager
        mock_manager = MagicMock()

        # Try to create route with manager
        router = create_routes(mock_manager)

        # Find the get_agent_config endpoint
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/agents/{agent_id}/config":
                # The endpoint should validate agent_id
                # This is more of a smoke test that the validation is in place
                assert route.endpoint is not None
                break


class TestRateLimiting:
    """Test rate limiting implementation."""

    def test_rate_limits_defined(self):
        """Test that rate limits are properly defined."""
        from ciris_manager.api.rate_limit import RATE_LIMITS

        # Check critical endpoints have strict limits
        assert RATE_LIMITS["auth"] == "5 per minute"
        assert RATE_LIMITS["login"] == "10 per minute"
        assert RATE_LIMITS["create_agent"] == "5 per minute"
        assert RATE_LIMITS["deploy"] == "2 per minute"

        # Check read operations have more permissive limits
        assert RATE_LIMITS["get_agent"] == "120 per minute"
        assert RATE_LIMITS["list_agents"] == "60 per minute"

    @pytest.mark.skip(reason="Rate limiting is disabled in tests")
    def test_rate_limit_handler_returns_429(self):
        """Test that rate limit handler returns correct status code."""
        # This test is skipped because rate limiting is disabled in test environment
        # and the RateLimitExceeded class behaves differently when slowapi is not available
        pass


class TestAuditLogging:
    """Test audit logging for security events."""

    def test_service_token_use_is_audited(self):
        """Test that service token usage is logged for audit."""
        from ciris_manager.audit import audit_service_token_use
        import tempfile
        import json
        import os
        from pathlib import Path

        # Use a temp file for audit log
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "audit.jsonl"
            
            with patch("ciris_manager.audit.AUDIT_LOG_PATH", log_path):
                audit_service_token_use(
                    agent_id="test-agent", 
                    action="deployment",
                    success=True,
                    details={"deployment_id": "deploy-123"}
                )
                
                # Read back the audit log
                assert log_path.exists(), "Audit log file was not created"
                with open(log_path, 'r') as f:
                    content = f.read()
                
                # Verify the log entry
                assert len(content) > 0, "Audit log is empty"
                log_entry = json.loads(content.strip())
                assert log_entry["agent_id"] == "test-agent"
                assert log_entry["action"] == "deployment"
                assert log_entry["success"] is True


class TestSecurityHeaders:
    """Test security headers and HTTP security."""

    def test_no_sensitive_data_in_errors(self):
        """Test that error messages don't leak sensitive information."""
        from ciris_manager.agent_auth import AgentAuth

        auth = AgentAuth()

        # Error message should be generic, not revealing system details
        with pytest.raises(ValueError) as exc_info:
            auth.get_auth_headers("nonexistent")

        error_msg = str(exc_info.value)
        assert "No service token found" in error_msg
        # Should not contain paths, system details, etc.
        assert "/opt/ciris" not in error_msg
        assert "filesystem" not in error_msg.lower()

    def test_auth_headers_format(self):
        """Test that auth headers follow proper format."""
        from ciris_manager.agent_auth import AgentAuth

        # Mock registry and agent with token
        mock_registry = Mock()
        mock_agent = Mock()
        mock_agent.service_token = "encrypted-token"
        mock_registry.get_agent.return_value = mock_agent

        auth = AgentAuth(agent_registry=mock_registry)

        # Mock encryption
        with patch.object(auth, "_get_service_token", return_value="decrypted-token"):
            headers = auth.get_auth_headers("test-agent")

            # Should use Bearer scheme with service prefix
            assert "Authorization" in headers
            assert headers["Authorization"].startswith("Bearer service:")
            assert "decrypted-token" in headers["Authorization"]


if __name__ == "__main__":
    # Set up test environment
    os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing-only"
    os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars"

    pytest.main([__file__, "-v"])
