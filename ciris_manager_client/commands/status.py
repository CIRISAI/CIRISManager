"""
Fleet ops/security status commands for CIRIS CLI.

These commands roll up fleet health, incident classification, deployment
history, and security signals across all servers in one place. Designed to
replace the ad-hoc SSH+docker exec pipelines we use for "is everything OK?"
checks.

Subcommands:
    fleet        Container/cognitive state across all agents + version uniformity
    incidents    Per-agent incident counts classified by category (today)
    deployments  Pending deployments + recent history
    security     Manager admin actions, OAuth failures, env drift signals
    all          Composite of all of the above

The fleet/deployments/security data come from the manager API. Per-agent
incident classification requires reading container logs, so it falls back to
SSH+docker exec (same pattern as `inspect`). Skipped gracefully if SSH is
unavailable.
"""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ciris_manager_client.output import OutputFormatterImpl

# Containers and hosts derived from CLAUDE.md production map. We resolve the
# host per-agent at runtime via the registered server_id and a small map below.
# These are static infrastructure facts; do not parameterize unless adding a
# new server.
_SERVER_HOSTS: Dict[str, str] = {
    "main": "45.76.231.182",
    "scout1": "144.202.55.195",
    "scout2": "45.76.18.133",
}
_MANAGER_HOST = "45.76.226.222"

# Incident classification: substring -> category. Order matters; first match wins.
# If you tweak these, re-run `status incidents` and confirm the categories still
# capture the long tail. Specifically: "All LLM services failed" must beat the
# more general "llm_service" filter.
_INCIDENT_PATTERNS: List[Tuple[str, str]] = [
    ("All LLM services failed", "llm_total_fail"),
    ("Circuit breaker OPEN", "cb_open"),
    ("transitioning to half-open", "cb_half_open"),
    ("IDMA fragility", "fragility"),
    ("sign_ed25519 blocked", "sig_retry"),
    ("conscience override to PONDER", "ponder_override"),
    ("Blocking repeated SPEAK", "speak_blocked"),
    ("RATE LIMIT", "rate_limit"),
    ("ciris_secondary error", "secondary_err"),
    ("ciris_primary error", "primary_err"),
    ("Failed to convert node", "config_warn"),
    ("No pricing found for model", "pricing_warn"),
    ("CIRISVerify", "verify_warn"),
]

# Patterns that signal cognitive-health attention (a non-zero count is worth
# surfacing to humans). The rest is treated as background noise.
_NOTABLE = {
    "llm_total_fail",
    "cb_open",
    "ponder_override",
    "speak_blocked",
    "secondary_err",
    "primary_err",
}

_SSH_KEY = Path.home() / ".ssh" / "ciris_deploy"


class _SSHUnavailable(RuntimeError):
    """Raised when we can't reach a remote host. Caller decides whether to skip."""


