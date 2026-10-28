"""Resetting an agent's ROOT admin password.

The previous tool looked for `admin` in `wa_cert`, which has been empty since
ciris-server took over auth, INSERTed a new ROOT into that dead table, then
verified against the same table and reported success twice. These tests pin
the properties that make that impossible: the right table, never an insert,
exactly one ROOT or refuse, and a hash the server itself accepts.

The helper tests execute `HELPER_SOURCE` - the exact text that ships to the
agent's server - not a re-implementation of it.
"""

import base64
import sqlite3
from unittest.mock import MagicMock

import pytest

from ciris_manager import admin_password_reset as apr

# ciris-server session.rs `verify_password_matches_agent_pbkdf2_vector`.
SERVER_VECTOR_PASSWORD = "correct horse battery staple"
SERVER_VECTOR_HASH = (
    "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh/viXCJThHDAjg+nTGyIJeRecLolkEA86maUs3Hzm+fdw=="
)

CERT_COLUMNS = (
    "wa_id TEXT, name TEXT NOT NULL, role TEXT NOT NULL, pubkey TEXT NOT NULL, "
    "jwt_kid TEXT NOT NULL, password_hash TEXT, scopes TEXT NOT NULL, "
    "auto_minted INTEGER NOT NULL, token_type TEXT NOT NULL, created TEXT NOT NULL, "
    "active INTEGER NOT NULL"
)


def _helper():
    ns = {"__name__": "helper_under_test"}
    exec(compile(apr.HELPER_SOURCE, "HELPER_SOURCE", "exec"), ns)
    return ns["run"]


def _db(tmp_path, roots=1, observers=3, with_legacy_table=True, with_new_table=True):
    path = tmp_path / "ciris_engine.db"
    conn = sqlite3.connect(path)
    if with_new_table:
        conn.execute(f"CREATE TABLE cirislens_wa_cert ({CERT_COLUMNS})")
    if with_legacy_table:
        conn.execute(f"CREATE TABLE wa_cert ({CERT_COLUMNS})")
    if with_new_table:
        for i in range(roots):
            conn.execute(
                "INSERT INTO cirislens_wa_cert VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"wa-root-{i}",
                    "admin",
                    "root",
                    "pk",
                    f"kid-{i}",
                    "old-hash",
                    "[]",
                    0,
                    "standard",
                    "t",
                    1,
                ),
            )
        for i in range(observers):
            conn.execute(
                "INSERT INTO cirislens_wa_cert VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"wa-obs-{i}",
                    f"user{i}",
                    "observer",
                    "pk",
                    f"okid-{i}",
                    f"h{i}",
                    "[]",
                    1,
                    "standard",
                    "t",
                    1,
                ),
            )
    conn.commit()
    conn.close()
    return path


def _dump(path, table="cirislens_wa_cert"):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT * FROM {table} ORDER BY wa_id").fetchall()
    finally:
        conn.close()


class TestHashCompatibility:
    def test_verifies_the_servers_own_test_vector(self):
        """Byte-compatibility with ciris-server, not just self-consistency."""
        assert apr.verify_password(SERVER_VECTOR_PASSWORD, SERVER_VECTOR_HASH)

    def test_wrong_password_rejected(self):
        assert not apr.verify_password("wrong", SERVER_VECTOR_HASH)

    def test_hash_has_the_servers_shape(self):
        h = apr.hash_password("a-password-here")
        assert len(h) == 88
        assert len(base64.b64decode(h)) == 64

    def test_round_trip(self):
        h = apr.hash_password("a-password-here")
        assert apr.verify_password("a-password-here", h)

    def test_salted(self):
        assert apr.hash_password("same") != apr.hash_password("same")

    @pytest.mark.parametrize("bad", ["", None, "not base64!!", base64.b64encode(b"short").decode()])
    def test_malformed_hashes_rejected_like_the_server(self, bad):
        assert not apr.verify_password("anything", bad)

    def test_generated_passwords_are_long_and_unique(self):
        a, b = apr.generate_password(), apr.generate_password()
        assert len(a) >= 32 and a != b


