"""Tests for the `ciris-manager-client status` command set.

Covers the pure-Python helpers (incident classification, container name
derivation, output rendering) without exercising SSH or the manager API.
SSH/API paths are integration-tested manually against production.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ciris_manager_client.commands.status import (
    _classify_log_lines,
    _container_name,
    _emit,
    _gather_fleet,
    _SSHUnavailable,
    _ssh_run,
)


class _FakeClient:
    def __init__(self, agents):
        self._agents = agents

    def list_agents(self):
        return self._agents


def _ctx(fmt: str = "json", agents=None):
    client = _FakeClient(agents or [])
    return SimpleNamespace(client=client, output_format=fmt, quiet=False, verbose=False)


# -----------------------------------------------------------------------------
# _classify_log_lines
# -----------------------------------------------------------------------------


def test_classify_groups_by_first_match():
    """First matching pattern wins; the more general 'llm' bucket can't steal
    a line that matches the more specific 'All LLM services failed'."""
    text = "\n".join(
        [
            "2026-04-30 12:00:00 - ERROR - All LLM services failed for foo",
            "2026-04-30 12:00:01 - WARN - Circuit breaker OPEN for ciris_secondary",
            "2026-04-30 12:00:02 - WARN - IDMA fragility detected for thought x",
            "2026-04-30 12:00:03 - WARN - sign_ed25519 blocked",
            "2026-04-30 12:00:04 - INFO - conscience override to PONDER for thought y",
            "2026-04-30 12:00:05 - INFO - garbage line",
        ]
    )
    counts = _classify_log_lines(text)
    assert counts["llm_total_fail"] == 1
    assert counts["cb_open"] == 1
    assert counts["fragility"] == 1
    assert counts["sig_retry"] == 1
    assert counts["ponder_override"] == 1
    assert counts["other"] == 1
    assert counts["total"] == 6


def test_classify_skips_blank_lines():
    text = "\n\n   \nIDMA fragility detected\n\n"
    counts = _classify_log_lines(text)
    assert counts["total"] == 1
    assert counts["fragility"] == 1


def test_classify_empty_input():
    counts = _classify_log_lines("")
    assert counts["total"] == 0
    assert counts["other"] == 0
    assert counts["fragility"] == 0


# -----------------------------------------------------------------------------
# _container_name
# -----------------------------------------------------------------------------


def test_container_name_uses_explicit_when_present():
    """If the manager API gives us container_name, trust it verbatim."""
    agent = {
        "agent_id": "datum",
        "container_name": "ciris-something-custom",
        "occurrence_id": "002",
    }
    assert _container_name(agent) == "ciris-something-custom"


def test_container_name_default_occurrence_omits_suffix():
    """The 'default' occurrence is the singleton case — no suffix on container."""
    assert _container_name({"agent_id": "datum", "occurrence_id": "default"}) == "ciris-datum"
    assert _container_name({"agent_id": "datum", "occurrence_id": None}) == "ciris-datum"
    assert _container_name({"agent_id": "datum"}) == "ciris-datum"


def test_container_name_appends_non_default_occurrence():
    """Multi-occurrence (e.g. scout-2) needs the suffix to find its container."""
    agent = {"agent_id": "scout-remote-test-dahrb9", "occurrence_id": "002"}
    assert _container_name(agent) == "ciris-scout-remote-test-dahrb9-002"


# -----------------------------------------------------------------------------
# _gather_fleet
# -----------------------------------------------------------------------------


def test_gather_fleet_summarises_versions_and_states():
    agents = [
        {
            "agent_id": "a1",
            "server_id": "main",
            "version": "2.7.6",
            "cognitive_state": "WORK",
            "health": "healthy",
            "status": "running",
        },
        {
            "agent_id": "a2",
            "server_id": "main",
            "version": "2.7.6",
            "cognitive_state": "WAKEUP",
            "health": "healthy",
            "status": "running",
        },
        {
            "agent_id": "a3",
            "server_id": "scout1",
            "version": "2.0.2",
            "cognitive_state": "WORK",
            "health": "healthy",
            "status": "running",
        },
    ]
    result = _gather_fleet(_ctx(agents=agents))
    assert result["summary"]["total_agents"] == 3
    assert result["summary"]["version_uniform"] is False
    assert result["summary"]["versions"] == {"2.7.6": 2, "2.0.2": 1}
    assert result["summary"]["cognitive_states"] == {"WORK": 2, "WAKEUP": 1}
    # rows sorted by (server_id, agent_id)
    assert [r["agent_id"] for r in result["agents"]] == ["a1", "a2", "a3"]


def test_gather_fleet_uniform_when_all_match():
    agents = [
        {"agent_id": "a", "server_id": "main", "version": "v1", "cognitive_state": "WORK"},
        {"agent_id": "b", "server_id": "main", "version": "v1", "cognitive_state": "WORK"},
    ]
    assert _gather_fleet(_ctx(agents=agents))["summary"]["version_uniform"] is True


# -----------------------------------------------------------------------------
# _emit (output rendering)
# -----------------------------------------------------------------------------


def test_emit_json_round_trips():
    import json

    payload = {"x": 1, "list": [{"a": 1}], "nested": {"b": 2}}
    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit(_ctx(fmt="json"), payload)
    out = json.loads(buf.getvalue())
    assert out == payload


def test_emit_yaml_round_trips():
    import yaml

    payload = {"x": 1, "nested": {"b": 2}}
    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit(_ctx(fmt="yaml"), payload)
    assert yaml.safe_load(buf.getvalue()) == payload


def test_emit_table_separates_primitives_from_structured():
    """Mixed primitives/dicts shouldn't make a `--- key ---` heading per primitive
    — primitives go into one compact key/value table; only nested dicts/lists
    get their own headed section."""
    payload = {
        "summary": {
            "count": 5,
            "uniform": True,
            "by_status": {"running": 5},
        }
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit(_ctx(fmt="table"), payload)
    out = buf.getvalue()
    # Both primitives appear in the SAME table (so the parent renders them together)
    assert "count" in out and "uniform" in out
    # by_status (the only nested child) gets its own headed section
    assert "--- by_status ---" in out
    # No `--- count ---` or `--- uniform ---` headings — those are primitives
    assert "--- count ---" not in out
    assert "--- uniform ---" not in out


# -----------------------------------------------------------------------------
# _ssh_run unavailability path
# -----------------------------------------------------------------------------


def test_ssh_run_raises_when_key_missing(tmp_path, monkeypatch):
    """Without the deploy key, status should fail loudly via _SSHUnavailable
    rather than silently producing zero counts."""
    monkeypatch.setattr("ciris_manager_client.commands.status._SSH_KEY", tmp_path / "no-such-key")
    with pytest.raises(_SSHUnavailable):
        _ssh_run("example.invalid", "true")


def test_ssh_run_raises_on_connection_failure(tmp_path, monkeypatch):
    """Connection failures (vs command failures) must raise _SSHUnavailable so
    callers can mark the host unreachable instead of treating it as 'no incidents'."""
    fake_key = tmp_path / "fake_key"
    fake_key.write_text("dummy")
    monkeypatch.setattr("ciris_manager_client.commands.status._SSH_KEY", fake_key)

    fake_result = SimpleNamespace(returncode=255, stdout="", stderr="ssh: Connection refused")
    with patch("subprocess.run", return_value=fake_result):
        with pytest.raises(_SSHUnavailable, match="Connection refused"):
            _ssh_run("example.invalid", "true")


def test_ssh_run_returns_stdout_on_command_failure(tmp_path, monkeypatch):
    """A failed `docker exec` (e.g. container not present) should NOT crash the
    whole status report — return empty stdout so classify treats it as zero
    incidents and the report carries on."""
    fake_key = tmp_path / "fake_key"
    fake_key.write_text("dummy")
    monkeypatch.setattr("ciris_manager_client.commands.status._SSH_KEY", fake_key)

    fake_result = SimpleNamespace(returncode=1, stdout="", stderr="Error: No such container")
    with patch("subprocess.run", return_value=fake_result):
        # Must NOT raise — connection succeeded, the inner command failed
        out = _ssh_run("example.invalid", "docker exec missing true")
        assert out == ""
