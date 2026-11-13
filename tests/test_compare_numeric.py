"""Artifact verification tolerates roundoff without concealing scientific changes."""
from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.compare_numeric import ComparisonError, compare_paths


class NumericComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def write_csv(self, name, rows):
        path = self.root / name
        opener = gzip.open if name.endswith(".gz") else open
        with opener(path, "wt", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)
        return path

    def test_json_accepts_roundoff_and_key_order(self):
        expected = self.write_json("expected.json", {
            "selection": "recent_mean", "count": 26, "success": True,
            "interval": [-0.097450195894755, 0.052852922210871], "missing": None})
        actual = self.write_json("actual.json", {
            "missing": None, "interval": [-0.097450195894751, 0.052852922210875],
            "success": True, "count": 26, "selection": "recent_mean"})
        self.assertEqual(compare_paths(expected, actual), ("JSON", None))

    def test_json_rejects_structure_selection_counts_and_meaningful_numeric_changes(self):
        baseline = {"selected": "phase_adaptive_10s", "n": 1363,
                    "success": True, "mae": 20.19, "epoch": 1723946587.007814,
                    "interval": [1.0, 2.0]}
        expected = self.write_json("expected.json", baseline)
        changes = [
            {**baseline, "extra": 1},
            {k: v for k, v in baseline.items() if k != "n"},
            {**baseline, "interval": [1.0]},
            {**baseline, "selected": "phase_adaptive_5s"},
            {**baseline, "n": 1364},
            {**baseline, "n": 1363.0},
            {**baseline, "success": 1},
            {**baseline, "mae": 20.1901},
            {**baseline, "epoch": 1723946587.007914},
            {**baseline, "mae": float("nan")},
            {**baseline, "mae": float("inf")},
        ]
        for index, changed in enumerate(changes):
            with self.subTest(index=index):
                actual = self.write_json("actual.json", changed)
                with self.assertRaises(ComparisonError):
                    compare_paths(expected, actual)

    def test_csv_and_gzip_accept_roundoff_and_compare_decompressed_rows(self):
        header = ["id", "selected", "n", "mae", "epoch"]
        expected = self.write_csv("expected.csv", [header,
            ["S000001", "recent_mean", "1363", "20.189079436580304", "1723946587.007814"],
            ["S000002", "phase_adaptive_10s", "0", "-0.097450195894755", "1723946587.007815"]])
        actual = self.write_csv("actual.csv.gz", [header,
            ["S000001", "recent_mean", "1363", "20.189079436580308", "1723946587.007814"],
            ["S000002", "phase_adaptive_10s", "0", "-0.097450195894751", "1723946587.007815"]])
        self.assertEqual(compare_paths(expected, actual), ("CSV", 2))

    def test_csv_rejects_headers_counts_selection_and_epoch_drift(self):
        header = ["id", "selected", "n", "mae", "epoch"]
        row = ["S000001", "recent_mean", "1363", "20.19", "1723946587.007814"]
        expected = self.write_csv("expected.csv.gz", [header, row])
        changes = [
            [list(reversed(header)), row],
            [header],
            [header, row, row],
            [header, row[:-1]],
            [header, ["S000002", *row[1:]]],
            [header, [row[0], "train_median", *row[2:]]],
            [header, [*row[:2], "1364", *row[3:]]],
            [header, [*row[:2], "1363.0", *row[3:]]],
            [header, [*row[:3], "20.1901", row[4]]],
            [header, [*row[:4], "1723946587.007914"]],
        ]
        for index, changed in enumerate(changes):
            with self.subTest(index=index):
                actual = self.write_csv("actual.csv", changed)
                with self.assertRaises(ComparisonError):
                    compare_paths(expected, actual)

    def test_cli_counts_streamed_rows_and_reports_one_concise_failure(self):
        expected = self.write_csv("expected.csv", [["n", "value"],
            *([str(i), str(i + 0.5)] for i in range(10000))])
        actual = self.write_csv("actual.csv.gz", [["n", "value"],
            *([str(i), str(i + 0.5)] for i in range(10000))])
        script = Path(__file__).resolve().parents[1] / "scripts" / "compare_numeric.py"
        command = [sys.executable, str(script), str(expected), str(actual)]
        success = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertIn("10000 data rows", success.stdout)
        self.assertEqual(success.stderr, "")
        self.assertLess(len(success.stdout), 160)
        self.write_csv("actual.csv.gz", [["n", "value"], ["0", "0.5001"]])
        failure = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(failure.returncode, 1)
        self.assertEqual(failure.stdout, "")
        self.assertIn("CSV row 1", failure.stderr)
        self.assertLess(len(failure.stderr), 300)


if __name__ == "__main__":
    unittest.main()
