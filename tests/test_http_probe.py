"""Behavioral checks for the measured localhost capability probe."""

import json
from pathlib import Path
import tempfile
import unittest

from leo_agent_study.http_probe import EXPECTED_BRIEF, run_probe


class HttpProbeTests(unittest.TestCase):
    def test_real_requests_have_causal_events_and_retry_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_probe(tmp, policy_wait_seconds=0.002, retry_backoff_seconds=0)
            events = [json.loads(s) for s in (Path(tmp) / "events.jsonl").read_text().splitlines()]
            self.assertTrue(result["identical_successful_outputs"])
            for run in result["runs"]:
                self.assertEqual(run["brief"], EXPECTED_BRIEF)
                self.assertEqual(run["attempts_by_operation"], {"plan": 1, "resources": 1, "requirements": 2, "synthesize": 1})
                self.assertEqual(run["request_attempts"], 5)
                self.assertEqual(len(run["server_request_audit"]), 5)
                self.assertEqual([a["status"] for a in run["server_request_audit"]], [200, 200, 503, 200, 200])
                # The successful first read is not fetched again after the other read fails.
                self.assertEqual(sum(a["path"] == "/fixtures/resources" for a in run["server_request_audit"]), 1)
                self.assertEqual(run["request_payload_bytes"], sum(a["request_payload_bytes"] for a in run["server_request_audit"]))
                self.assertEqual(run["response_payload_bytes"], sum(a["response_payload_bytes"] for a in run["server_request_audit"]))
                own = [e for e in events if e["policy"] == run["policy"]]
                self.assertEqual([e["elapsed_seconds"] for e in own], sorted(e["elapsed_seconds"] for e in own))
                started, completed = {}, {}
                for event in own:
                    if event["event"] == "request_start":
                        for dependency in event["dependency_request_ids"]:
                            self.assertIn(dependency, completed)
                            self.assertLessEqual(completed[dependency]["elapsed_seconds"], event["elapsed_seconds"])
                        started[event["request_id"]] = event
                    if event["event"] == "request_end":
                        self.assertIn(event["request_id"], started)
                        self.assertGreaterEqual(event["measured_seconds"], 0)
                        self.assertGreaterEqual(event["elapsed_seconds"], started[event["request_id"]]["elapsed_seconds"])
                        completed[event["request_id"]] = event
                self.assertEqual(len(started), len(completed))
                if run["policy"] == "bounded_wait":
                    waits = [e for e in own if e["event"] == "wait_end" and e["wait_kind"] == "policy"]
                    self.assertEqual(len(waits), 5)
                    self.assertAlmostEqual(run["policy_wait_requested_seconds"], 0.01)
                    self.assertTrue(all(e["measured_seconds"] >= e["requested_seconds"] for e in waits))
                else:
                    self.assertEqual(run["policy_wait_requested_seconds"], 0)

    def test_exhausted_retry_does_not_synthesize_or_forge_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_probe(tmp, max_attempts=1, policy_wait_seconds=0, retry_backoff_seconds=0)
            self.assertFalse(result["identical_successful_outputs"])
            for run in result["runs"]:
                self.assertFalse(run["success"])
                self.assertIsNone(run["brief"])
                self.assertIsNone(run["output_sha256"])
                self.assertEqual(run["request_attempts"], 3)
                self.assertNotIn("synthesize", run["attempts_by_operation"])
                self.assertEqual(run["completed_checkpoint_sources"], ["resources"])

    def test_no_injected_failure_needs_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_probe(tmp, inject_transient_failure=False, max_attempts=1, policy_wait_seconds=0)
            self.assertTrue(result["identical_successful_outputs"])
            self.assertTrue(all(r["request_attempts"] == 4 for r in result["runs"]))

    def test_wait_and_retry_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            for settings in ({"policy_wait_seconds": -1}, {"policy_wait_seconds": 1}, {"retry_backoff_seconds": 1}, {"max_attempts": 0}):
                with self.assertRaises(ValueError):
                    run_probe(tmp, **settings)


if __name__ == "__main__":
    unittest.main()
