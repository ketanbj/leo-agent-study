"""Audit determinism, paired controls, and retention of failed virtual runs."""

import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from leo_agent_study.synthetic_study import SweepConfig, evaluate_scenario, run_study, scenarios


def small_config():
    return SweepConfig(periods_s=(5.0,), outage_fractions=(0.2,),
                       detection_delay_ratios=(0.0, 2.0), deadlines_s=(30.0,),
                       max_attempts=(3,), retry_backoffs_s=(0.25,),
                       good_rates_bytes_per_s=(262144.0,), phase_count=2,
                       progress_bad_capacity_fractions=(0.0,))


class SyntheticStudyTests(unittest.TestCase):
    def test_paired_progress_control_has_no_positive_headroom(self):
        count = 0
        for scenario in scenarios(small_config()):
            if scenario.regime != "progress_control":
                continue
            count += 1
            results = evaluate_scenario(scenario)
            asap = results["asap"].restricted_completion_s(scenario.deadline_s)
            for result in results.values():
                self.assertGreaterEqual(result.restricted_completion_s(scenario.deadline_s) + 1e-8, asap)
        self.assertEqual(count, 6)

    def test_written_records_include_all_policies_and_are_deterministic(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            summary = run_study(Path(first), config=small_config())
            again = run_study(Path(second), config=small_config())
            self.assertEqual(summary, again)
            for name in ("configuration.json", "summary.json", "summary.csv", "runs.csv.gz", "README.md"):
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes(), name)
            self.assertEqual(summary["scenario_counts"], {
                "stable_control": 3, "progress_control": 6, "restart_on_outage": 12})
            self.assertEqual(summary["policy_runs"], 69)
            with gzip.open(Path(first) / "runs.csv.gz", "rt", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), summary["policy_runs"])
            self.assertTrue(any(row["completed_chain"] == "0" for row in rows))
            for row in rows:
                if row["completed_chain"] == "0":
                    self.assertEqual(float(row["restricted_completion_s"]), float(row["deadline_s"]))
            grouped = {}
            for row in rows:
                grouped.setdefault(row["scenario_id"], []).append(row)
            for group in grouped.values():
                policies = {row["policy"] for row in group}
                expected = {"asap", "ideal_reactive", "perfect_future_oracle"}
                if group[0]["regime"] == "progress_control":
                    expected.add("deliberate_wait_control")
                self.assertEqual(policies, expected)
            manifest = json.loads((Path(first) / "manifest.json").read_text())
            for name, expected in manifest["data_sha256"].items():
                self.assertEqual(hashlib.sha256((Path(first) / name).read_bytes()).hexdigest(), expected)

    def test_zero_detection_ideal_reactive_tie_is_retained(self):
        with tempfile.TemporaryDirectory() as output:
            summary = run_study(Path(output), config=small_config())
        values = summary["restart_breakdown_by_detection_delay_ratio"]["0.0"]["oracle_vs_ideal_reactive"]
        self.assertEqual(values["oracle_lower_restricted_time"], 0)
        self.assertEqual(values["oracle_higher_restricted_time"], 0)
        self.assertEqual(values["aggregate_restricted_time_reduction_fraction"], 0)
        self.assertEqual(summary["negative_control_violations"], 0)


if __name__ == "__main__":
    unittest.main()