class TestHelper:
    def test_applies_to_the_live_table_only(self, tmp_path):
        path = _db(tmp_path)
        new_hash = apr.hash_password("new-password-123")
        result = _helper()(str(path), new_hash, True)

        assert result["ok"] and result["applied"]
        assert result["wa_id"] == "wa-root-0"
        assert result["previous_hash"] == "old-hash"
        assert apr.verify_password("new-password-123", result["stored_hash"])

    def test_only_the_admin_row_changes(self, tmp_path):
        path = _db(tmp_path, observers=5)
        before = {r[0]: r for r in _dump(path)}
        _helper()(str(path), apr.hash_password("new-password-123"), True)
        after = {r[0]: r for r in _dump(path)}

        changed = [k for k in before if before[k] != after[k]]
        assert changed == ["wa-root-0"]
        assert set(before) == set(after), "rows were added or removed"

    def test_never_writes_the_dead_legacy_table(self, tmp_path):
        """The old tool's bug: a new ROOT inserted where nothing reads it."""
        path = _db(tmp_path)
        _helper()(str(path), apr.hash_password("new-password-123"), True)
        assert _dump(path, "wa_cert") == []

    def test_refuses_rather_than_creating_a_root(self, tmp_path):
        path = _db(tmp_path, roots=0)
        before = _dump(path)
        result = _helper()(str(path), apr.hash_password("x" * 20), True)

        assert not result["ok"]
        assert "never creates" in result["error"]
        assert _dump(path) == before

    def test_refuses_when_root_is_ambiguous(self, tmp_path):
        path = _db(tmp_path, roots=2)
        before = _dump(path)
        result = _helper()(str(path), apr.hash_password("x" * 20), True)

        assert not result["ok"] and "found 2" in result["error"]
        assert _dump(path) == before

    def test_refuses_a_pre_server_database(self, tmp_path):
        path = _db(tmp_path, with_new_table=False)
        result = _helper()(str(path), apr.hash_password("x" * 20), True)
        assert not result["ok"] and "cirislens_wa_cert" in result["error"]

    def test_dry_run_writes_nothing(self, tmp_path):
        path = _db(tmp_path)
        before = _dump(path)
        result = _helper()(str(path), "", False)

        assert result["ok"] and not result["applied"]
        assert result["wa_id"] == "wa-root-0"
        assert _dump(path) == before

    def test_refuses_while_another_writer_holds_the_database(self, tmp_path):
        """A live server would hold it; the write must not race."""
        path = _db(tmp_path)
        holder = sqlite3.connect(path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        try:
            result = _helper()(str(path), apr.hash_password("x" * 20), True)
        finally:
            holder.execute("ROLLBACK")
            holder.close()

        assert not result["ok"] and "sqlite" in result["error"]
        root = next(r for r in _dump(path) if r[0] == "wa-root-0")
        assert root[5] == "old-hash"

    def test_missing_database(self, tmp_path):
        result = _helper()(str(tmp_path / "nope.db"), "", False)
        assert not result["ok"] and "not found" in result["error"]


def _container(status="exited", env=None):
    c = MagicMock()
    c.name = "ciris-datum"
    c.id = "abc123"
    c.status = status
    c.attrs = {
        "Config": {
            "Image": "ghcr.io/cirisai/ciris-agent:2.9.38-stable",
            "Env": env or [],
            "User": "ciris",
        }
    }
    return c


class TestOrchestration:
    @pytest.mark.parametrize("status", ["running", "restarting", "paused"])
    def test_refuses_a_live_container(self, status):
        with pytest.raises(apr.ResetRefused, match="stop it first"):
            apr.check_container(_container(status))

    def test_refuses_postgres_agents(self):
        c = _container(env=["DATABASE_URL=postgresql://u:p@db/x"])
        with pytest.raises(apr.ResetRefused, match="PostgreSQL"):
            apr.check_container(c)

    def test_accepts_a_stopped_sqlite_agent(self):
        apr.check_container(_container(env=["DATABASE_URL=sqlite:////app/data/ciris_engine.db"]))

    def test_plaintext_never_reaches_the_helper(self, monkeypatch):
        seen = {}

        def fake_run(client, container, new_hash, apply, db_path):
            seen["hash"] = new_hash
            return {"ok": True, "applied": True, "wa_id": "wa-1", "stored_hash": new_hash}

        monkeypatch.setattr(apr, "run_helper", fake_run)
        client = MagicMock()
        client.containers.get.return_value = _container()

        result = apr.reset_admin_password(client, "ciris-datum", "plain-password-xyz", True)
        assert "plain-password-xyz" not in seen["hash"]
        assert apr.verify_password("plain-password-xyz", seen["hash"])
        assert result["verified"]

    def test_dry_run_sends_no_hash(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            apr,
            "run_helper",
            lambda c, ct, h, a, d: seen.update(hash=h, apply=a) or {"ok": True, "wa_id": "wa-1"},
        )
        client = MagicMock()
        client.containers.get.return_value = _container()
        apr.reset_admin_password(client, "ciris-datum", None, False)
        assert seen == {"hash": "", "apply": False}

    def test_unverifiable_write_is_reported_as_failure(self, monkeypatch):
        """Never report success on a hash that would not log in."""
        monkeypatch.setattr(
            apr,
            "run_helper",
            lambda *a: {"ok": True, "applied": True, "wa_id": "wa-1", "stored_hash": "garbage"},
        )
        client = MagicMock()
        client.containers.get.return_value = _container()
        with pytest.raises(apr.ResetFailed, match="does not verify"):
            apr.reset_admin_password(client, "ciris-datum", "plain-password-xyz", True)

    def test_helper_failure_surfaces_its_reason(self, monkeypatch):
        monkeypatch.setattr(apr, "run_helper", lambda *a: {"ok": False, "error": "found 0"})
        client = MagicMock()
        client.containers.get.return_value = _container()
        with pytest.raises(apr.ResetFailed, match="found 0"):
            apr.reset_admin_password(client, "ciris-datum", "plain-password-xyz", True)

    def test_parse_finds_result_among_noise(self):
        out = 'warning: blah\nCIRIS_RESET_RESULT {"ok": true, "wa_id": "w"}\n'
        assert apr.parse_helper_output(out) == {"ok": True, "wa_id": "w"}

    def test_parse_without_result_fails_loudly(self):
        with pytest.raises(apr.ResetFailed, match="no result line"):
            apr.parse_helper_output("Traceback: boom")
