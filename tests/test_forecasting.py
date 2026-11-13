"""Causal split and coverage checks for the retrospective RTT study."""
from __future__ import annotations

import csv
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leo_agent_study.forecasting import (
    Model, Sample, evaluate, fit, load_samples, paired_block_interval,
)


def regular_samples(n=500):
    return [Sample(i / 5, 100.0 + i % 5) for i in range(n)]


class ForecastingTests(unittest.TestCase):
    def test_fit_is_invariant_to_unavailable_future_observations(self):
        samples = regular_samples()
        # A probe sent before cutoff but still in flight is also future evidence.
        samples[49] = Sample(9.8, 1000.0)
        cutoff = 10.0
        changed = [Sample(s.timestamp_s, s.rtt_ms if s.available_s <= cutoff else
                          s.rtt_ms + 5000.0, s.segment) for s in samples]
        original = fit(samples, cutoff)
        altered = fit(changed, cutoff)
        self.assertEqual(original, altered)
        known = [s for s in samples if s.available_s <= cutoff]
        self.assertNotIn(samples[49], known)
        self.assertEqual(original.train_median,
                         statistics.median(s.rtt_ms for s in known))
        self.assertEqual(original.predict(known, 10.5), altered.predict(known, 10.5))

    def test_predictions_only_use_available_replies_and_label_persistence(self):
        samples = regular_samples()
        samples[320] = Sample(64.0, 1200.0)
        predict = Model.predict
        checked = []
        before_long_reply = []
        after_long_reply = []

        def audit(model, history, target_t):
            origin = target_t - 0.5
            self.assertTrue(all(s.available_s <= origin + 1e-9 for s in history))
            if 64.2 < origin < 65.2 - 1e-9:
                before_long_reply.append(origin)
                self.assertNotIn(samples[320], history)
            if abs(origin - 65.2) < 1e-9:
                after_long_reply.append(origin)
                self.assertIn(samples[320], history)
                self.assertEqual(history[-1], samples[320])
            checked.append(origin)
            return predict(model, history, target_t)

        with patch.object(Model, "predict", audit):
            report, rows = evaluate(samples, horizons=(0.5,))
        self.assertTrue(checked)
        self.assertTrue(before_long_reply)
        self.assertTrue(after_long_reply)
        last_received = next(row for row in rows if abs(row["origin_s"] - 65.2) < 1e-9)
        self.assertEqual(last_received["persistence"], 1200.0)
        self.assertIn("last RTT received", report["baseline_definitions"]["persistence"])

    def test_validation_labels_arrive_before_test_and_selection_ignores_test(self):
        samples = [Sample(i / 5, 100.0) for i in range(500)]
        # Target sent at 79.8 has its result only at 80.8; test begins at 80.
        samples[399] = Sample(79.8, 1000.0)
        report, rows = evaluate(samples, horizons=(0.5,))
        cutoff = report["split"]["test_start_s"]
        self.assertEqual(cutoff, 80.0)
        validation = [r for r in rows if r["split"] == "validation"]
        test = [r for r in rows if r["split"] == "test"]
        self.assertTrue(all(r["target_available_s"] <= cutoff for r in validation))
        self.assertTrue(all(r["origin_s"] < cutoff and r["target_s"] < cutoff
                            for r in validation))
        self.assertTrue(all(r["origin_s"] >= cutoff for r in test))
        self.assertFalse(any(r["target_s"] == 79.8 for r in validation))
        horizon = report["horizons"]["0.5"]
        coverage = horizon["coverage"]["validation"]
        self.assertEqual(coverage["excluded_origins_by_reason"]
                         ["validation_label_unavailable_at_test_start"], 1)
        for split in ("validation", "test"):
            cov = horizon["coverage"][split]
            self.assertEqual(cov["candidate_response_origins"],
                             cov["eligible_forecasts"] +
                             sum(cov["excluded_origins_by_reason"].values()))
            self.assertEqual(cov["eligible_fraction"], cov["eligible_forecasts"] /
                             cov["candidate_response_origins"])
        # Mutate both an unavailable validation label and every test label.
        changed = [Sample(s.timestamp_s, 1500.0 if s.timestamp_s >= 79.8 else s.rtt_ms)
                   for s in samples]
        other, _ = evaluate(changed, horizons=(0.5,))
        other_horizon = other["horizons"]["0.5"]
        self.assertEqual(horizon["validation"], other_horizon["validation"])
        self.assertEqual(horizon["validation_selected_baseline"],
                         other_horizon["validation_selected_baseline"])
        self.assertEqual(horizon["validation_selected_phase_candidate"],
                         other_horizon["validation_selected_phase_candidate"])
        self.assertEqual(set(horizon["test"]), set(horizon["validation"]))
        self.assertIn("recent_mean", horizon["test"])
        self.assertTrue(all(i["baseline"] == "recent_mean" for i in
                            horizon["paired_intervals_vs_recent_mean"]))

    def test_collection_gaps_reset_recent_history_and_reduce_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["timestamp_s", "rtt_ms"])
                for i in range(500):
                    offset = 0 if i < 350 else 20 if i < 450 else 40
                    rtt = 100 if i < 350 else 200 if i < 450 else 300
                    writer.writerow([i / 5 + offset, rtt])
            samples, metadata = load_samples(path, gap_s=2.0)
        self.assertEqual(metadata["segments"], 3)
        report, rows = evaluate(samples, horizons=(0.5,))
        self.assertTrue(rows)
        segment_by_time = {s.timestamp_s: s.segment for s in samples}
        origin_segment = {s.available_s: s.segment for s in samples}
        for row in rows:
            self.assertEqual(row["segment"], segment_by_time[row["target_s"]])
            self.assertEqual(row["segment"], origin_segment[row["origin_s"]])
        first_second_segment = min((r for r in rows if r["segment"] == 1),
                                   key=lambda r: r["origin_s"])
        first_third_segment = min((r for r in rows if r["segment"] == 2),
                                  key=lambda r: r["origin_s"])
        self.assertEqual(first_second_segment["recent_mean"], 200.0)
        self.assertEqual(first_third_segment["recent_mean"], 300.0)
        coverage = report["horizons"]["0.5"]["coverage"]
        self.assertGreater(sum(c["excluded_origins_by_reason"].get(
            "different_continuity_segment", 0) for c in coverage.values()), 0)
        for cov in coverage.values():
            self.assertLess(cov["eligible_fraction"], 1.0)
            self.assertGreaterEqual(cov["actual_lead_s"]["min"], 0.5 - 1e-9)
            self.assertLessEqual(cov["actual_lead_s"]["max"], 0.9 + 1e-9)
            self.assertEqual(cov["reused_target_forecasts"], cov["eligible_forecasts"] -
                             cov["unique_recorded_targets"])

    def test_descriptive_block_bootstrap_is_reproducible_and_segment_aware(self):
        rows = [{"origin_s": float(i), "segment": int(i >= 6), "truth_ms": 100.0,
                 "baseline": 104.0 + i % 3, "candidate": 99.0 + i % 4}
                for i in range(12)]
        result = paired_block_interval(rows, "baseline", "candidate", block_s=60,
                                       seed=123, repetitions=250)
        repeated = paired_block_interval(rows, "baseline", "candidate", block_s=60,
                                         seed=123, repetitions=250)
        self.assertEqual(result, repeated)
        self.assertEqual(result["occupied_blocks"], 2)
        self.assertEqual(result["continuity_segments"], 2)
        expected = statistics.mean(abs(r["baseline"] - r["truth_ms"]) -
                                   abs(r["candidate"] - r["truth_ms"]) for r in rows)
        self.assertEqual(result["mae_reduction_ms"], expected)
        low, high = result["descriptive_95pct_interval_ms"]
        self.assertLessEqual(low, high)
        self.assertIn("descriptive", result["interpretation"])
        self.assertEqual(rows[0]["baseline"], 104.0)


if __name__ == "__main__":
    unittest.main()
