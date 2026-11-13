"""Causal, chronologically held-out RTT forecasts; no bandwidth/agent inference.

Availability is conservatively recorded timestamp + measured RTT. Positive RTT rows
only are forecast targets; missing ping samples never become inferred losses.
Phase structure is an empirical candidate, not proof of satellite handovers.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Sample:
    timestamp_s: float
    rtt_ms: float
    segment: int = 0

    @property
    def available_s(self) -> float:
        return self.timestamp_s + self.rtt_ms / 1000.0


def load_samples(path: Path, gap_s: float = 2.0) -> tuple[list[Sample], dict]:
    if not math.isfinite(gap_s) or gap_s <= 0:
        raise ValueError("gap_s must be finite and positive")
    samples = []
    dropped = 0
    previous = None
    segment = 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                t, rtt = float(row["timestamp_s"]), float(row["rtt_ms"])
            except (ValueError, KeyError):
                dropped += 1
                continue
            if not (math.isfinite(t) and math.isfinite(rtt) and rtt > 0):
                dropped += 1
                continue
            if previous is not None:
                if t <= previous:
                    raise ValueError("Samples must be strictly increasing in timestamp")
                if t - previous > gap_s:
                    segment += 1
            samples.append(Sample(t, rtt, segment))
            previous = t
    if len(samples) < 100:
        raise ValueError("At least 100 valid samples are required for the temporal split")
    return samples, {"valid_samples": len(samples), "invalid_or_missing_rows": dropped,
                     "segments": segment + 1, "gap_threshold_s": gap_s,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@dataclass
class Model:
    train_median: float
    profiles: dict[int, dict[int, float]]
    bin_width_s: float = 0.5

    def phase(self, t: float, period: int) -> float:
        index = int((t % period) / self.bin_width_s)
        return self.profiles[period].get(index, self.train_median)

    def predict(self, history: list[Sample], target_t: float) -> dict[str, float]:
        """Use reception-ordered available history, resetting recent state by segment.

        Persistence is the last RTT received, which may be an older probe when
        replies arrive out of send order. The caller enforces availability.
        """
        if not history:
            raise ValueError("Prediction requires already available history")
        segment = history[-1].segment
        recent = [s for s in history[-100:] if s.segment == segment][-20:]
        level = statistics.mean(s.rtt_ms for s in recent)
        result = {"train_median": self.train_median,
                  "persistence": history[-1].rtt_ms,
                  "recent_mean": level}
        for period in self.profiles:
            # Learned phase plus an offset estimated solely from past observations.
            offset = statistics.mean(s.rtt_ms - self.phase(s.timestamp_s, period)
                                     for s in recent)
            result[f"phase_adaptive_{period}s"] = max(
                0.0, self.phase(target_t, period) + offset)
        return result


def fit(samples: list[Sample], cutoff_s: float, periods=(5, 10, 15, 30),
        bin_width_s: float = 0.5) -> Model:
    if not math.isfinite(bin_width_s) or bin_width_s <= 0:
        raise ValueError("bin_width_s must be finite and positive")
    if not periods or any(not math.isfinite(p) or p <= 0 for p in periods):
        raise ValueError("periods must contain finite positive periods")
    training = [s for s in samples if s.available_s <= cutoff_s]
    if not training:
        raise ValueError("No observations are available before training cutoff")
    median = statistics.median(s.rtt_ms for s in training)
    profiles = {}
    for period in periods:
        bins = defaultdict(list)
        for s in training:
            bins[int((s.timestamp_s % period) / bin_width_s)].append(s.rtt_ms)
        profiles[period] = {i: statistics.median(v) for i, v in bins.items()}
    return Model(median, profiles, bin_width_s)


def metrics(rows: list[dict], model: str) -> dict:
    errors = [float(r[model]) - r["truth_ms"] for r in rows]
    if not errors:
        raise ValueError("No eligible forecast targets in split")
    absolute = sorted(abs(e) for e in errors)
    return {"n": len(errors), "mae_ms": statistics.mean(absolute),
            "rmse_ms": math.sqrt(statistics.mean(e * e for e in errors)),
            "bias_ms": statistics.mean(errors),
            "p90_absolute_error_ms": absolute[min(len(absolute)-1, math.ceil(.9*len(absolute))-1)]}


def paired_block_interval(rows: list[dict], baseline: str, candidate: str,
                          block_s: float = 60, seed: int = 20261113,
                          repetitions: int = 2000) -> dict:
    """Descriptive paired time-block bootstrap, not independent-user inference.

    Occupied bins are resampled within this one recorded trace. Sparse segments,
    reused targets, model-selection uncertainty, and nonstationarity prevent a
    population or causal interpretation of the reported percentile interval.
    """
    if not rows:
        raise ValueError("At least one forecast row is required")
    if not math.isfinite(block_s) or block_s <= 0 or repetitions < 1:
        raise ValueError("block_s and repetitions must be positive")
    blocks = defaultdict(list)
    start = min(r["origin_s"] for r in rows)
    for r in rows:
        difference = abs(r[baseline] - r["truth_ms"]) - abs(r[candidate] - r["truth_ms"])
        # Segment boundaries prevent treating a gap as observed network behavior.
        key = (r["segment"], int((r["origin_s"] - start) // block_s))
        blocks[key].append(difference)
    summaries = [(sum(v), len(v)) for v in blocks.values()]
    rng = random.Random(seed)
    draws = []
    for _ in range(repetitions):
        selected = rng.choices(summaries, k=len(summaries))
        draws.append(sum(v for v, _ in selected) / sum(n for _, n in selected))
    draws.sort()
    n = len(draws)
    return {"baseline": baseline, "candidate": candidate,
            "mae_reduction_ms": statistics.mean(
                abs(r[baseline]-r["truth_ms"])-abs(r[candidate]-r["truth_ms"]) for r in rows),
            "descriptive_95pct_interval_ms": [draws[int(.025*n)], draws[min(n-1,int(.975*n))]],
            "block_seconds": block_s, "occupied_blocks": len(summaries),
            "continuity_segments": len({r["segment"] for r in rows}),
            "resampling_unit": "occupied time bins separated by continuity segment",
            "interpretation": "descriptive trace resampling; not independent-user or causal inference",
            "bootstrap_repetitions": repetitions, "seed": seed}


def _coverage(rows: list[dict], candidate_origins: int, exclusions: dict) -> dict:
    """Coverage is conditional on recorded successful response origins."""
    target_counts = defaultdict(int)
    for row in rows:
        target_counts[row["target_s"]] += 1
    leads = [row["actual_lead_s"] for row in rows]
    return {"candidate_response_origins": candidate_origins,
            "eligible_forecasts": len(rows),
            "eligible_fraction": len(rows) / candidate_origins if candidate_origins else None,
            "unique_recorded_targets": len(target_counts),
            "reused_target_forecasts": len(rows) - len(target_counts),
            "maximum_forecasts_per_target": max(target_counts.values(), default=0),
            "continuity_segments": len({row["segment"] for row in rows}),
            "actual_lead_s": {"min": min(leads), "median": statistics.median(leads),
                              "max": max(leads)} if leads else None,
            "excluded_origins_by_reason": dict(sorted(exclusions.items()))}


def evaluate(samples: list[Sample], horizons=(0.5, 1.0, 2.0, 5.0),
             seed: int = 20261113) -> tuple[dict, list[dict]]:
    """60/20/20 split by chronological row count; validation selects models only.

    Origins are conservatively available RTT responses. Targets use the first
    recorded sample at/after origin+nominal horizon, at most 0.4s late and in the
    same continuity segment. Forecast phase uses the requested target time, never
    the actual future measurement timestamp. Validation labels must themselves
    be available by the test boundary. Test predictions may use earlier test RTTs
    only after those measurements become available, as in online deployment.
    """
    n = len(samples)
    if n < 100:
        raise ValueError("At least 100 samples are required for the temporal split")
    if not horizons or any(not math.isfinite(h) or h <= 0 for h in horizons):
        raise ValueError("horizons must contain finite positive nominal lead times")
    train_end = samples[int(.6*n)].timestamp_s
    test_start = samples[int(.8*n)].timestamp_s
    model = fit(samples, train_end)
    names = ["train_median", "persistence", "recent_mean",
             *(f"phase_adaptive_{period}s" for period in model.profiles)]
    sent_times = [s.timestamp_s for s in samples]
    available = sorted(samples, key=lambda s: s.available_s)
    all_rows = []
    by_horizon = {}
    for horizon in horizons:
        rows = []
        candidates = defaultdict(int)
        excluded = {"validation": defaultdict(int), "test": defaultdict(int)}
        for i, s in enumerate(available):
            origin = s.available_s
            if origin < train_end:
                continue
            # Split origins before inspecting future targets; exclusions retain
            # their denominator instead of silently improving coverage.
            split = "validation" if origin < test_start else "test"
            candidates[split] += 1
            requested_t = origin + horizon
            target_index = bisect.bisect_left(sent_times, requested_t)
            if target_index == n:
                excluded[split]["no_recorded_future_target"] += 1
                continue
            target = samples[target_index]
            if target.segment != s.segment:
                excluded[split]["different_continuity_segment"] += 1
                continue
            if target.timestamp_s - requested_t > .4:
                excluded[split]["target_more_than_0.4s_late"] += 1
                continue
            if split == "validation":
                if target.timestamp_s >= test_start:
                    excluded[split]["target_crosses_test_boundary"] += 1
                    continue
                if target.available_s > test_start:
                    excluded[split]["validation_label_unavailable_at_test_start"] += 1
                    continue
            history = available[max(0,i-99):i+1]
            prediction = model.predict(history, requested_t)
            row = {"origin_s": origin, "requested_target_s": requested_t,
                   "target_s": target.timestamp_s,
                   "target_available_s": target.available_s,
                   "horizon_s": horizon, "actual_lead_s": target.timestamp_s-origin,
                   "latest_available_s": s.available_s, "segment": target.segment,
                   "split": split, "truth_ms": target.rtt_ms, **prediction}
            rows.append(row)
        validation = [r for r in rows if r["split"] == "validation"]
        test = [r for r in rows if r["split"] == "test"]
        baseline = min(["train_median", "persistence", "recent_mean"],
                       key=lambda name: metrics(validation,name)["mae_ms"])
        phase = min([name for name in names if name.startswith("phase_")],
                    key=lambda name: metrics(validation,name)["mae_ms"])
        by_horizon[str(horizon)] = {
            "validation_selected_baseline": baseline,
            "validation_selected_phase_candidate": phase,
            "coverage": {
                "validation": _coverage(validation, candidates["validation"], excluded["validation"]),
                "test": _coverage(test, candidates["test"], excluded["test"])},
            "validation": {name: metrics(validation,name) for name in names},
            "test": {name: metrics(test,name) for name in names},
            "paired_intervals": [paired_block_interval(test,baseline,phase,b,seed)
                                 for b in (15,60,120)],
            "paired_intervals_vs_recent_mean": [
                paired_block_interval(test,"recent_mean",phase,b,seed)
                for b in (15,60,120)]}
        all_rows.extend(rows)
    report = {"kind": "retrospective_public_starlink_rtt_forecasting",
              "not_measured": ["agent task benefit", "browser or LLM task performance",
                               "Helene recovery-hub conditions", "available bandwidth", "packet loss"],
              "split": {"rule": "chronological 60/20/20 row-count split",
                        "train_end_s": train_end,"test_start_s": test_start,
                        "validation_label_rule": "target RTT available by test_start_s"},
              "availability_rule": "record timestamp + RTT; conservative when timestamp semantics uncertain",
              "baseline_definitions": {
                  "train_median": "median of RTT observations available at the training cutoff",
                  "persistence": "last RTT received; reception order, not latest probe send time",
                  "recent_mean": "mean of up to 20 latest received RTTs in the same continuity segment"},
              "coverage_interpretation": "forecast instances conditional on recorded successful response origins and future targets; not uptime or loss",
              "nominal_horizon_rule": "first recorded target at/after requested time, at most 0.4 seconds late",
              "phase_bin_seconds": .5, "candidate_period_seconds": [5,10,15,30],
              "model_selection": "validation MAE only; training profile frozen before validation/test; no test-based candidate selection",
              "online_history": "adaptive test predictions may use earlier test RTTs only after their reception",
              "horizons": by_horizon, "seed": seed}
    return report, all_rows
