"""SQLite storage: one file, WAL mode, durable writes, explicit transactions, versioned migrations."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # v1: kernel
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

    CREATE TABLE audit (
        seq       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts        TEXT NOT NULL,
        actor     TEXT NOT NULL,
        event     TEXT NOT NULL,
        task_id   TEXT,
        payload   TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        hash      TEXT NOT NULL UNIQUE
    );
    CREATE INDEX audit_task ON audit(task_id, seq);
    CREATE TRIGGER audit_append_only_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    CREATE TRIGGER audit_append_only_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

    CREATE TABLE tasks (
        id          TEXT PRIMARY KEY,
        request     TEXT NOT NULL,
        goal        TEXT NOT NULL,
        state       TEXT NOT NULL,
        priority    INTEGER NOT NULL DEFAULT 50,
        version     INTEGER NOT NULL DEFAULT 0,
        context     TEXT NOT NULL DEFAULT '{}',
        control     TEXT,
        next_action TEXT,
        error       TEXT,
        result      TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX tasks_state ON tasks(state, priority);

    CREATE TABLE steps (
        id           TEXT PRIMARY KEY,
        task_id      TEXT NOT NULL REFERENCES tasks(id),
        idx          INTEGER NOT NULL,
        description  TEXT NOT NULL,
        tool         TEXT NOT NULL,
        action       TEXT NOT NULL,
        args         TEXT NOT NULL,
        depends_on   TEXT NOT NULL DEFAULT '[]',
        state        TEXT NOT NULL,
        attempts     INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        not_before   REAL,
        op_id        TEXT UNIQUE,
        result       TEXT,
        error        TEXT,
        started_at   TEXT,
        finished_at  TEXT,
        UNIQUE (task_id, idx)
    );

    CREATE TABLE checkpoints (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        step_id TEXT,
        ts      TEXT NOT NULL,
        data    TEXT NOT NULL
    );
    CREATE INDEX checkpoints_task ON checkpoints(task_id, id);

    CREATE TABLE approvals (
        id         TEXT PRIMARY KEY,
        task_id    TEXT,
        step_id    TEXT,
        tool       TEXT NOT NULL,
        action     TEXT NOT NULL,
        resource   TEXT,
        args_hash  TEXT NOT NULL,
        tier       INTEGER NOT NULL,
        reason     TEXT NOT NULL,
        summary    TEXT NOT NULL,
        state      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        decided_at TEXT,
        decided_by TEXT
    );
    CREATE INDEX approvals_task ON approvals(task_id, state);
    """,
    # v2: model layer
    """
    CREATE TABLE egress_grants (
        id         TEXT PRIMARY KEY,
        category   TEXT NOT NULL,
        provider   TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        expires_at TEXT,
        revoked_at TEXT
    );
    CREATE INDEX egress_grants_lookup ON egress_grants(category, provider);

    CREATE TABLE model_usage (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,
        provider      TEXT NOT NULL,
        model         TEXT NOT NULL,
        task_id       TEXT,
        input_tokens  INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cost_usd      REAL NOT NULL
    );
    CREATE INDEX model_usage_ts ON model_usage(ts);
    """,
    # v3: memory — original records, derived memories, full-text indexes, deletion tombstones
    """
    CREATE TABLE records (
        id         TEXT PRIMARY KEY,
        session    TEXT NOT NULL,
        kind       TEXT NOT NULL,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX records_session ON records(session, created_at);
    CREATE VIRTUAL TABLE records_fts USING fts5(id UNINDEXED, content, tokenize = 'porter unicode61');

    CREATE TABLE memories (
        id            TEXT PRIMARY KEY,
        text          TEXT NOT NULL,
        kind          TEXT NOT NULL,
        origin        TEXT NOT NULL,
        confidence    REAL NOT NULL,
        source_record TEXT,
        created_at    TEXT NOT NULL,
        verified_at   TEXT,
        important     INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX memories_source ON memories(source_record);
    CREATE VIRTUAL TABLE memories_fts USING fts5(id UNINDEXED, text, tokenize = 'porter unicode61');

    CREATE TABLE tombstones (
        hash       TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    );
    """,
    # v4: task leases — which process is running a task, until when (nullable; old rows unaffected)
    """
    ALTER TABLE tasks ADD COLUMN lease_owner TEXT;
    ALTER TABLE tasks ADD COLUMN lease_until REAL;
    """,
    # v5: iPhone companion — paired devices (passkeys), their sessions, one-time pairing codes, push subscriptions
    """
    CREATE TABLE devices (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        credential_id TEXT NOT NULL UNIQUE,
        public_key    TEXT NOT NULL,
        sign_count    INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        last_seen     TEXT,
        revoked_at    TEXT
    );
    CREATE TABLE device_sessions (
        token_hash TEXT PRIMARY KEY,
        device_id  TEXT NOT NULL REFERENCES devices(id),
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        last_seen  REAL NOT NULL
    );
    CREATE TABLE pairings (
        code_hash  TEXT PRIMARY KEY,
        challenge  TEXT,
        user_id    TEXT,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        used_at    REAL
    );
    CREATE TABLE push_subscriptions (
        id         TEXT PRIMARY KEY,
        device_id  TEXT NOT NULL REFERENCES devices(id),
        endpoint   TEXT NOT NULL UNIQUE,
        p256dh     TEXT NOT NULL,
        auth       TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # v6: Touch ID passkeys for the Mac dashboard live beside phone passkeys
    """
    ALTER TABLE devices ADD COLUMN kind TEXT NOT NULL DEFAULT 'phone' CHECK (kind IN ('phone', 'mac'));
    """,
    # v7: improvement proposals (propose-only: a decision records your answer and changes nothing by itself)
    """
    CREATE TABLE proposals (
        id          TEXT PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE,
        kind        TEXT NOT NULL,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'approved', 'rejected', 'done')),
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        decided_at  TEXT,
        decided_by  TEXT
    );
    """,
    # v8: project ideas for the owner (evidence is stored as references to records/memories, never copies)
    """
    CREATE TABLE project_ideas (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'active', 'dismissed', 'done')),
        source      TEXT NOT NULL DEFAULT 'local',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        decided_at  TEXT
    );
    """,
    # v9: continuous intelligence — outcomes, lessons with evidence, knowledge links, experiments, feedback, autonomy.
    # Everything here is derived from the audit log or stated by the owner; text is short and never a transcript.
    """
    CREATE TABLE outcomes (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL CHECK (kind IN ('task', 'reply')),
        ref         TEXT NOT NULL,
        model       TEXT,
        verdict     TEXT NOT NULL CHECK (verdict IN ('verified', 'failed', 'unverified')),
        evidence    TEXT NOT NULL,
        seconds     REAL,
        errors      INTEGER NOT NULL DEFAULT 0,
        recovered   INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        UNIQUE (kind, ref)
    );
    CREATE INDEX outcomes_created ON outcomes(created_at);
    CREATE TABLE lessons (
        id          TEXT PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE,
        subject     TEXT NOT NULL,
        polarity    INTEGER NOT NULL DEFAULT 0,
        statement   TEXT NOT NULL,
        kind        TEXT NOT NULL CHECK (kind IN ('confirmed', 'user', 'inferred', 'hypothesis', 'outdated')),
        evidence    TEXT NOT NULL,
        confidence  REAL NOT NULL,
        seen        INTEGER NOT NULL DEFAULT 1,
        applied     INTEGER NOT NULL DEFAULT 0,
        state       TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'rejected')),
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL
    );
    CREATE TABLE links (
        src         TEXT NOT NULL,
        dst         TEXT NOT NULL,
        rel         TEXT NOT NULL,
        source      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (src, dst, rel)
    );
    CREATE INDEX links_dst ON links(dst);
    CREATE TABLE experiments (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        objective   TEXT NOT NULL,
        hypothesis  TEXT NOT NULL,
        baseline    TEXT NOT NULL,
        criteria    TEXT NOT NULL,
        environment TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'planned' CHECK (state IN ('planned', 'running', 'done', 'failed', 'cancelled')),
        results     TEXT,
        recommendation TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE feedback (
        id          TEXT PRIMARY KEY,
        target      TEXT NOT NULL CHECK (target IN ('reply', 'task')),
        ref         TEXT NOT NULL,
        model       TEXT,
        mode        TEXT,
        rating      INTEGER NOT NULL CHECK (rating IN (-1, 1)),
        reason      TEXT,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE autonomy (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        updated_by  TEXT NOT NULL
    );
    """,
    # v10: Mission Control — planning jobs survive a restart (a plan waiting for you, or being planned, isn't lost)
    """
    CREATE TABLE plan_jobs (
        id          TEXT PRIMARY KEY,
        request     TEXT NOT NULL,
        state       TEXT NOT NULL CHECK (state IN ('planning', 'waiting_approval', 'ready', 'submitted')),
        data        TEXT NOT NULL,          -- the job as the dashboard shows it (JSON), plus the plan itself
        replan_of   TEXT,                   -- the failed mission this is a second attempt at
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE INDEX plan_jobs_replan ON plan_jobs(replan_of);
    """,
]


class SchemaTooNew(RuntimeError):
    pass


class Database:
    """Thread-safe wrapper around a single SQLite connection.

    ``tx()`` opens an IMMEDIATE transaction; nested ``tx()`` calls become savepoints,
    so an inner failure rolls back only the inner work.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        # secure_delete: deleted rows are overwritten with zeros, so forgotten text doesn't linger on disk.
        for pragma in ("journal_mode=WAL", "foreign_keys=ON", "synchronous=FULL", "busy_timeout=5000",
                       "secure_delete=ON"):
            self._conn.execute(f"PRAGMA {pragma}")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current > len(MIGRATIONS):
                raise SchemaTooNew(f"database schema v{current} is newer than this code (v{len(MIGRATIONS)})")
            for version in range(current + 1, len(MIGRATIONS) + 1):
                try:
                    self._conn.executescript(
                        f"BEGIN IMMEDIATE;\n{MIGRATIONS[version - 1]}\nPRAGMA user_version = {version};\nCOMMIT;"
                    )
                except Exception:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise

    def checkpoint(self) -> None:
        """Fold the write-ahead log into the main file and truncate it (removes old page copies)."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @property
    def schema_version(self) -> int:
        return self.one("PRAGMA user_version")[0]

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            depth = self._depth
            self._conn.execute("BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT sp{depth}")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if depth == 0:
                    self._conn.execute("ROLLBACK")
                else:
                    self._conn.execute(f"ROLLBACK TO sp{depth}")
                    self._conn.execute(f"RELEASE sp{depth}")
                raise
            self._depth -= 1
            self._conn.execute("COMMIT" if depth == 0 else f"RELEASE sp{depth}")

    def query(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
