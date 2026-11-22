from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_KEY = 80
MAX_VALUE = 360
MAX_SOURCE = 120
MAX_EVIDENCE = 500
DEFAULT_DB = Path(os.environ.get("FIDELITYFLOW_HOME", Path.home() / ".fidelityflow")) / "learning.sqlite3"

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
]

def redact(text: str) -> str:
    value = str(text)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value[:MAX_VALUE]

def project_root(path: str | Path | None = None) -> Path:
    current = Path(path or os.getcwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current

def project_id(path: str | Path | None = None) -> tuple[str, str]:
    root = project_root(path)
    # The path is retained locally for human inspection; the DB key is a one-way digest.
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    return digest, str(root)

class LearningStore:
    """Small local SQLite store. Only confirmed, short project facts are recalled."""

    def __init__(self, db_path: str | Path = DEFAULT_DB, root: str | Path | None = None):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_key, self.root = project_id(root)
        self.db = sqlite3.connect(self.db_path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._init()

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _init(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY,
            project_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source TEXT NOT NULL,
            evidence TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(project_key, fact_key, fact_value, session_id, evidence_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_obs_project_key
            ON observations(project_key, fact_key, created_at);
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY,
            project_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_value TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('candidate','active','retired')),
            first_seen INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(project_key, fact_key, fact_value)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_active
            ON facts(project_key, status, fact_key);
        """)
        row = self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row and int(row["value"]) != SCHEMA_VERSION:
            raise RuntimeError("Unsupported FidelityFlow learning database schema")
        self.db.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    @staticmethod
    def _validate_key(key: str) -> str:
        key = re.sub(r"\s+", "_", str(key).strip().lower())
        if not key or len(key) > MAX_KEY or not re.fullmatch(r"[a-z0-9_.:/-]+", key):
            raise ValueError("fact key must be 1-80 chars: lowercase letters, digits, _ . : / -")
        return key

    def observe(self, key: str, value: str, session_id: str, source: str, evidence: str,
                min_sessions: int = 2) -> dict[str, Any]:
        key = self._validate_key(key)
        value = redact(value).strip()
        session_id = str(session_id).strip()[:100]
        source = redact(source).strip()[:MAX_SOURCE]
        evidence = redact(evidence).strip()[:MAX_EVIDENCE]
        if not value or not session_id or not evidence:
            raise ValueError("value, session_id and evidence are required")
        if min_sessions < 2 or min_sessions > 10:
            raise ValueError("min_sessions must be between 2 and 10")
        now = int(time.time())
        evidence_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        with self.db:
            self.db.execute("""
                INSERT OR IGNORE INTO observations
                (project_key,fact_key,fact_value,session_id,source,evidence,evidence_hash,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (self.project_key, key, value, session_id, source, evidence, evidence_hash, now))
            self.db.execute("""
                INSERT INTO facts(project_key,fact_key,fact_value,status,first_seen,updated_at)
                VALUES(?,?,?,'candidate',?,?)
                ON CONFLICT(project_key,fact_key,fact_value)
                DO UPDATE SET updated_at=excluded.updated_at
            """, (self.project_key, key, value, now, now))
            count = self.db.execute("""
                SELECT COUNT(DISTINCT session_id) AS n FROM observations
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (self.project_key, key, value)).fetchone()["n"]
            alternatives = self.db.execute("""
                SELECT DISTINCT fact_value FROM observations
                WHERE project_key=? AND fact_key=? AND fact_value<>?
            """, (self.project_key, key, value)).fetchall()
            if alternatives:
                # A newly observed contradiction suspends every active value until reviewed.
                self.db.execute("""
                    UPDATE facts SET status='candidate',updated_at=?
                    WHERE project_key=? AND fact_key=? AND status='active'
                """, (now, self.project_key, key))
            elif count >= min_sessions:
                self.db.execute("""
                    UPDATE facts SET status='active',updated_at=?
                    WHERE project_key=? AND fact_key=? AND fact_value=?
                """, (now, self.project_key, key, value))
            self.db.commit()
        return {"key": key, "value": value, "independent_sessions": count,
                "status": self._status(key, value), "required_sessions": min_sessions}

    def _status(self, key: str, value: str) -> str:
        row = self.db.execute("""
            SELECT status FROM facts WHERE project_key=? AND fact_key=? AND fact_value=?
        """, (self.project_key, key, value)).fetchone()
        return row["status"] if row else "missing"

    def recall(self, query: str = "", limit: int = 12) -> list[dict[str, Any]]:
        if not 1 <= limit <= 30:
            raise ValueError("limit must be between 1 and 30")
        rows = self.db.execute("""
            SELECT f.fact_key, f.fact_value, f.updated_at,
                   COUNT(DISTINCT o.session_id) AS sessions
            FROM facts f
            JOIN observations o ON o.project_key=f.project_key
              AND o.fact_key=f.fact_key AND o.fact_value=f.fact_value
            WHERE f.project_key=? AND f.status='active'
            GROUP BY f.id
            ORDER BY f.updated_at DESC, f.fact_key ASC
        """, (self.project_key,)).fetchall()
        terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9_.:/-]+", query) if len(t) > 1]
        results = []
        for row in rows:
            haystack = (row["fact_key"] + " " + row["fact_value"]).lower()
            if terms and not any(term in haystack for term in terms):
                continue
            results.append({"key": row["fact_key"], "value": row["fact_value"],
                            "independent_sessions": row["sessions"]})
            if len(results) >= limit:
                break
        return results

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT f.fact_key,f.fact_value,f.status,
                   COUNT(DISTINCT o.session_id) AS sessions
            FROM facts f JOIN observations o
              ON o.project_key=f.project_key AND o.fact_key=f.fact_key
             AND o.fact_value=f.fact_value
            WHERE f.project_key=? AND f.status='candidate'
            GROUP BY f.id ORDER BY f.updated_at DESC
        """, (self.project_key,)).fetchall()
        return [dict(r) for r in rows]

    def confirm(self, key: str, value: str) -> None:
        key = self._validate_key(key)
        with self.db:
            count = self.db.execute("""
                SELECT COUNT(DISTINCT session_id) AS n FROM observations
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (self.project_key, key, value)).fetchone()["n"]
            if count < 1:
                raise ValueError("No matching evidence exists")
            self.db.execute("""
                UPDATE facts SET status='retired',updated_at=?
                WHERE project_key=? AND fact_key=? AND status='active' AND fact_value<>?
            """, (int(time.time()), self.project_key, key, value))
            self.db.execute("""
                UPDATE facts SET status='active',updated_at=?
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (int(time.time()), self.project_key, key, value))
            self.db.commit()

    def retire(self, key: str, value: str | None = None) -> int:
        key = self._validate_key(key)
        with self.db:
            if value is None:
                cur = self.db.execute("""
                    UPDATE facts SET status='retired',updated_at=?
                    WHERE project_key=? AND fact_key=? AND status='active'
                """, (int(time.time()), self.project_key, key))
            else:
                cur = self.db.execute("""
                    UPDATE facts SET status='retired',updated_at=?
                    WHERE project_key=? AND fact_key=? AND fact_value=?
                """, (int(time.time()), self.project_key, key, value))
            self.db.commit()
            return cur.rowcount

    def forget(self, key: str | None = None) -> int:
        with self.db:
            if key is None:
                count = self.db.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE project_key=?", (self.project_key,)
                ).fetchone()["n"]
                self.db.execute("DELETE FROM observations WHERE project_key=?", (self.project_key,))
                self.db.execute("DELETE FROM facts WHERE project_key=?", (self.project_key,))
            else:
                key = self._validate_key(key)
                count = self.db.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE project_key=? AND fact_key=?",
                    (self.project_key, key)
                ).fetchone()["n"]
                self.db.execute(
                    "DELETE FROM observations WHERE project_key=? AND fact_key=?",
                    (self.project_key, key)
                )
                self.db.execute(
                    "DELETE FROM facts WHERE project_key=? AND fact_key=?",
                    (self.project_key, key)
                )
            self.db.commit()
            return count

    def stats(self) -> dict[str, int]:
        row = self.db.execute("""
            SELECT
              (SELECT COUNT(*) FROM facts WHERE project_key=? AND status='active') AS active,
              (SELECT COUNT(*) FROM facts WHERE project_key=? AND status='candidate') AS candidates,
              (SELECT COUNT(*) FROM observations WHERE project_key=?) AS observations
        """, (self.project_key, self.project_key, self.project_key)).fetchone()
        return dict(row)
