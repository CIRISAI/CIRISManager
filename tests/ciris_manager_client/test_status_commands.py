"""Tests for the `ciris-manager-client status` command set.

Covers the pure-Python helpers (incident classification, container name
derivation, output rendering) without exercising SSH or the manager API.
SSH/API paths are integration-tested manually against production.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest

from ciris_manager_client.commands.status import (
    _classify_log_lines,
    _container_name,
    _emit,
    _gather_fleet,
    _CERT_WARN_DAYS,
    _NOTABLE,
    _ORIGIN_CERTS,
    _SERVER_HOSTS,
    _SSHUnavailable,
    _gather_reconcile,
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


# -----------------------------------------------------------------------------
# Regression: classifier vs. real production logs
# -----------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "incidents_sample.log"


def test_classifier_scores_against_real_production_log():
    """The classifier must actually match real agent output.

    Guards the 2026-07-30 finding: every notable pattern scored zero against
    production logs containing thousands of ERROR lines, so `status all`
    reported "clean" while an agent had been down for three weeks. A classifier
    that matches nothing is worse than no classifier, because it manufactures
    a green signal. If this test fails, the log format moved - re-derive the
    patterns from a fresh capture rather than deleting the assertion.
    """
    counts = _classify_log_lines(FIXTURE.read_text())

    assert counts["total"] > 0, "fixture is empty"
    # The single most important property: real logs must not classify as all-benign.
    notable = sum(counts.get(c, 0) for c in _NOTABLE)
    assert notable > 0, "no notable category matched a real production log"

    # Each failure mode found during the soak review must stay detected.
    for category in (
        "telemetry_flush_fail",
        "persistence_fk_fail",
        "scheduler_task_fail",
        "shutdown_livelock",
        "verify_security_alert",
        "verify_hash_mismatch",
        "verify_no_consensus",
        "verify_dns_disagree",
        "config_warn",
    ):
        assert counts[category] > 0, f"{category} no longer matches production output"


def test_ciris_verify_logger_name_is_lowercase():
    """The old pattern was "CIRISVerify"; the logger is actually `ciris_verify`.

    That single case mismatch meant no CIRISVerify line was ever classified.
    """
    line = "2026-07-30 19:24:48.319 - WARNING - ciris_verify - [core::dns] something"
    counts = _classify_log_lines(line)
    assert counts["other"] == 0
    assert counts["verify_warn"] == 1


def test_dns_disagreement_is_not_notable_but_security_alert_is():
    """Registry lag is continuous background noise; the escalation is not.

    Treating both as notable is what buried the real findings.
    """
    assert "verify_dns_disagree" not in _NOTABLE
    assert "verify_security_alert" in _NOTABLE
    assert "verify_no_consensus" in _NOTABLE


# -----------------------------------------------------------------------------
# _gather_reconcile — registry vs actually-running containers
# -----------------------------------------------------------------------------


def test_reconcile_flags_missing_container():
    """A registered agent with no running container must be reported MISSING.

    This is the check the crash-loop watchdog cannot make: scout2's agent
    exited once with RestartCount=0 and stayed down for three weeks, which
    never looked like a crash loop.
    """
    ctx = SimpleNamespace(
        client=_FakeClient(
            [
                {"agent_id": "datum", "server_id": "main", "container_name": "ciris-datum"},
                {"agent_id": "gone", "server_id": "scout2", "container_name": "ciris-gone"},
            ]
        ),
        output_format="json",
    )

    def fake_ssh(host, cmd, timeout=30):
        return "ciris-datum\nciris-nginx\n" if host == _SERVER_HOSTS["main"] else "ciris-nginx\n"

    with patch("ciris_manager_client.commands.status._ssh_run", side_effect=fake_ssh):
        result = _gather_reconcile(ctx)

    by_id = {r["agent_id"]: r for r in result["agents"]}
    assert by_id["datum"]["status"] == "running"
    assert by_id["gone"]["status"] == "MISSING"
    assert result["summary"]["missing_containers"] == 1
    assert result["summary"]["verdict"] == "review_needed"


def test_reconcile_clean_when_all_running():
    ctx = SimpleNamespace(
        client=_FakeClient(
            [{"agent_id": "datum", "server_id": "main", "container_name": "ciris-datum"}]
        ),
        output_format="json",
    )
    with patch(
        "ciris_manager_client.commands.status._ssh_run",
        return_value="ciris-datum\n",
    ):
        result = _gather_reconcile(ctx)
    assert result["summary"]["missing_containers"] == 0
    assert result["summary"]["verdict"] == "ok"


def test_reconcile_degrades_when_host_unreachable():
    """An unreachable host must not be reported as a missing container.

    Conflating "we couldn't look" with "it isn't there" would page on every
    transient network blip.
    """
    ctx = SimpleNamespace(
        client=_FakeClient(
            [{"agent_id": "datum", "server_id": "main", "container_name": "ciris-datum"}]
        ),
        output_format="json",
    )
    with patch(
        "ciris_manager_client.commands.status._ssh_run",
        side_effect=_SSHUnavailable("host down"),
    ):
        result = _gather_reconcile(ctx)
    assert result["agents"][0]["status"] == "host_unreachable"
    assert result["summary"]["missing_containers"] == 0


# -----------------------------------------------------------------------------
# _gather_endpoints — cert expiry thresholds
# -----------------------------------------------------------------------------


def test_origin_certs_checked_by_ip_not_public_hostname():
    """Origin certs must be probed at the origin IP.

    The public hostname resolves to Cloudflare, whose edge cert auto-renews and
    was perfectly healthy throughout the 46-day outage. Checking the edge would
    have reported green the entire time.
    """
    for _label, ip, sni in _ORIGIN_CERTS:
        assert ip[0].isdigit(), f"{_label} must be probed by IP, got {ip!r}"
        assert not sni[0].isdigit(), f"{_label} needs a hostname for SNI, got {sni!r}"

    # Both scout origins serve the same hostname from different filesystems and
    # must be listed separately - scout2's cert is currently hand-copied.
    scout_entries = [e for e in _ORIGIN_CERTS if e[2] == "scoutapilb.ciris.ai"]
    assert len(scout_entries) == 2


def test_cert_warn_threshold_exceeds_certbot_renewal_window():
    """Warn only after certbot has already had a chance to renew and failed.

    Certbot renews at 30 days remaining; warning above that would fire on every
    healthy cert in its normal renewal window.
    """
    assert _CERT_WARN_DAYS < 30
