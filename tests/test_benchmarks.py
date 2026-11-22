from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "read_claude_usage.py"


def write_transcript(path: Path, messages: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in messages) + "\n",
        encoding="utf-8",
    )


class UsageComparisonTests(unittest.TestCase):
    def test_compares_context_and_output_tokens_without_estimating(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            baseline = folder / "baseline.jsonl"
            candidate = folder / "candidate.jsonl"
            write_transcript(baseline, [
                {"uuid": "a", "message": {"id": "a", "model": "claude-test", "usage": {
                    "input_tokens": 1000, "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 300, "output_tokens": 200,
                }}},
            ])
            write_transcript(candidate, [
                {"uuid": "b", "message": {"id": "b", "model": "claude-test", "usage": {
                    "input_tokens": 500, "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 150, "output_tokens": 180,
                }}},
            ])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(baseline), "--compare", str(candidate), "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["baseline"]["context_input_tokens"], 1400)
            self.assertEqual(report["candidate"]["context_input_tokens"], 700)
            self.assertEqual(
                report["comparison"]["context_input_tokens"]["reduction_percent"],
                50.0,
            )
            self.assertEqual(
                report["comparison"]["metrics"]["output_tokens"]["difference_candidate_minus_baseline"],
                -20,
            )
            self.assertIn("cannot establish answer quality", report["comparison"]["quality_assessment"])

    def test_manual_quality_scores_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            baseline = folder / "baseline.jsonl"
            candidate = folder / "candidate.jsonl"
            write_transcript(baseline, [{"uuid": "a", "message": {"id": "a", "usage": {"input_tokens": 100}}}])
            write_transcript(candidate, [{"uuid": "b", "message": {"id": "b", "usage": {"input_tokens": 80}}}])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(baseline), "--compare", str(candidate),
                 "--quality-baseline", "92", "--quality-candidate", "91", "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["manual_quality_scores"]["difference_candidate_minus_baseline"], -1)

    def test_user_supplied_pricing_is_used_and_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            baseline = folder / "baseline.jsonl"
            candidate = folder / "candidate.jsonl"
            pricing = folder / "pricing.json"
            write_transcript(baseline, [{"uuid": "a", "message": {"id": "a", "usage": {
                "input_tokens": 1_000_000, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0, "output_tokens": 0,
            }}}])
            write_transcript(candidate, [{"uuid": "b", "message": {"id": "b", "usage": {
                "input_tokens": 500_000, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0, "output_tokens": 0,
            }}}])
            pricing.write_text(json.dumps({
                "currency": "USD",
                "per_million_tokens": {
                    "input_tokens": 2, "cache_creation_input_tokens": 2.5,
                    "cache_read_input_tokens": 0.2, "output_tokens": 10,
                },
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(baseline), "--compare", str(candidate),
                 "--pricing", str(pricing), "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["api_cost_estimate"]["baseline"], 2.0)

            pricing.write_text('{"currency":"USD","per_million_tokens":{"input_tokens":2}}', encoding="utf-8")
            invalid = subprocess.run(
                [sys.executable, str(SCRIPT), str(baseline), "--compare", str(candidate),
                 "--pricing", str(pricing)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("requires a non-negative numeric rate", invalid.stderr)

    def test_repeated_message_ids_are_counted_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            transcript = folder / "session.jsonl"
            row = {"uuid": "a", "message": {"id": "same", "usage": {"input_tokens": 100}}}
            write_transcript(transcript, [row, {**row, "uuid": "duplicate"}])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(transcript), "--json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["baseline"]["messages"], 1)
            self.assertEqual(report["baseline"]["usage"]["input_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
