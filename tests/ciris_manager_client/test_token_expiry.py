"""An expired session should say so, not vanish.

`load_token` already compared `expires_at` against the clock, but every way
that comparison could go wrong ended in `except Exception: pass` - so an
expired session, a clock-format change and an unreadable file were all
reported identically, as "not signed in". In practice that surfaced several
calls later as an empty result or an opaque 401, which reads like the server
is broken rather than the session having lapsed.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from ciris_manager_client.main import load_token


@pytest.fixture
def token_home(tmp_path, monkeypatch):
    """Point Path.home() at a temp dir and clear the env override."""
    monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    d = tmp_path / ".config" / "ciris-manager"
    d.mkdir(parents=True)
    return d / "token.json"


def _write(path, expires_at, token="tok-abc", email="eric@ciris.ai"):
    path.write_text(json.dumps({"token": token, "email": email, "expires_at": expires_at}))


class TestValidToken:
    def test_unexpired_naive_timestamp_is_used(self, token_home):
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).replace(tzinfo=None)
        _write(token_home, future.isoformat())
        assert load_token() == "tok-abc"

    def test_unexpired_offset_aware_timestamp_is_used(self, token_home):
        """A tz-aware stamp used to raise TypeError against utcnow() and be
        swallowed, silently downgrading a valid session to 'not signed in'."""
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        _write(token_home, future.isoformat())
        assert load_token() == "tok-abc"

    def test_env_var_wins_over_file(self, token_home, monkeypatch):
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(tzinfo=None)
        _write(token_home, past.isoformat())
        monkeypatch.setenv("CIRIS_MANAGER_TOKEN", "env-token")
        assert load_token() == "env-token"


class TestExpiredToken:
    def test_expired_token_is_not_returned(self, token_home):
        past = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)
        _write(token_home, past.isoformat())
        assert load_token() is None

    def test_expired_token_explains_itself(self, token_home, capsys):
        past = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)
        _write(token_home, past.isoformat())
        load_token()
        err = capsys.readouterr().err
        assert "Session expired" in err
        assert "eric@ciris.ai" in err
        assert "auth login" in err, "the message must name the remedy"

    def test_expiry_message_goes_to_stderr_not_stdout(self, token_home, capsys):
        """stdout carries data; a --format json consumer must not receive this."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        _write(token_home, past.isoformat())
        load_token()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Session expired" in captured.err


class TestUnreadableToken:
    def test_malformed_json_is_reported(self, token_home, capsys):
        token_home.write_text("{not json")
        assert load_token() is None
        assert "unreadable token file" in capsys.readouterr().err

    def test_missing_expires_at_is_reported(self, token_home, capsys):
        token_home.write_text(json.dumps({"token": "tok-abc"}))
        assert load_token() is None
        assert "unreadable token file" in capsys.readouterr().err

    def test_unparseable_timestamp_is_reported(self, token_home, capsys):
        _write(token_home, "not-a-timestamp")
        assert load_token() is None
        assert "unreadable token file" in capsys.readouterr().err
