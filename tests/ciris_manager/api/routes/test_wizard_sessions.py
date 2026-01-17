"""
Tests for wizard session management.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from ciris_manager.api.routes.wizard_sessions import (
    WizardSession,
    WizardSessionManager,
    get_wizard_session_manager,
    SESSION_TTL_SECONDS,
)


class TestWizardSession:
    """Tests for the WizardSession class."""

    def test_initialization(self):
        """Test basic session initialization."""
        session = WizardSession(
            session_id="wiz_test123",
            agent_id="test-agent",
            adapter_type="discord",
            steps=["step1", "step2", "step3"],
        )

        assert session.session_id == "wiz_test123"
        assert session.agent_id == "test-agent"
        assert session.adapter_type == "discord"
        assert session.steps == ["step1", "step2", "step3"]
        assert session.current_step_index == 0
        assert session.steps_completed == []
        assert session.collected_data == {}
        assert session.oauth_state is None

    def test_current_step_property(self):
        """Test current_step property returns correct step."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a", "b", "c"],
        )

        assert session.current_step == "a"
        session.current_step_index = 1
        assert session.current_step == "b"
        session.current_step_index = 2
        assert session.current_step == "c"

    def test_current_step_at_end(self):
        """Test current_step returns last step when past end."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a", "b"],
        )
        session.current_step_index = 5  # Past the end
        assert session.current_step == "b"  # Returns last step

    def test_steps_remaining_property(self):
        """Test steps_remaining returns correct list."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a", "b", "c", "d"],
        )

        assert session.steps_remaining == ["a", "b", "c", "d"]
        session.current_step_index = 2
        assert session.steps_remaining == ["c", "d"]
        session.current_step_index = 4
        assert session.steps_remaining == []

    def test_is_expired_fresh_session(self):
        """Test fresh session is not expired."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a"],
        )
        assert not session.is_expired

    def test_is_expired_old_session(self):
        """Test old session is expired."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a"],
        )
        # Set expires_at to the past
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert session.is_expired

    def test_advance_step(self):
        """Test advancing through steps."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a", "b", "c"],
        )

        assert session.advance_step() is True
        assert session.current_step_index == 1
        assert session.steps_completed == ["a"]

        assert session.advance_step() is True
        assert session.current_step_index == 2
        assert session.steps_completed == ["a", "b"]

        assert session.advance_step() is True
        assert session.current_step_index == 3
        assert session.steps_completed == ["a", "b", "c"]

        # Can't advance past end
        assert session.advance_step() is False

    def test_to_dict(self):
        """Test session serialization to dict."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a", "b"],
        )
        session.collected_data = {"field1": "value1"}
        session.advance_step()

        result = session.to_dict()

        assert result["session_id"] == "wiz_test"
        assert result["agent_id"] == "agent"
        assert result["adapter_type"] == "test"
        assert result["current_step"] == "b"
        assert result["steps_completed"] == ["a"]
        assert result["steps_remaining"] == ["b"]
        assert result["collected_data"] == {"field1": "value1"}
        assert "expires_at" in result

    def test_mask_sensitive_data(self):
        """Test sensitive data masking."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a"],
        )

        data = {
            "username": "user123",
            "password": "secret123",
            "api_key": "key_abc",
            "token": "tok_xyz",
            "client_secret": "cs_123",
            "normal_field": "visible",
        }

        masked = session._mask_sensitive_data(data)

        assert masked["username"] == "user123"
        assert masked["password"] == "***"
        assert masked["api_key"] == "***"
        assert masked["token"] == "***"
        assert masked["client_secret"] == "***"
        assert masked["normal_field"] == "visible"

    def test_mask_sensitive_data_nested(self):
        """Test sensitive data masking in nested dicts."""
        session = WizardSession(
            session_id="wiz_test",
            agent_id="agent",
            adapter_type="test",
            steps=["a"],
        )

        data = {
            "outer": "visible",
            "nested": {
                "inner_password": "secret",
                "inner_normal": "visible",
            },
        }

        masked = session._mask_sensitive_data(data)

        assert masked["outer"] == "visible"
        assert masked["nested"]["inner_password"] == "***"
        assert masked["nested"]["inner_normal"] == "visible"


class TestWizardSessionManager:
    """Tests for the WizardSessionManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh session manager for each test."""
        return WizardSessionManager()

    def test_create_session(self, manager):
        """Test creating a new session."""
        session = manager.create_session(
            agent_id="test-agent",
            adapter_type="discord",
            steps=["step1", "step2"],
        )

        assert session.agent_id == "test-agent"
        assert session.adapter_type == "discord"
        assert session.steps == ["step1", "step2"]
        assert session.session_id.startswith("wiz_")

    def test_get_session(self, manager):
        """Test retrieving a session by ID."""
        created = manager.create_session(
            agent_id="test-agent",
            adapter_type="discord",
            steps=["step1"],
        )

        retrieved = manager.get_session(created.session_id)
        assert retrieved is not None
        assert retrieved.session_id == created.session_id

    def test_get_session_not_found(self, manager):
        """Test retrieving non-existent session returns None."""
        result = manager.get_session("nonexistent_id")
        assert result is None

    def test_get_session_expired(self, manager):
        """Test expired session returns None and is cleaned up."""
        session = manager.create_session(
            agent_id="test-agent",
            adapter_type="discord",
            steps=["step1"],
        )

        # Expire the session
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        result = manager.get_session(session.session_id)
        assert result is None

    def test_get_sessions_for_agent(self, manager):
        """Test getting all sessions for an agent."""
        manager.create_session("agent1", "discord", ["s1"])
        manager.create_session("agent1", "reddit", ["s1"])
        manager.create_session("agent2", "discord", ["s1"])

        agent1_sessions = manager.get_sessions_for_agent("agent1")
        assert len(agent1_sessions) == 2

        agent2_sessions = manager.get_sessions_for_agent("agent2")
        assert len(agent2_sessions) == 1

    def test_delete_session(self, manager):
        """Test deleting a session."""
        session = manager.create_session("agent", "discord", ["s1"])
        session_id = session.session_id

        assert manager.delete_session(session_id) is True
        assert manager.get_session(session_id) is None

    def test_delete_session_not_found(self, manager):
        """Test deleting non-existent session returns False."""
        assert manager.delete_session("nonexistent") is False

    def test_cleanup_expired_on_create(self, manager):
        """Test that expired sessions are cleaned up when creating new ones."""
        # Create a session and expire it
        old_session = manager.create_session("agent", "discord", ["s1"])
        old_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        # Creating a new session should clean up the expired one
        manager.create_session("agent", "reddit", ["s1"])

        assert manager.get_session(old_session.session_id) is None

    def test_unique_session_ids(self, manager):
        """Test that session IDs are unique."""
        session_ids = set()
        for _ in range(100):
            session = manager.create_session("agent", "discord", ["s1"])
            assert session.session_id not in session_ids
            session_ids.add(session.session_id)


class TestGetWizardSessionManager:
    """Tests for the global session manager singleton."""

    def test_returns_same_instance(self):
        """Test that get_wizard_session_manager returns the same instance."""
        # Note: This test may be affected by other tests since it uses a global
        manager1 = get_wizard_session_manager()
        manager2 = get_wizard_session_manager()
        assert manager1 is manager2
