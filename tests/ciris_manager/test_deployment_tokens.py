"""Tests for DeploymentTokenManager lifecycle hardening.

Regression tests for: production logs showed `_save_tokens` being called on
every process start (and twice when the orchestrator gets double-initialised),
each call failing to write /etc/ciris-manager/environment at ERROR level.
The manager should (a) only persist when tokens actually change and (b) treat
env-file sync failures as a once-per-process warning, not a repeated ERROR.
"""

import json
from pathlib import Path
from unittest.mock import patch

from ciris_manager.deployment_tokens import DeploymentTokenManager


def _write_tokens_json(config_dir: Path, tokens: dict) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "deployment_tokens.json").write_text(json.dumps(tokens))


def test_no_save_when_tokens_unchanged(tmp_path, caplog):
    """When the JSON already has all required tokens, _save_tokens must not run."""
    _write_tokens_json(
        tmp_path,
        {"agent": "a" * 32, "gui": "g" * 32, "legacy": "l" * 32},
    )

    with patch.object(DeploymentTokenManager, "_save_tokens") as save:
        mgr = DeploymentTokenManager(config_dir=str(tmp_path))

    save.assert_not_called()
    assert mgr.tokens["agent"] == "a" * 32


def test_save_runs_when_tokens_generated(tmp_path):
    """Missing tokens trigger generation, which must persist to JSON."""
    # Empty config dir -> all three tokens need generating.
    mgr = DeploymentTokenManager(config_dir=str(tmp_path))

    stored = json.loads((tmp_path / "deployment_tokens.json").read_text())
    assert set(stored.keys()) == {"agent", "gui", "legacy"}
    for v in stored.values():
        assert isinstance(v, str) and len(v) > 20
    assert mgr.tokens == stored


def test_save_runs_when_env_backfills_missing_token(tmp_path, monkeypatch):
    """If JSON is missing a token but the env has it, we pick up and persist."""
    _write_tokens_json(tmp_path, {"agent": "a" * 32, "gui": "g" * 32})
    monkeypatch.setenv("CIRIS_DEPLOY_TOKEN", "legacy-from-env")

    mgr = DeploymentTokenManager(config_dir=str(tmp_path))

    stored = json.loads((tmp_path / "deployment_tokens.json").read_text())
    assert stored["legacy"] == "legacy-from-env"
    assert mgr.tokens["legacy"] == "legacy-from-env"


def test_env_file_sync_failure_warns_once(tmp_path, caplog):
    """Env-file sync failures must warn once, not log ERROR on every save."""
    # Empty dir => tokens will be generated => _save_tokens runs.
    with patch.object(
        DeploymentTokenManager,
        "_update_environment_file",
        side_effect=PermissionError("no write"),
    ):
        caplog.clear()
        mgr = DeploymentTokenManager(config_dir=str(tmp_path))

        # First failure: one WARNING.
        warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "sync deployment tokens" in r.message
        ]
        errors = [
            r for r in caplog.records if r.levelname == "ERROR" and "environment file" in r.message
        ]
        assert len(warnings) == 1
        assert errors == []  # No ERROR-level spam

        # Simulate a second save (e.g. orchestrator double-init); must NOT
        # warn again in the same process.
        caplog.clear()
        mgr._save_tokens(mgr.tokens)
        repeat = [r for r in caplog.records if "sync deployment tokens" in r.message]
        assert repeat == []


def test_json_save_succeeds_even_when_env_sync_fails(tmp_path):
    """JSON persistence must not be blocked by env-file sync failures."""
    with patch.object(
        DeploymentTokenManager,
        "_update_environment_file",
        side_effect=PermissionError("no write"),
    ):
        DeploymentTokenManager(config_dir=str(tmp_path))

    tokens_path = tmp_path / "deployment_tokens.json"
    assert tokens_path.exists()
    data = json.loads(tokens_path.read_text())
    assert set(data.keys()) == {"agent", "gui", "legacy"}
