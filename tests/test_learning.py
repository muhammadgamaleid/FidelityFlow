import tempfile
import unittest
import json
import os
import subprocess
import sys
from pathlib import Path
from fidelityflow_learning.store import LearningStore

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.db = Path(self.tmp.name) / "memory.sqlite3"

    def store(self):
        return LearningStore(self.db, self.root)

    def test_fact_requires_two_independent_sessions(self):
        with self.store() as s:
            first=s.observe("test.command","pytest -q","session-a","bash","Ran pytest -q; exit 0")
            self.assertEqual(first["status"],"candidate")
            self.assertEqual(s.recall(),[])
            second=s.observe("test.command","pytest -q","session-b","bash","Ran pytest -q; exit 0 on a separate day")
            self.assertEqual(second["status"],"active")
            self.assertEqual(s.recall()[0]["value"],"pytest -q")

    def test_same_session_cannot_promote(self):
        with self.store() as s:
            s.observe("test.command","pytest -q","same","bash","first evidence")
            result=s.observe("test.command","pytest -q","same","bash","second evidence")
            self.assertEqual(result["independent_sessions"],1)
            self.assertEqual(result["status"],"candidate")

    def test_conflicting_values_do_not_auto_promote(self):
        with self.store() as s:
            s.observe("test.command","pytest -q","a","bash","evidence a")
            s.observe("test.command","unittest","b","bash","evidence b")
            s.observe("test.command","pytest -q","c","bash","evidence c")
            self.assertEqual(s.recall(),[])
            self.assertEqual(len(s.list_candidates()),2)

    def test_contradiction_suspends_previously_active_fact(self):
        with self.store() as s:
            s.observe("test.command","pytest -q","a","bash","first valid run")
            s.observe("test.command","pytest -q","b","bash","second valid run")
            self.assertEqual(s.recall()[0]["value"],"pytest -q")
            s.observe("test.command","python -m unittest","c","bash","new command observed")
            self.assertEqual(s.recall(),[])

    def test_manual_confirmation_retires_old_active_value(self):
        with self.store() as s:
            s.observe("test.command","pytest -q","a","bash","evidence a")
            s.observe("test.command","pytest -q","b","bash","evidence b")
            s.observe("test.command","python -m unittest","c","bash","evidence c")
            s.confirm("test.command","python -m unittest")
            self.assertEqual(s.recall()[0]["value"],"python -m unittest")

    def test_project_isolation(self):
        other=self.root.parent/"other"; other.mkdir()
        with LearningStore(self.db,self.root) as a:
            a.observe("build.command","make","a","bash","build succeeded")
            a.observe("build.command","make","b","bash","build succeeded independently")
        with LearningStore(self.db,other) as b:
            self.assertEqual(b.recall(),[])

    def test_secret_redaction(self):
        with self.store() as s:
            s.observe("config.note","api_key=abc123456789secret","a","manual","Observed API key=ghp_123456789012345678901234")
            s.observe("config.note","api_key=abc123456789secret","b","manual","Observed API key=ghp_223456789012345678901234")
            recalled=s.recall()[0]["value"]
            self.assertIn("[REDACTED]",recalled)
            self.assertNotIn("abc123",recalled)

    def test_retire_and_forget(self):
        with self.store() as s:
            s.observe("test.command","pytest","a","bash","first")
            s.observe("test.command","pytest","b","bash","second")
            self.assertEqual(s.retire("test.command"),1)
            self.assertEqual(s.recall(),[])
            s.forget()
            self.assertEqual(s.stats()["observations"],0)


    def test_post_tool_use_hook_records_only_allowlisted_successful_bash(self):
        hook = Path(__file__).resolve().parents[1] / "hooks" / "post_tool_use.py"
        env = os.environ.copy()
        env["FIDELITYFLOW_HOME"] = str(Path(self.tmp.name) / "home")
        event = {"hook_event_name":"PostToolUse", "tool_name":"Bash",
                 "session_id":"session-1", "cwd":str(self.root),
                 "tool_input":{"command":"pytest -q"},
                 "tool_response":{"stdout":"9 passed", "stderr":"", "interrupted":False}}
        result = subprocess.run([sys.executable, str(hook)], input=json.dumps(event),
                                text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        with LearningStore(Path(env["FIDELITYFLOW_HOME"])/"learning.sqlite3", self.root) as store:
            self.assertEqual(store.stats()["candidates"], 1)
            self.assertEqual(store.recall(), [])

    def test_session_start_hook_injects_only_confirmed_facts(self):
        hook = Path(__file__).resolve().parents[1] / "hooks" / "session_start.py"
        env = os.environ.copy()
        env["FIDELITYFLOW_HOME"] = str(Path(self.tmp.name) / "home")
        db = Path(env["FIDELITYFLOW_HOME"])/"learning.sqlite3"
        with LearningStore(db, self.root) as store:
            store.observe("test.command", "pytest -q", "s1", "bash", "first success")
            store.observe("test.command", "pytest -q", "s2", "bash", "second success")
            store.observe("build.command", "make build", "s1", "bash", "only one observation")
        event = {"hook_event_name":"SessionStart", "session_id":"new-session", "cwd":str(self.root)}
        result = subprocess.run([sys.executable, str(hook)], input=json.dumps(event),
                                text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pytest -q", context)
        self.assertNotIn("make build", context)

    def test_rejects_invalid_key_and_weak_threshold(self):
        with self.store() as s:
            with self.assertRaises(ValueError):
                s.observe("bad key!","x","a","manual","e")
            with self.assertRaises(ValueError):
                s.observe("valid.key","x","a","manual","e",min_sessions=1)


    def test_manual_resolution_survives_a_later_matching_observation(self):
        with self.store() as s:
            s.observe("test.command", "pytest -q", "s1", "manual", "first evidence")
            s.observe("test.command", "pytest -q", "s2", "manual", "second evidence")
            s.observe("test.command", "python -m unittest", "s3", "manual", "conflicting evidence")
            s.confirm("test.command", "pytest -q")
            self.assertEqual(s.recall()[0]["value"], "pytest -q")
            result = s.observe("test.command", "pytest -q", "s4", "manual", "matching after decision")
            self.assertEqual(result["status"], "active")
            self.assertEqual(s.recall()[0]["value"], "pytest -q")

    def test_new_conflict_after_manual_resolution_reopens_review(self):
        with self.store() as s:
            s.observe("test.command", "pytest -q", "s1", "manual", "first evidence")
            s.observe("test.command", "pytest -q", "s2", "manual", "second evidence")
            s.observe("test.command", "python -m unittest", "s3", "manual", "conflicting evidence")
            s.confirm("test.command", "pytest -q")
            result = s.observe("test.command", "python -m unittest", "s4", "manual", "new conflict")
            self.assertEqual(result["status"], "candidate")
            self.assertEqual(s.recall(), [])


    def test_new_conflict_after_resolution_returns_retired_value_to_candidates(self):
        with self.store() as s:
            s.observe("test.command", "pytest -q", "s1", "manual", "first")
            s.observe("test.command", "pytest -q", "s2", "manual", "second")
            s.observe("test.command", "python -m unittest", "s3", "manual", "conflict")
            s.confirm("test.command", "pytest -q")
            result = s.observe("test.command", "python -m unittest", "s4", "manual", "new conflict")
            self.assertEqual(result["status"], "candidate")
            self.assertEqual(len(s.list_candidates()), 2)
            self.assertEqual(s.recall(), [])

    def test_retired_fact_is_not_automatically_reactivated(self):
        with self.store() as s:
            s.observe("build.command", "make build", "s1", "manual", "first")
            s.observe("build.command", "make build", "s2", "manual", "second")
            self.assertEqual(s.retire("build.command"), 1)
            result = s.observe("build.command", "make build", "s3", "manual", "repeated after retirement")
            self.assertEqual(result["status"], "retired")
            self.assertEqual(s.recall(), [])

    def test_min_sessions_threshold_is_fixed_by_first_observation(self):
        with self.store() as s:
            first = s.observe("build.command", "make build", "s1", "manual", "first", min_sessions=3)
            second = s.observe("build.command", "make build", "s2", "manual", "second", min_sessions=2)
            self.assertEqual(first["required_sessions"], 3)
            self.assertEqual(second["required_sessions"], 3)
            self.assertEqual(second["status"], "candidate")
            third = s.observe("build.command", "make build", "s3", "manual", "third")
            self.assertEqual(third["status"], "active")
            self.assertEqual(third["required_sessions"], 3)


    def test_bare_secret_flag_arguments_are_redacted(self):
        with self.store() as s:
            first = s.observe(
                "command.note", "pytest --password super-secret-value",
                "s1", "manual", "safe evidence",
            )
            self.assertEqual(first["status"], "candidate")
            row = s.db.execute(
                "SELECT fact_value FROM facts WHERE project_key=? AND fact_key=?",
                (s.project_key, "command.note"),
            ).fetchone()
            self.assertEqual(row["fact_value"], "pytest --password [REDACTED]")

    def test_evidence_can_use_its_documented_500_character_limit(self):
        with self.store() as s:
            result = s.observe(
                "note.evidence", "short", "session-one", "manual", "x" * 450
            )
            self.assertEqual(result["status"], "candidate")
            stored = s.db.execute(
                "SELECT evidence FROM observations WHERE project_key=?",
                (s.project_key,),
            ).fetchone()["evidence"]
            self.assertEqual(len(stored), 450)

    def test_v1_database_is_migrated_to_v2(self):
        import sqlite3
        legacy = Path(self.tmp.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata(key,value) VALUES('schema_version','1');
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY, project_key TEXT NOT NULL, fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL, session_id TEXT NOT NULL, source TEXT NOT NULL,
                evidence TEXT NOT NULL, evidence_hash TEXT NOT NULL, created_at INTEGER NOT NULL,
                UNIQUE(project_key, fact_key, fact_value, session_id, evidence_hash)
            );
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY, project_key TEXT NOT NULL, fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('candidate','active','retired')),
                first_seen INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                UNIQUE(project_key, fact_key, fact_value)
            );
        """)
        connection.commit()
        connection.close()
        with LearningStore(legacy, self.root) as store:
            self.assertEqual(store.db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()["value"], "2")
            columns = {row["name"] for row in store.db.execute("PRAGMA table_info(facts)")}
            self.assertIn("required_sessions", columns)
            self.assertEqual(store.stats()["observations"], 0)

if __name__ == "__main__":
    unittest.main()
