#!/usr/bin/env python3
"""Compare scientific JSON/CSV artifacts without platform roundoff failures.

JSON structure, strings, booleans, nulls and integers compare exactly. Finite
floating-point numbers allow an absolute difference of 1e-9, with no relative
allowance: large Unix timestamps must not conceal millisecond-scale changes.
CSV headers and text compare exactly; integer cells compare as exact integers,
while decimal/exponent cells use the same finite-float rule. CSV rows stream,
including gzip inputs, so gzip metadata and serialization roundoff do not matter.

Usage: python3 scripts/compare_numeric.py EXPECTED ACTUAL
"""
from __future__ import annotations

import argparse
import csv
import gzip
import itertools
import json
import math
import re
import sys
from pathlib import Path

ABS_TOL = 1e-9
REL_TOL = 0.0
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_FLOAT = re.compile(r"[+-]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)\Z")
_MISSING = object()


class ComparisonError(ValueError):
    """An artifact differs beyond permitted numeric roundoff."""


def _short(value):
    result = repr(value)
    return result if len(result) <= 90 else result[:87] + "..."


def _different(location, expected, actual):
    raise ComparisonError(f"{location}: expected {_short(expected)}, got {_short(actual)}")


def _compare_float(expected, actual, location):
    if not (math.isfinite(expected) and math.isfinite(actual)):
        raise ComparisonError(f"{location}: nonfinite numeric value")
    if not math.isclose(expected, actual, abs_tol=ABS_TOL, rel_tol=REL_TOL):
        _different(location, expected, actual)


def _compare_json(expected, actual, location="$"):
    if type(expected) is not type(actual):
        raise ComparisonError(f"{location}: type changed from {type(expected).__name__} "
                              f"to {type(actual).__name__}")
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            missing = sorted(expected.keys() - actual.keys())[:3]
            extra = sorted(actual.keys() - expected.keys())[:3]
            raise ComparisonError(f"{location}: object keys differ; "
                                  f"missing={_short(missing)}, extra={_short(extra)}")
        for key, value in expected.items():
            _compare_json(value, actual[key], f"{location}[{_short(key)}]")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise ComparisonError(f"{location}: array length {len(expected)} != {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            _compare_json(left, right, f"{location}[{index}]")
    elif isinstance(expected, float):
        _compare_float(expected, actual, location)
    elif expected != actual:
        _different(location, expected, actual)


def _reject_nonfinite(value):
    raise ComparisonError(f"Nonfinite JSON constant {value}")


def _cell_kind(value):
    if _INTEGER.fullmatch(value):
        return "integer"
    if _FLOAT.fullmatch(value):
        return "float"
    return "text"


def _compare_cell(expected, actual, location):
    left_kind, right_kind = _cell_kind(expected), _cell_kind(actual)
    if left_kind != right_kind:
        raise ComparisonError(f"{location}: cell kind changed from {left_kind} to {right_kind}")
    if left_kind == "float":
        _compare_float(float(expected), float(actual), location)
    elif left_kind == "integer":
        if int(expected) != int(actual):
            _different(location, expected, actual)
    elif expected != actual:
        _different(location, expected, actual)


def _open_text(path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _compare_csv(expected_path, actual_path):
    with _open_text(expected_path) as left, _open_text(actual_path) as right:
        expected, actual = csv.reader(left), csv.reader(right)
        expected_header, actual_header = next(expected, None), next(actual, None)
        if expected_header != actual_header:
            _different("CSV header", expected_header, actual_header)
        rows = 0
        for rows, (left_row, right_row) in enumerate(
                itertools.zip_longest(expected, actual, fillvalue=_MISSING), 1):
            if left_row is _MISSING or right_row is _MISSING:
                left_count = rows - 1 if left_row is _MISSING else rows + sum(1 for _ in expected)
                right_count = rows - 1 if right_row is _MISSING else rows + sum(1 for _ in actual)
                raise ComparisonError(f"CSV data-row count {left_count} != {right_count}")
            if len(left_row) != len(expected_header):
                raise ComparisonError(f"CSV expected row {rows}: field count does not match header")
            if len(right_row) != len(expected_header):
                raise ComparisonError(f"CSV actual row {rows}: field count does not match header")
            for column, (left_value, right_value) in enumerate(zip(left_row, right_row)):
                _compare_cell(left_value, right_value,
                              f"CSV row {rows}, column {_short(expected_header[column])}")
    return rows


def _format(path):
    if path.name.endswith(".json"):
        return "JSON"
    if path.name.endswith((".csv", ".csv.gz")):
        return "CSV"
    raise ComparisonError(f"Unsupported artifact format: {path.name}")


def compare_paths(expected_path: str | Path, actual_path: str | Path) -> tuple[str, int | None]:
    """Raise ComparisonError on a meaningful difference; return format/row count."""
    expected_path, actual_path = Path(expected_path), Path(actual_path)
    kind = _format(expected_path)
    if _format(actual_path) != kind:
        raise ComparisonError("Expected and actual artifact formats differ")
    if kind == "JSON":
        with _open_text(expected_path) as left, _open_text(actual_path) as right:
            _compare_json(json.load(left, parse_constant=_reject_nonfinite),
                          json.load(right, parse_constant=_reject_nonfinite))
        return kind, None
    return kind, _compare_csv(expected_path, actual_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args(argv)
    try:
        kind, rows = compare_paths(args.expected, args.actual)
    except (ComparisonError, OSError, UnicodeError, csv.Error, json.JSONDecodeError) as error:
        print(f"Artifact comparison failed: {error}", file=sys.stderr)
        return 1
    suffix = f", {rows} data rows" if rows is not None else ""
    print(f"Equivalent {kind}{suffix}; float abs_tol={ABS_TOL:g}, rel_tol={REL_TOL:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
