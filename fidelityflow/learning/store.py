from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
MAX_KEY = 80
MAX_VALUE = 360
MAX_SOURCE = 120
MAX_EVIDENCE = 500
DEFAULT_DB = Path(os.environ.get("FIDELITYFLOW_HOME", Path.home() / ".fidelityflow")) / "learning.sqlite3"

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|passwd|secret|client[-_]?secret|database[-_]?url|connection[-_]?string)\s+)(?:'[^']*'|\"[^\"]*\"|\S+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|client[_-]?secret|database[_-]?url|connection[_-]?string)\b\s*[:=]\s*['\"]?[^\s,;'\"]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s:]+(?::[^/@\s]*)?@"), r"\1[REDACTED]@"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED]"),
)


def redact(text: str, max_length: int = MAX_VALUE) -> str:
    """Best-effort masking with a caller-specific length limit."""
    value = str(text)
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value[:max_length]


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
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    return digest, str(root)


class LearningStore:
    """Small local SQLite store with explicit, auditable contradiction resolution."""

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
            required_sessions INTEGER NOT NULL DEFAULT 2 CHECK(required_sessions BETWEEN 2 AND 10),
            UNIQUE(project_key, fact_key, fact_value)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_active
            ON facts(project_key, status, fact_key);
        CREATE TABLE IF NOT EXISTS resolutions (
            project_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            selected_value TEXT NOT NULL,
            resolved_observation_id INTEGER NOT NULL,
            resolved_at INTEGER NOT NULL,
            PRIMARY KEY(project_key, fact_key)
        );
        """)

        row = self.db.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
        else:
            try:
                version = int(row["value"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Invalid FidelityFlow learning database schema version") from exc
            if version == 1:
                columns = {
                    item["name"]
                    for item in self.db.execute("PRAGMA table_info(facts)").fetchall()
                }
                if "required_sessions" not in columns:
                    self.db.execute(
                        "ALTER TABLE facts ADD COLUMN required_sessions INTEGER NOT NULL DEFAULT 2"
                    )
                self.db.execute(
                    "UPDATE metadata SET value=? WHERE key='schema_version'",
                    (str(SCHEMA_VERSION),),
                )
            elif version != SCHEMA_VERSION:
                raise RuntimeError("Unsupported FidelityFlow learning database schema")
        self.db.commit()

    @staticmethod
    def _validate_key(key: str) -> str:
        key = re.sub(r"\s+", "_", str(key).strip().lower())
        if not key or len(key) > MAX_KEY or not re.fullmatch(r"[a-z0-9_.:/-]+", key):
            raise ValueError("fact key must be 1-80 chars: lowercase letters, digits, _ . : / -")
        return key

    def observe(
        self,
        key: str,
        value: str,
        session_id: str,
        source: str,
        evidence: str,
        min_sessions: int = 2,
    ) -> dict[str, Any]:
        key = self._validate_key(key)
        value = redact(value, MAX_VALUE).strip()
        session_id = str(session_id).strip()[:100]
        source = redact(source, MAX_SOURCE).strip()
        evidence = redact(evidence, MAX_EVIDENCE).strip()
        if not value or not session_id or not evidence:
            raise ValueError("value, session_id and evidence are required")
        if not 2 <= min_sessions <= 10:
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
                INSERT INTO facts
                    (project_key,fact_key,fact_value,status,first_seen,updated_at,required_sessions)
                VALUES(?,?,?,'candidate',?,?,?)
                ON CONFLICT(project_key,fact_key,fact_value)
                DO UPDATE SET updated_at=excluded.updated_at
            """, (self.project_key, key, value, now, now, min_sessions))

            fact = self.db.execute("""
                SELECT required_sessions FROM facts
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (self.project_key, key, value)).fetchone()
            required_sessions = int(fact["required_sessions"])

            count = self.db.execute("""
                SELECT COUNT(DISTINCT session_id) AS n FROM observations
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (self.project_key, key, value)).fetchone()["n"]

            resolution = self.db.execute("""
                SELECT selected_value,resolved_observation_id FROM resolutions
                WHERE project_key=? AND fact_key=?
            """, (self.project_key, key)).fetchone()

            if resolution is not None:
                # Only evidence added after the human decision can reopen it.
                newer_conflict = self.db.execute("""
                    SELECT 1 FROM observations
                    WHERE project_key=? AND fact_key=? AND fact_value<>?
                      AND id>?
                    LIMIT 1
                """, (
                    self.project_key, key, resolution["selected_value"],
                    resolution["resolved_observation_id"],
                )).fetchone()
                if newer_conflict:
                    self.db.execute("""
                        DELETE FROM resolutions WHERE project_key=? AND fact_key=?
                    """, (self.project_key, key))
                    self.db.execute("""
                        UPDATE facts SET status='candidate',updated_at=?
                        WHERE project_key=? AND fact_key=? AND status='active'
                    """, (now, self.project_key, key))
                    self.db.execute("""
                        UPDATE facts SET status='candidate',updated_at=?
                        WHERE project_key=? AND fact_key=? AND fact_value=? AND status='retired'
                    """, (now, self.project_key, key, value))
                else:
                    # A matching observation must not undo a previous manual resolution.
                    self.db.execute("""
                        UPDATE facts SET status='active',updated_at=?
                        WHERE project_key=? AND fact_key=? AND fact_value=?
                    """, (now, self.project_key, key, resolution["selected_value"]))
            else:
                alternatives = self.db.execute("""
                    SELECT 1 FROM observations
                    WHERE project_key=? AND fact_key=? AND fact_value<>?
                    LIMIT 1
                """, (self.project_key, key, value)).fetchone()
                if alternatives:
                    self.db.execute("""
                        UPDATE facts SET status='candidate',updated_at=?
                        WHERE project_key=? AND fact_key=? AND status='active'
                    """, (now, self.project_key, key))
                elif count >= required_sessions:
                    self.db.execute("""
                        UPDATE facts SET status='active',updated_at=?
                        WHERE project_key=? AND fact_key=? AND fact_value=?
                          AND status='candidate'
                    """, (now, self.project_key, key, value))
            self.db.commit()

        return {
            "key": key,
            "value": value,
            "independent_sessions": count,
            "status": self._status(key, value),
            "required_sessions": required_sessions,
        }

    def _status(self, key: str, value: str) -> str:
        row = self.db.execute("""
            SELECT status FROM facts
            WHERE project_key=? AND fact_key=? AND fact_value=?
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
            results.append({
                "key": row["fact_key"],
                "value": row["fact_value"],
                "independent_sessions": row["sessions"],
            })
            if len(results) >= limit:
                break
        return results

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = self.db.execute("""
            SELECT f.fact_key,f.fact_value,f.status,f.required_sessions,
                   COUNT(DISTINCT o.session_id) AS sessions
            FROM facts f JOIN observations o
              ON o.project_key=f.project_key AND o.fact_key=f.fact_key
             AND o.fact_value=f.fact_value
            WHERE f.project_key=? AND f.status='candidate'
            GROUP BY f.id ORDER BY f.updated_at DESC
        """, (self.project_key,)).fetchall()
        return [dict(row) for row in rows]

    def confirm(self, key: str, value: str) -> None:
        key = self._validate_key(key)
        value = redact(value, MAX_VALUE).strip()
        with self.db:
            matching_evidence = self.db.execute("""
                SELECT 1 FROM observations
                WHERE project_key=? AND fact_key=? AND fact_value=?
                LIMIT 1
            """, (self.project_key, key, value)).fetchone()
            if matching_evidence is None:
                raise ValueError("No matching evidence exists")
            # The resolution cutoff must include every observation for this key,
            # including competing values reviewed by the human decision.
            latest = self.db.execute("""
                SELECT MAX(id) AS observation_id FROM observations
                WHERE project_key=? AND fact_key=?
            """, (self.project_key, key)).fetchone()
            if latest is None or latest["observation_id"] is None:
                raise ValueError("No observations exist for this fact key")
            now = int(time.time())
            self.db.execute("""
                UPDATE facts SET status='retired',updated_at=?
                WHERE project_key=? AND fact_key=? AND fact_value<>?
                  AND status<>'retired'
            """, (now, self.project_key, key, value))
            cur = self.db.execute("""
                UPDATE facts SET status='active',updated_at=?
                WHERE project_key=? AND fact_key=? AND fact_value=?
            """, (now, self.project_key, key, value))
            if cur.rowcount != 1:
                raise ValueError("Matching fact record does not exist")
            self.db.execute("""
                INSERT INTO resolutions
                    (project_key,fact_key,selected_value,resolved_observation_id,resolved_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(project_key,fact_key) DO UPDATE SET
                    selected_value=excluded.selected_value,
                    resolved_observation_id=excluded.resolved_observation_id,
                    resolved_at=excluded.resolved_at
            """, (
                self.project_key, key, value, latest["observation_id"], now,
            ))
            self.db.commit()

    def retire(self, key: str, value: str | None = None) -> int:
        key = self._validate_key(key)
        with self.db:
            if value is None:
                cur = self.db.execute("""
                    UPDATE facts SET status='retired',updated_at=?
                    WHERE project_key=? AND fact_key=? AND status='active'
                """, (int(time.time()), self.project_key, key))
                self.db.execute(
                    "DELETE FROM resolutions WHERE project_key=? AND fact_key=?",
                    (self.project_key, key),
                )
            else:
                value = redact(value, MAX_VALUE).strip()
                cur = self.db.execute("""
                    UPDATE facts SET status='retired',updated_at=?
                    WHERE project_key=? AND fact_key=? AND fact_value=?
                """, (int(time.time()), self.project_key, key, value))
                self.db.execute("""
                    DELETE FROM resolutions
                    WHERE project_key=? AND fact_key=? AND selected_value=?
                """, (self.project_key, key, value))
            self.db.commit()
            return cur.rowcount

    def forget(self, key: str | None = None) -> int:
        with self.db:
            if key is None:
                count = self.db.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE project_key=?",
                    (self.project_key,),
                ).fetchone()["n"]
                self.db.execute(
                    "DELETE FROM observations WHERE project_key=?", (self.project_key,)
                )
                self.db.execute(
                    "DELETE FROM facts WHERE project_key=?", (self.project_key,)
                )
                self.db.execute(
                    "DELETE FROM resolutions WHERE project_key=?", (self.project_key,)
                )
            else:
                key = self._validate_key(key)
                count = self.db.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE project_key=? AND fact_key=?",
                    (self.project_key, key),
                ).fetchone()["n"]
                self.db.execute("""
                    DELETE FROM observations WHERE project_key=? AND fact_key=?
                """, (self.project_key, key))
                self.db.execute("""
                    DELETE FROM facts WHERE project_key=? AND fact_key=?
                """, (self.project_key, key))
                self.db.execute("""
                    DELETE FROM resolutions WHERE project_key=? AND fact_key=?
                """, (self.project_key, key))
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
