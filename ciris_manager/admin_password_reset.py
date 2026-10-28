"""Reset an agent's ROOT `admin` password, offline, on the agent's own server.

Why this exists: the manager has stored each agent's admin password encrypted
in the registry since 2025-10, yet the live registry holds it for none of them.
Without it there is no SYSTEM_ADMIN session, and without that session a node
that is already rooted by the legacy `admin` account cannot be upgraded to a
fed-ID owner-binding (`POST /v1/self/upgrade-owner`).

What an earlier attempt got wrong, so it is not repeated:

- **The table.** Since ciris-server absorbed auth, the live certs are in persist's
  `cirislens_wa_cert`. The old `wa_cert` table still exists but is empty and
  nothing reads it. A tool that looks for `admin` there finds nothing, INSERTs
  a fresh ROOT into the dead table, then verifies against that same table, so
  it reports success twice and changes nothing that matters. This module never
  inserts: exactly one active ROOT `admin` or it refuses.
- **The premise.** Restarting a container does not restore a default password;
  the hash lives in the database.
- **The socket.** The manager host runs no agent containers, so the local Docker
  socket reaches none of them. This goes through the manager's per-server
  Docker client.
- **A live writer.** Writing a persist-owned table under a running server races
  its WAL. Merely *reading* the database from inside a live container coincided
  with datum dying on SIGBUS. So the agent must be stopped, and the write takes
  `BEGIN IMMEDIATE`, which fails fast if anything else holds the database.

The plaintext password never leaves the manager host: it is hashed here and
only the hash is handed to a short-lived helper container, which runs the
agent's own image with the stopped agent's volumes attached and no network.
The result is verified here, with a verifier that mirrors ciris-server's
`session.rs::verify_password` byte for byte.

SQLite agents only. PostgreSQL agents are refused rather than guessed at.
"""

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Dict, Optional

# ciris-server `session.rs`: PBKDF2-HMAC-SHA256, 100k iterations, 32-byte salt,
# 32-byte key, stored as STANDARD base64 of salt || key (88 chars).
PBKDF2_ITERATIONS = 100_000
PBKDF2_SALT_LEN = 32
PBKDF2_KEY_LEN = 32

DEFAULT_DB_PATH = "/app/data/ciris_engine.db"
RESULT_MARKER = "CIRIS_RESET_RESULT "

# States in which a container may still be writing its database.
_LIVE_STATES = {"running", "restarting", "paused", "removing"}


class ResetRefused(Exception):
    """The reset was not attempted because a precondition does not hold."""


class ResetFailed(Exception):
    """The reset was attempted and did not produce a usable password."""


def hash_password(password: str) -> str:
    """Hash exactly as ciris-server's `session.rs::hash_password` does."""
    salt = secrets.token_bytes(PBKDF2_SALT_LEN)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PBKDF2_ITERATIONS, dklen=PBKDF2_KEY_LEN
    )
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Mirror of ciris-server's `session.rs::verify_password`.

    Including its strictness: anything that is not exactly salt + key long is
    rejected, so a hash this accepts is one the server accepts.
    """
    if not stored_hash:
        return False
    try:
        decoded = base64.b64decode(stored_hash, validate=True)
    except ValueError:
        return False
    if len(decoded) != PBKDF2_SALT_LEN + PBKDF2_KEY_LEN:
        return False
    salt, stored_key = decoded[:PBKDF2_SALT_LEN], decoded[PBKDF2_SALT_LEN:]
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PBKDF2_ITERATIONS, dklen=PBKDF2_KEY_LEN
    )
    return hmac.compare_digest(key, stored_key)


def generate_password() -> str:
    """A 32-character URL-safe password - no shell or JSON escaping hazards."""
    return secrets.token_urlsafe(24)


# Runs INSIDE the helper container with the agent's own python, stdlib only.
# Kept as source text so the tests exercise exactly what ships to the server.
HELPER_SOURCE = r"""
import json, os, sqlite3, sys

TABLE = "cirislens_wa_cert"