def _ssh_run(host: str, cmd: str, timeout: int = 30) -> str:
    """Run a command on a remote host via the standard ciris_deploy key.

    Raises _SSHUnavailable on connection problems so callers can degrade
    gracefully instead of failing the whole status call.
    """
    if not _SSH_KEY.exists():
        raise _SSHUnavailable(f"SSH key not found at {_SSH_KEY}")
    full = [
        "ssh",
        "-i",
        str(_SSH_KEY),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={min(timeout, 10)}",
        "-o",
        "BatchMode=yes",
        f"root@{host}",
        cmd,
    ]
    try:
        result = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise _SSHUnavailable(f"SSH to {host} timed out after {timeout}s") from e
    if result.returncode != 0:
        # Connection-level failures (host unreachable, bad key, etc.) — degrade.
        # Command-level failures (the `docker exec` itself failed) bubble up
        # as the empty-string output, which classify_incidents treats as zero.
        if "Connection" in result.stderr or "Permission denied" in result.stderr:
            raise _SSHUnavailable(f"SSH to {host} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def _container_name(agent: Dict[str, Any]) -> str:
    """Derive container name from an agent record.

    For multi-occurrence agents (scout-2), the container name embeds the
    occurrence_id (e.g. `ciris-scout-remote-test-dahrb9-002`). The agent
    record from list_agents includes `container_name` directly when the
    manager knows it; we trust that when present and fall back to the
    naming convention otherwise.
    """
    cn = agent.get("container_name")
    if cn:
        return str(cn)
    aid = agent.get("agent_id", "")
    occ = agent.get("occurrence_id")
    if occ and occ not in ("default", None):
        return f"ciris-{aid}-{occ}"
    return f"ciris-{aid}"


def _emit(ctx: Any, payload: Any, default_columns: Optional[List[str]] = None) -> None:
    """Render payload according to ctx.output_format.

    Accepts either a list-of-dicts (table-friendly) or a dict (sectioned).
    In table mode, recurses one level for sectioned dicts (so the composite
    `all` command renders each top-level section as its own block of tables
    instead of stuffing nested dicts into a single key/value row).
    """
    fmt = ctx.output_format
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
        return
    if fmt == "yaml":
        print(yaml.safe_dump(payload, sort_keys=False, default_flow_style=False))
        return
    _render_table(payload, default_columns, depth=0)


def _render_table(
    payload: Any, default_columns: Optional[List[str]] = None, depth: int = 0
) -> None:
    """Recursive table renderer. Sections are headed by `=== name ===` (depth 0)
    or `--- name ---` (depth 1+). Lists become tables; primitive values are
    printed inline; nested dicts recurse one more level."""
    formatter = OutputFormatterImpl()

    if isinstance(payload, list):
        print(formatter.format_table(payload, columns=default_columns))
        return

    if not isinstance(payload, dict):
        print(payload)
        return

    # Split children into (primitives, structured) so primitives go in one
    # compact key/value table and only structured children get their own section.
    primitives = {k: v for k, v in payload.items() if not isinstance(v, (dict, list))}
    structured = {k: v for k, v in payload.items() if isinstance(v, (dict, list))}

    if primitives:
        print(formatter.format_table([{"key": k, "value": v} for k, v in primitives.items()]))

    for section, data in structured.items():
        header = f"=== {section} ===" if depth == 0 else f"--- {section} ---"
        print(f"\n{header}")
        if isinstance(data, list):
            print(formatter.format_table(data))
        elif isinstance(data, dict):
            if all(not isinstance(v, (dict, list)) for v in data.values()):
                # all primitives: one compact key/value table
                print(formatter.format_table([{"key": k, "value": v} for k, v in data.items()]))
            else:
                _render_table(data, depth=depth + 1)


# -----------------------------------------------------------------------------
# Section gatherers — each returns a dict suitable for json/yaml or a list for
# table mode. Kept independent so `all` can call any subset.
# -----------------------------------------------------------------------------


def _gather_fleet(ctx: Any) -> Dict[str, Any]:
    """Fleet snapshot from manager API."""
    agents = ctx.client.list_agents()
    versions = Counter(a.get("version") or "<none>" for a in agents)
    cog_states = Counter(a.get("cognitive_state") or "<none>" for a in agents)
    healths = Counter(a.get("health") or "<unknown>" for a in agents)

    rows = []
    for a in sorted(agents, key=lambda x: (x.get("server_id", ""), x.get("agent_id", ""))):
        rows.append(
            {
                "agent_id": a.get("agent_id"),
                "server": a.get("server_id"),
                "status": a.get("status"),
                "health": a.get("health"),
                "cognitive_state": a.get("cognitive_state"),
                "version": a.get("version"),
                "update_available": a.get("update_available"),
            }
        )
    return {
        "summary": {
            "total_agents": len(agents),
            "version_uniform": len(versions) == 1,
            "versions": dict(versions),
            "cognitive_states": dict(cog_states),
            "health": dict(healths),
        },
        "agents": rows,
    }


def _classify_log_lines(text: str) -> Dict[str, int]:
    """Bucket log lines by _INCIDENT_PATTERNS. First match wins per line."""
    counts: Dict[str, int] = {cat: 0 for _, cat in _INCIDENT_PATTERNS}
    counts["other"] = 0
    counts["total"] = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        counts["total"] += 1
        for needle, cat in _INCIDENT_PATTERNS:
            if needle in line:
                counts[cat] += 1
                break
        else:
            counts["other"] += 1
    return counts


def _gather_incidents(ctx: Any, since_date: Optional[str] = None) -> Dict[str, Any]:
    """Per-agent incident counts classified by category.

    Reads each agent's `incidents_latest.log` via SSH+docker exec. If SSH is
    unavailable for a server, that agent's incidents come back as `<unreachable>`
    and the report continues — better than failing the whole command.
    """
    from datetime import datetime, timezone

    if since_date is None:
        since_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    agents = ctx.client.list_agents()
    rows: List[Dict[str, Any]] = []
    notable_total = 0
    unreachable_hosts: List[str] = []

    for agent in sorted(agents, key=lambda a: (a.get("server_id", ""), a.get("agent_id", ""))):
        agent_id = agent.get("agent_id", "")
        server_id = agent.get("server_id", "")
        host = _SERVER_HOSTS.get(server_id)
        container = _container_name(agent)

        row: Dict[str, Any] = {
            "agent_id": agent_id,
            "server": server_id,
        }

        if host is None:
            row["status"] = f"unknown_server:{server_id}"
            rows.append(row)
            continue

        # grep date-prefix on the agent's incidents log inside its container.
        # Use single grep to keep the SSH round-trip short.
        cmd = (
            f"docker exec {container} sh -c "
            f"'grep \"^{since_date}\" /app/logs/incidents_latest.log 2>/dev/null'"
        )
        try:
            text = _ssh_run(host, cmd, timeout=20)
        except _SSHUnavailable as e:
            row["status"] = "unreachable"
            row["error"] = str(e)[:120]
            if host not in unreachable_hosts:
                unreachable_hosts.append(host)
            rows.append(row)
            continue

        counts = _classify_log_lines(text)
        row["status"] = "ok"
        # Promote notable categories to top-level keys; collapse rest into row["benign_total"].
        notable_in_row = sum(counts.get(c, 0) for c in _NOTABLE)
        notable_total += notable_in_row
        for cat in _NOTABLE:
            row[cat] = counts.get(cat, 0)
        row["fragility"] = counts.get("fragility", 0)
        row["sig_retry"] = counts.get("sig_retry", 0)
        row["benign_total"] = counts["total"] - notable_in_row - row["fragility"] - row["sig_retry"]
        row["total"] = counts["total"]
        rows.append(row)

    return {
        "summary": {
            "since_date_utc": since_date,
            "agents_reporting": sum(1 for r in rows if r.get("status") == "ok"),
            "agents_unreachable": sum(1 for r in rows if r.get("status") == "unreachable"),
            "notable_incident_total": notable_total,
            "verdict": "clean" if notable_total == 0 else "review_needed",
        },
        "agents": rows,
    }


def _gather_deployments(ctx: Any) -> Dict[str, Any]:
    """Pending deployments + manager status snapshot."""
    pending = ctx.client.get_pending_deployments() or {}
    manager_status = ctx.client.get_status() or {}

    pending_list = pending.get("deployments", []) if isinstance(pending, dict) else []
    rows = []
    for d in pending_list:
        rows.append(
            {
                "deployment_id": d.get("deployment_id"),
                "version": d.get("version"),
                "status": d.get("status"),
                "strategy": d.get("strategy"),
                "staged_at": d.get("staged_at"),
                "agents": d.get("affected_agents"),
                "commit": d.get("commit"),
            }
        )

    return {
        "summary": {
            "pending_count": len(pending_list),
            "manager_version": manager_status.get("version"),
            "manager_status": manager_status.get("status") or "unknown",
        },
        "pending": rows,
    }


def _gather_security(ctx: Any) -> Dict[str, Any]:
    """Manager admin signals: recent ERROR/WARNING in manager log + sshd auth failures.

    Hits both the manager host (systemd journal) and each agent host
    (auth.log) via SSH. Degrades gracefully if SSH unavailable.
    """
    sections: Dict[str, Any] = {}

    # Manager service errors/warnings in last hour
    try:
        log = _ssh_run(
            _MANAGER_HOST,
            "journalctl -u ciris-manager --since '1 hour ago' --no-pager "
            "| grep -iE 'error|warning' "
            "| grep -v 'GET /' | grep -v 'POST /' "
            "| grep -v 'Early adopter group is' "
            "| wc -l",
            timeout=20,
        )
        sections["manager_errors_last_hour"] = int(log.strip() or 0)
    except (_SSHUnavailable, ValueError) as e:
        sections["manager_errors_last_hour"] = f"unreachable: {str(e)[:100]}"

    # Failed sshd auth on all hosts in last 24h
    auth_failures: Dict[str, Any] = {}
    for label, host in [("manager", _MANAGER_HOST), *_SERVER_HOSTS.items()]:
        try:
            out = _ssh_run(
                host,
                "journalctl _COMM=sshd --since '24 hours ago' --no-pager 2>/dev/null "
                "| grep -E 'Failed password|Invalid user' | wc -l",
                timeout=20,
            )
            auth_failures[label] = int(out.strip() or 0)
        except (_SSHUnavailable, ValueError) as e:
            auth_failures[label] = f"unreachable: {str(e)[:80]}"
    sections["sshd_failed_auth_last_24h"] = auth_failures

    # OAuth login failures from manager log (401s on /oauth/user)
    try:
        out = _ssh_run(
            _MANAGER_HOST,
            "journalctl -u ciris-manager --since '24 hours ago' --no-pager 2>/dev/null "
            "| grep -c '/oauth/user.*401'",
            timeout=20,
        )
        sections["oauth_user_401_last_24h"] = int(out.strip() or 0)
    except (_SSHUnavailable, ValueError) as e:
        sections["oauth_user_401_last_24h"] = f"unreachable: {str(e)[:100]}"

    return sections


# -----------------------------------------------------------------------------
# Public command handlers
# -----------------------------------------------------------------------------


class StatusCommands:
    """Fleet ops/security status commands."""

    @staticmethod
    def fleet(ctx: Any, args: Namespace) -> int:
        _emit(ctx, _gather_fleet(ctx))
        return 0

    @staticmethod
    def incidents(ctx: Any, args: Namespace) -> int:
        since = getattr(args, "since", None)
        _emit(ctx, _gather_incidents(ctx, since_date=since))
        return 0

    @staticmethod
    def deployments(ctx: Any, args: Namespace) -> int:
        _emit(ctx, _gather_deployments(ctx))
        return 0

    @staticmethod
    def security(ctx: Any, args: Namespace) -> int:
        _emit(ctx, _gather_security(ctx))
        return 0

    @staticmethod
    def all(ctx: Any, args: Namespace) -> int:
        since = getattr(args, "since", None)
        composite = {
            "fleet": _gather_fleet(ctx),
            "deployments": _gather_deployments(ctx),
            "incidents": _gather_incidents(ctx, since_date=since),
            "security": _gather_security(ctx),
        }
        _emit(ctx, composite)
        # Exit non-zero if any notable incidents OR manager errors — useful for cron.
        notable = composite["incidents"]["summary"]["notable_incident_total"]
        mgr_err = composite["security"].get("manager_errors_last_hour", 0)
        return 0 if notable == 0 and (not isinstance(mgr_err, int) or mgr_err == 0) else 1
