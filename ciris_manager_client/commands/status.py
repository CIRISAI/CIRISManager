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
    endpoints    End-to-end probe of public URLs + origin cert expiry
    reconcile    Registered agents vs actually-running containers
    all          Composite of all of the above

The fleet/deployments/security data come from the manager API. Per-agent
incident classification requires reading container logs, so it falls back to
SSH+docker exec (same pattern as `inspect`). Skipped gracefully if SSH is
unavailable.

`endpoints` and `reconcile` exist because of the 2026-07-30 soak review, where
every other section reported green while (a) agents.ciris.ai had served an
expired origin cert for 46 days, making the whole vhost return Cloudflare 526,
and (b) an agent container had been gone for three weeks. Neither is visible
from inside a container or from the manager API, so both are checked from the
outside. `endpoints` deliberately requires no auth token - the outage it
diagnoses also breaks the OAuth flow needed to obtain one.
"""

from __future__ import annotations

import datetime as datetime_mod
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
#
# These MUST be derived from real production logs, not from the failure modes we
# expect. The 2026-07-30 soak review found every pattern below the divider
# scoring zero against logs containing thousands of ERROR lines, so `status all`
# reported "clean" while an agent had been down for three weeks. Any edit here
# should be checked against tests/ciris_manager_client/fixtures/incidents_sample.log,
# which is a verbatim capture from production.
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
    # --- observed in production 2026-07-30; all of these previously fell into
    # `other` or matched nothing at all ---
    # Persistence: a scheduled task outliving its parent row retries forever.
    ("FOREIGN KEY constraint failed", "persistence_fk_fail"),
    ("Failed to trigger task", "scheduler_task_fail"),
    # Shutdown processor livelocks polling for a task that will never return.
    ("Shutdown task disappeared", "shutdown_livelock"),
    # Telemetry flush retrying a non-retryable auth failure on a fixed timer.
    ("FLUSH FAILED", "telemetry_flush_fail"),
    ("verify_unknown_key", "telemetry_auth_fail"),
    # Secrets bootstrap corruption (see RCA-secrets-master-key-zero-byte.md).
    ("Master key must be exactly 32 bytes", "secrets_bootstrap_corruption"),
    # CIRISVerify. NOTE: the logger name is `ciris_verify`, lower/underscore -
    # the old "CIRISVerify" pattern never matched a single line.
    ("SECURITY ALERT", "verify_security_alert"),
    ("HASH MISMATCH", "verify_hash_mismatch"),
    ("cannot establish trusted consensus", "verify_no_consensus"),
    ("DNS DISAGREEMENT", "verify_dns_disagree"),
    ("ciris_verify", "verify_warn"),
    ("Failed to convert node", "config_warn"),
    ("No pricing found for model", "pricing_warn"),
]

# Patterns that signal attention (a non-zero count is worth surfacing to humans).
# The rest is treated as background noise.
#
# `verify_dns_disagree` and `verify_warn` are deliberately NOT notable: the EU
# registry lagging the US one produces a continuous stream of those, and burying
# real findings under them is what made the category useless. The escalated
# forms (`verify_security_alert`, `verify_no_consensus`) ARE notable.
_NOTABLE = {
    "llm_total_fail",
    "cb_open",
    "ponder_override",
    "speak_blocked",
    "secondary_err",
    "primary_err",
    "persistence_fk_fail",
    "scheduler_task_fail",
    "shutdown_livelock",
    "telemetry_flush_fail",
    "telemetry_auth_fail",
    "secrets_bootstrap_corruption",
    "verify_security_alert",
    "verify_hash_mismatch",
    "verify_no_consensus",
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

        # grep the date prefix across ALL retained incident logs, not just the
        # `incidents_latest.log` symlink. Under load these rotate every few
        # hours, so reading only the current file silently redefines "today"
        # as "the last couple of hours" - which is how a full soak window
        # looked clean. `cat` the glob so rotated files are included.
        cmd = (
            f"docker exec {container} sh -c "
            f"'cat /app/logs/incidents_*.log 2>/dev/null | grep \"^{since_date}\"'"
        )
        try:
            text = _ssh_run(host, cmd, timeout=30)
        except _SSHUnavailable as e:
            row["status"] = "unreachable"
            row["error"] = str(e)[:120]
            if host not in unreachable_hosts:
                unreachable_hosts.append(host)
            rows.append(row)
            continue

        counts = _classify_log_lines(text)
        row["status"] = "ok"
        # There are too many notable categories to give each its own column, so
        # the row carries a total plus a compact breakdown of only the non-zero
        # ones. Full per-category counts stay available under `counts` for
        # --format json.
        notable_in_row = sum(counts.get(c, 0) for c in _NOTABLE)
        notable_total += notable_in_row
        hits = {c: counts.get(c, 0) for c in sorted(_NOTABLE) if counts.get(c, 0)}
        row["notable"] = ", ".join(f"{c}={n}" for c, n in hits.items()) or "-"
        row["notable_total"] = notable_in_row
        row["benign_total"] = counts["total"] - notable_in_row
        row["total"] = counts["total"]
        if getattr(ctx, "output_format", "table") != "table":
            # Nested dict would wreck the table layout; machine formats get the
            # full per-category breakdown.
            row["counts"] = {c: n for c, n in counts.items() if n and c != "total"}
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


# Public endpoints probed end-to-end. Every internal signal read green through
# the 46-day agents.ciris.ai outage in 2026-06/07 because nothing ever tested
# the path a real client uses: expired origin cert -> Cloudflare 526. Health
# has to be measured where the user sits, not inside the container.
_PUBLIC_ENDPOINTS: List[Tuple[str, str, int]] = [
    ("manager_api", "https://agents.ciris.ai/manager/v1/health", 200),
    ("manager_gui", "https://agents.ciris.ai/", 200),
    ("scout_api", "https://scoutapilb.ciris.ai/health", 200),
]

# Origin certs to check, as (label, origin_ip, sni_hostname).
#
# These MUST be checked against the origin IP, not the public hostname: the
# public name resolves to Cloudflare, whose edge cert auto-renews and is never
# the thing that breaks. The 46-day outage was an expired *origin* cert behind
# a perfectly healthy edge cert. Both scout origins are listed separately
# because they serve the same hostname from different filesystems - scout2's
# cert is currently hand-copied, so it can go stale independently of scout1.
_ORIGIN_CERTS: List[Tuple[str, str, str]] = [
    ("main", "45.76.231.182", "agents.ciris.ai"),
    ("scout1", "144.202.55.195", "scoutapilb.ciris.ai"),
    ("scout2", "45.76.18.133", "scoutapilb.ciris.ai"),
]

# Warn this far ahead of expiry. Certbot renews at 30 days remaining, so a cert
# below this threshold means renewal has already failed at least once.
_CERT_WARN_DAYS = 21

# Cloudflare 403s requests with the default urllib User-Agent, which would make
# every probe look like a failure. Identify ourselves honestly instead.
_PROBE_UA = "ciris-manager-client/status-endpoints"


def _cert_not_after(der: bytes) -> "datetime_mod.datetime":
    """Extract notAfter (UTC) from a DER-encoded certificate.

    ssl.getpeercert() only returns a parsed dict when the chain was verified,
    and we intentionally skip verification to probe origins by IP - so parse
    the DER ourselves.
    """
    from datetime import timezone

    from cryptography import x509

    cert = x509.load_der_x509_certificate(der)
    try:
        return cert.not_valid_after_utc
    except AttributeError:  # cryptography < 42
        return cert.not_valid_after.replace(tzinfo=timezone.utc)


def _gather_endpoints(ctx: Any) -> Dict[str, Any]:
    """Probe public endpoints end-to-end and check origin cert expiry.

    Deliberately uses the public hostname (not localhost, not the VPC IP) so
    that TLS, Cloudflare, and nginx routing are all in the path.
    """
    import ssl
    import socket
    from datetime import datetime, timezone
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    rows: List[Dict[str, Any]] = []
    problems = 0

    for name, url, expect in _PUBLIC_ENDPOINTS:
        row: Dict[str, Any] = {"endpoint": name, "url": url, "expect": expect}
        try:
            req = Request(url, headers={"User-Agent": _PROBE_UA})  # noqa: S310 - fixed https
            with urlopen(req, timeout=15) as resp:  # noqa: S310
                code = resp.status
        except HTTPError as e:
            # An HTTP error status still means we reached an origin; record it.
            # A 526 here is the exact signature of an expired origin cert.
            code = e.code
        except (URLError, socket.timeout, ssl.SSLError) as e:
            row["status"] = "unreachable"
            row["error"] = str(e)[:120]
            problems += 1
            rows.append(row)
            continue
        row["code"] = code
        row["status"] = "ok" if code == expect else "unexpected_code"
        if code != expect:
            problems += 1
        rows.append(row)

    cert_rows: List[Dict[str, Any]] = []
    for label, ip, sni in _ORIGIN_CERTS:
        crow: Dict[str, Any] = {"origin": label, "host": sni, "ip": ip}
        try:
            # Verification is disabled deliberately: we are connecting by IP and
            # only want the expiry date out of the presented chain. Hostname
            # validation would fail on the IP and tell us nothing useful.
            cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            cctx.check_hostname = False
            cctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((ip, 443), timeout=15) as sock:
                with cctx.wrap_socket(sock, server_hostname=sni) as ssock:
                    der = ssock.getpeercert(binary_form=True)
            not_after = _cert_not_after(der)
            days = (not_after - datetime.now(timezone.utc)).days
            crow["expires"] = not_after.strftime("%Y-%m-%d")
            crow["days_left"] = days
            crow["status"] = "ok" if days >= _CERT_WARN_DAYS else "EXPIRING"
            if days < _CERT_WARN_DAYS:
                problems += 1
        except Exception as e:  # noqa: BLE001 - any failure here is a real signal
            crow["status"] = "error"
            crow["error"] = str(e)[:120]
            problems += 1
        cert_rows.append(crow)

    return {
        "summary": {
            "endpoints_checked": len(rows),
            "origins_checked": len(cert_rows),
            "problems": problems,
            "verdict": "ok" if problems == 0 else "review_needed",
        },
        "endpoints": rows,
        "origin_certificates": cert_rows,
    }


def _gather_reconcile(ctx: Any) -> Dict[str, Any]:
    """Reconcile the agent registry against containers actually running.

    The crash-loop watchdog only fires on repeated restarts, so a container
    that exits once and stays exited is invisible to it. That is exactly how
    the scout2 agent stayed dead for three weeks after a host reboot with
    RestartCount=0. This check answers the different question: for every agent
    the registry knows about, is a container actually running for it?
    """
    agents = ctx.client.list_agents()

    # One docker ps per host rather than per agent - keeps this to 3 round trips.
    running_by_host: Dict[str, Any] = {}
    for server_id, host in _SERVER_HOSTS.items():
        try:
            out = _ssh_run(
                host,
                "docker ps --filter 'name=ciris' --format '{{.Names}}'",
                timeout=20,
            )
            running_by_host[server_id] = set(out.split())
        except _SSHUnavailable as e:
            running_by_host[server_id] = e  # sentinel: host unreachable

    rows: List[Dict[str, Any]] = []
    missing = 0
    for agent in sorted(agents, key=lambda a: (a.get("server_id", ""), a.get("agent_id", ""))):
        server_id = agent.get("server_id", "")
        container = _container_name(agent)
        row: Dict[str, Any] = {
            "agent_id": agent.get("agent_id"),
            "server": server_id,
            "container": container,
        }
        known = running_by_host.get(server_id)
        if known is None:
            row["status"] = f"unknown_server:{server_id}"
        elif isinstance(known, _SSHUnavailable):
            row["status"] = "host_unreachable"
        elif container in known:
            row["status"] = "running"
        else:
            row["status"] = "MISSING"
            missing += 1
        rows.append(row)

    return {
        "summary": {
            "registered_agents": len(rows),
            "missing_containers": missing,
            "verdict": "ok" if missing == 0 else "review_needed",
        },
        "agents": rows,
    }


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
    def endpoints(ctx: Any, args: Namespace) -> int:
        result = _gather_endpoints(ctx)
        _emit(ctx, result)
        return 0 if result["summary"]["problems"] == 0 else 1

    @staticmethod
    def reconcile(ctx: Any, args: Namespace) -> int:
        result = _gather_reconcile(ctx)
        _emit(ctx, result)
        return 0 if result["summary"]["missing_containers"] == 0 else 1

    @staticmethod
    def all(ctx: Any, args: Namespace) -> int:
        since = getattr(args, "since", None)
        composite = {
            "fleet": _gather_fleet(ctx),
            "endpoints": _gather_endpoints(ctx),
            "reconcile": _gather_reconcile(ctx),
            "deployments": _gather_deployments(ctx),
            "incidents": _gather_incidents(ctx, since_date=since),
            "security": _gather_security(ctx),
        }
        _emit(ctx, composite)
        # Exit non-zero if anything notable — useful for cron.
        # `endpoints` and `reconcile` are included because they are the two
        # checks that would have caught the 2026-07-30 P0s (46-day expired cert,
        # agent container missing for 3 weeks) which every other section
        # reported as green.
        notable = composite["incidents"]["summary"]["notable_incident_total"]
        mgr_err = composite["security"].get("manager_errors_last_hour", 0)
        endpoint_problems = composite["endpoints"]["summary"]["problems"]
        missing = composite["reconcile"]["summary"]["missing_containers"]
        ok = (
            notable == 0
            and (not isinstance(mgr_err, int) or mgr_err == 0)
            and endpoint_problems == 0
            and missing == 0
        )
        return 0 if ok else 1
