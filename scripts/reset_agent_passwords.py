#!/usr/bin/env python3
"""
Reset a stopped agent's ROOT `admin` password.

Run on the manager host, from the manager's install:

    cd /opt/ciris-manager
    ciris-manager-client agent stop datum                      # must be stopped
    ./venv/bin/python scripts/reset_agent_passwords.py datum   # dry run: shows the row
    ./venv/bin/python scripts/reset_agent_passwords.py datum --apply
    ciris-manager-client agent start datum

Dry run is the default. It reports which ROOT row would change and writes
nothing. `--apply` writes a new hash, verifies it here against ciris-server's
own algorithm, saves the previous hash to a 0600 backup file, and prints the
new password once.

See ciris_manager/admin_password_reset.py for why each step is the way it is.
The previous version of this script assumed a restart restores a default
password, used the local Docker socket, and targeted agents that no longer
exist; it could not work.
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ciris_manager.admin_password_reset import (  # noqa: E402
    ResetFailed,
    ResetRefused,
    generate_password,
    reset_admin_password,
)
from ciris_manager.agent_registry import AgentRegistry  # noqa: E402
from ciris_manager.config.settings import CIRISManagerConfig  # noqa: E402
from ciris_manager.multi_server_docker import MultiServerDockerClient  # noqa: E402
from ciris_manager.utils.naming import container_name  # noqa: E402


def write_backup(backup_dir: Path, agent_key: str, result: dict) -> Path:
    """Save the previous hash so the change can be reverted."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"{agent_key}-{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "agent": agent_key,
                "wa_id": result.get("wa_id"),
                "previous_hash": result.get("previous_hash"),
                "saved_at": stamp,
            },
            f,
            indent=2,
        )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a stopped agent's ROOT admin password")
    parser.add_argument("agent_id")
    parser.add_argument("--server-id", help="Required when the agent id exists on several servers")
    parser.add_argument("--occurrence-id", help="Occurrence id for multi-occurrence agents")
    parser.add_argument(
        "--apply", action="store_true", help="Write the new hash (default: dry run)"
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the new password from stdin instead of generating one",
    )
    parser.add_argument("--config", default="/etc/ciris-manager/config.yml")
    parser.add_argument("--metadata", default="/opt/ciris/agents/metadata.json")
    parser.add_argument("--db-path", default="/app/data/ciris_engine.db")
    parser.add_argument("--backup-dir", default="/opt/ciris/agents/password-reset-backups")
    args = parser.parse_args()

    registry = AgentRegistry(Path(args.metadata))
    agent = registry.get_agent(
        args.agent_id, occurrence_id=args.occurrence_id, server_id=args.server_id
    )
    if agent is None:
        print(f"Agent {args.agent_id} not found in {args.metadata}", file=sys.stderr)
        return 2
    matches = registry.get_agents_by_agent_id(args.agent_id)
    if len(matches) > 1 and not args.server_id:
        print(
            f"{args.agent_id} exists on {len(matches)} servers; pass --server-id",
            file=sys.stderr,
        )
        return 2

    name = container_name(agent.agent_id, getattr(agent, "occurrence_id", None))
    config = CIRISManagerConfig.from_file(args.config)
    docker_client = MultiServerDockerClient(config.servers).get_client(agent.server_id)
    agent_key = (
        f"{agent.agent_id}-{getattr(agent, 'occurrence_id', None) or 'default'}-{agent.server_id}"
    )

    password = None
    if args.apply:
        if args.password_stdin:
            password = (
                sys.stdin.readline().rstrip("\n")
                if not sys.stdin.isatty()
                else getpass.getpass("New admin password: ")
            )
            if len(password) < 12:
                print("Password must be at least 12 characters", file=sys.stderr)
                return 2
        else:
            password = generate_password()

    print(
        f"{'APPLY' if args.apply else 'DRY RUN'}: {name} on server {agent.server_id}",
        file=sys.stderr,
    )
    try:
        result = reset_admin_password(docker_client, name, password, args.apply, args.db_path)
    except ResetRefused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 3
    except ResetFailed as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    print(
        f"  ROOT admin: {result['wa_id']}  ({result['total_rows']} certs in table)", file=sys.stderr
    )
    if not args.apply:
        print("  Nothing written. Re-run with --apply to reset.", file=sys.stderr)
        return 0

    backup = write_backup(Path(args.backup_dir), agent_key, result)
    print(f"  Previous hash saved to {backup}", file=sys.stderr)
    print("  New hash written and verified against ciris-server's algorithm.", file=sys.stderr)
    if not args.password_stdin:
        # Shown once, on stdout, so it can be captured without the log noise.
        print(password)
        print("  ^ SAVE THIS PASSWORD - it is not stored anywhere.", file=sys.stderr)
    print(f"  Next: ciris-manager-client agent start {agent.agent_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
