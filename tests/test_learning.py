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

if __name__ == "__main__":
    unittest.main()
