"""Test OAuth models and type safety."""

import pytest
from ciris_manager.models import OAuthToken, OAuthUser, OAuthSession, JWTPayload


def test_oauth_token_creation():
    """Test OAuthToken model creation."""
    token = OAuthToken(
        access_token="test-token-123",
        token_type="Bearer",
        expires_in=3600,
    )

    assert token.access_token == "test-token-123"
    assert token.token_type == "Bearer"
    assert token.expires_in == 3600
    assert token.refresh_token is None


def test_oauth_user_creation():
    """Test OAuthUser model creation."""
    user = OAuthUser(
        id="user-123",
        email="test@ciris.ai",
        name="Test User",
        picture="https://example.com/pic.jpg",
    )

    assert user.id == "user-123"
    assert user.email == "test@ciris.ai"
    assert user.name == "Test User"
    assert user.picture == "https://example.com/pic.jpg"
    assert user.is_ciris_user is True


def test_oauth_user_non_ciris():
    """Test non-CIRIS user detection."""
    user = OAuthUser(
        id="user-456",
        email="test@example.com",
        name="External User",
    )

    assert user.is_ciris_user is False


def test_oauth_session_creation():
    """Test OAuthSession model creation."""
    session = OAuthSession(
        redirect_uri="/dashboard",
        callback_url="https://api.ciris.ai/auth/callback",
        created_at="2024-12-10T10:00:00Z",
    )

    assert session.redirect_uri == "/dashboard"
    assert session.callback_url == "https://api.ciris.ai/auth/callback"
    assert session.created_at == "2024-12-10T10:00:00Z"


def test_jwt_payload_creation():
    """Test JWTPayload model creation."""
    payload = JWTPayload(
        user_id=123,
        email="test@ciris.ai",
        name="Test User",
        exp=1704067200,  # 2024-01-01 00:00:00 UTC
    )

    assert payload.user_id == 123
    assert payload.email == "test@ciris.ai"
    assert payload.name == "Test User"
    assert payload.exp == 1704067200


def test_oauth_models_validation():
    """Test that required fields are enforced."""
    # OAuthToken requires access_token
    with pytest.raises(ValueError):
        OAuthToken()  # type: ignore

    # OAuthUser requires id and email
    with pytest.raises(ValueError):
        OAuthUser(id="test")  # type: ignore

    # OAuthSession requires all fields
    with pytest.raises(ValueError):
        OAuthSession(redirect_uri="/test")  # type: ignore

    # JWTPayload requires user_id and email
    with pytest.raises(ValueError):
        JWTPayload(user_id=123)  # type: ignore


def test_model_serialization():
    """Test that models can be serialized to dict."""
    user = OAuthUser(
        id="user-123",
        email="test@ciris.ai",
        name="Test User",
    )

    user_dict = user.model_dump()
    assert user_dict["id"] == "user-123"
    assert user_dict["email"] == "test@ciris.ai"
    assert user_dict["name"] == "Test User"
    assert user_dict["picture"] is None

    # Should be able to recreate from dict
    user2 = OAuthUser(**user_dict)
    assert user2.id == user.id
    assert user2.email == user.email