def run(db_path, new_hash, apply):
    out = {"ok": False, "applied": False}
    if not os.path.exists(db_path):
        out["error"] = f"database not found at {db_path}"
        return out
    conn = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        out["integrity"] = integrity
        if integrity != "ok":
            out["error"] = f"database failed quick_check: {integrity}"
            return out
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone():
            out["error"] = (
                f"no {TABLE} table - this agent predates ciris-server auth; "
                "its certs are not where this tool writes"
            )
            return out
        # Fails immediately if anything else holds the database for writing.
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"SELECT wa_id, password_hash FROM {TABLE} "
            "WHERE name = 'admin' AND lower(role) = 'root' AND active = 1"
        ).fetchall()
        if len(rows) != 1:
            conn.execute("ROLLBACK")
            out["error"] = (
                f"expected exactly one active ROOT 'admin' in {TABLE}, found {len(rows)}; "
                "refusing - this tool never creates a ROOT"
            )
            return out
        wa_id, previous = rows[0]
        out["wa_id"] = wa_id
        out["previous_hash"] = previous
        out["total_rows"] = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        if not apply:
            conn.execute("ROLLBACK")
            out["ok"] = True
            return out
        cur = conn.execute(
            f"UPDATE {TABLE} SET password_hash = ? WHERE wa_id = ? AND name = 'admin'",
            (new_hash, wa_id),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            out["error"] = f"update touched {cur.rowcount} rows, expected 1; rolled back"
            return out
        conn.execute("COMMIT")
        out["stored_hash"] = conn.execute(
            f"SELECT password_hash FROM {TABLE} WHERE wa_id = ?", (wa_id,)
        ).fetchone()[0]
        out["applied"] = True
        out["ok"] = True
        return out
    except sqlite3.OperationalError as e:
        out["error"] = f"sqlite: {e} (is the agent still running?)"
        return out
    finally:
        conn.close()

if __name__ == "__main__":
    result = run(
        os.environ["CIRIS_RESET_DB"],
        os.environ.get("CIRIS_RESET_HASH", ""),
        os.environ.get("CIRIS_RESET_APPLY") == "1",
    )
    print("CIRIS_RESET_RESULT " + json.dumps(result))
    sys.exit(0 if result["ok"] else 1)
"""


def parse_helper_output(output: str) -> Dict[str, Any]:
    """Extract the helper's JSON result line from its combined output."""
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_MARKER):
            return dict(json.loads(line[len(RESULT_MARKER) :]))
    raise ResetFailed(f"helper produced no result line; output was:\n{output[-2000:]}")


def check_container(container: Any) -> None:
    """Refuse unless the agent is stopped and SQLite-backed."""
    container.reload()
    if container.status in _LIVE_STATES:
        raise ResetRefused(
            f"container {container.name} is {container.status}; stop it first "
            "(ciris-manager-client agent stop <agent_id>) - writing its database "
            "under a live server races the WAL"
        )
    env = container.attrs.get("Config", {}).get("Env") or []
    db_url = next((e.split("=", 1)[1] for e in env if e.startswith("DATABASE_URL=")), "")
    if db_url.startswith(("postgres://", "postgresql://")):
        raise ResetRefused(
            f"{container.name} uses PostgreSQL; this tool handles SQLite agents only"
        )


def run_helper(
    docker_client: Any,
    container: Any,
    new_hash: str,
    apply: bool,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Run the helper in the agent's own image with the agent's volumes."""
    config = container.attrs.get("Config", {})
    helper = docker_client.containers.create(
        config.get("Image"),
        entrypoint=["python3", "-c", HELPER_SOURCE],
        environment={
            "CIRIS_RESET_DB": db_path,
            "CIRIS_RESET_HASH": new_hash,
            "CIRIS_RESET_APPLY": "1" if apply else "0",
        },
        volumes_from=[container.id],
        network_mode="none",
        user=config.get("User") or None,
        labels={"ai.ciris.purpose": "admin-password-reset"},
    )
    try:
        helper.start()
        helper.wait(timeout=600)
        output = helper.logs(stdout=True, stderr=True).decode(errors="replace")
    finally:
        helper.remove(force=True)
    return parse_helper_output(output)


def reset_admin_password(
    docker_client: Any,
    container_name: str,
    new_password: Optional[str],
    apply: bool,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Check preconditions, run the helper, and verify the result here.

    With `apply=False` nothing is written: the helper reports the ROOT row it
    would change. With `apply=True` the stored hash is re-read and verified
    against `new_password` before success is reported.
    """
    container = docker_client.containers.get(container_name)
    check_container(container)

    if apply and not new_password:
        raise ResetRefused("apply requested without a password")
    new_hash = hash_password(new_password) if apply and new_password else ""

    result = run_helper(docker_client, container, new_hash, apply, db_path)
    if not result.get("ok"):
        raise ResetFailed(result.get("error", "helper reported failure without a reason"))

    if apply:
        if not verify_password(new_password or "", result.get("stored_hash")):
            raise ResetFailed(
                f"hash written for {result.get('wa_id')} does not verify; "
                "restore the previous hash before starting the agent"
            )
        result["verified"] = True
    return result
