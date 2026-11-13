"""Reproducible synthetic timing-headroom sweep, not a LEO measurement study.

The sweep compares immediate dispatch, an optimistic current-state reactive
controller, and perfect-future outage admission on fixed serial tool/model
exchange traces.  Perfect-future admission is an upper bound, not a trained or
deployable predictor.  All capacities, outages, payloads, inference delays,
failure detection delays, and retry budgets are specified experimental inputs.

The progress-preserving control has a FIFO service model in which waiting cannot
accelerate a serial chain.  Its oracle therefore dispatches immediately.  An
additional deliberate-wait control checks that nonnegative waits produce no
spurious positive gain.  The secondary model assumes entire RPC sessions restart
on any outage, even during remote inference; this strong synthetic assumption is
the explicit source of possible admission headroom.

Run with ``python -m leo_agent_study.synthetic_study --output results/synthetic``.
The public API is ``run_study(output: Path)``.  Nothing contacts the Internet,
invokes a language model, generates assistance advice, or measures a satellite.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import asdict, dataclass
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import platform
import random
import sys
from typing import Iterable

from .scheduling import (
    Operation, RunResult, asap_policy, periodic_trace, reactive_policy,
    run_chain, uninterrupted_dispatch_time,
)


@dataclass(frozen=True)
class SweepConfig:
    seed: int = 20261113
    periods_s: tuple[float, ...] = (5.0, 15.0, 30.0)
    outage_fractions: tuple[float, ...] = (0.05, 0.20, 0.40)
    detection_delay_ratios: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)
    deadlines_s: tuple[float, ...] = (30.0, 90.0)
    max_attempts: tuple[int, ...] = (3, 8)
    retry_backoffs_s: tuple[float, ...] = (0.25, 1.0)
    good_rates_bytes_per_s: tuple[float, ...] = (262144.0, 8388608.0)
    phase_count: int = 6
    propagation_s: float = 0.03
    progress_bad_capacity_fractions: tuple[float, ...] = (0.0, 0.10)
    progress_deadline_s: float = 90.0

    def __post_init__(self) -> None:
        if self.phase_count < 1:
            raise ValueError("phase_count must be positive")
        if not self.periods_s or any(value <= 0 for value in self.periods_s):
            raise ValueError("periods must be nonempty and positive")
        if not self.outage_fractions or any(not 0 < value < 1 for value in self.outage_fractions):
            raise ValueError("outage fractions must lie strictly between zero and one")
        if any(value < 0 for value in self.detection_delay_ratios):
            raise ValueError("detection delay ratios cannot be negative")
        if not self.deadlines_s or any(value <= 0 for value in self.deadlines_s):
            raise ValueError("deadlines must be nonempty and positive")
        if not self.max_attempts or any(value < 1 for value in self.max_attempts):
            raise ValueError("attempt budgets must be positive")
        if not self.retry_backoffs_s or any(value < 0 for value in self.retry_backoffs_s):
            raise ValueError("retry backoffs cannot be negative")
        if not self.good_rates_bytes_per_s or any(value <= 0 for value in self.good_rates_bytes_per_s):
            raise ValueError("good rates must be positive")
        if self.propagation_s < 0 or self.progress_deadline_s <= 0:
            raise ValueError("propagation and control deadline are invalid")
        if any(not 0 <= value <= 1 for value in self.progress_bad_capacity_fractions):
            raise ValueError("progress bad capacity fractions must lie in [0, 1]")


def workloads() -> dict[str, tuple[Operation, ...]]:
    """Fixed fixtures representing three fetches and three model exchanges.

    These payloads and compute times are synthetic sensitivity settings, not
    observations of a deployed agent.  All policies receive identical fixtures.
    """
    fixtures = {}
    for name, page_bytes, context_bytes, model_wait in (
        ("short_model_wait", 32768, 16384, 0.25),
        ("mixed", 131072, 65536, 2.0),
        ("inference_dominated", 16384, 8192, 8.0),
    ):
        operations = []
        for index, purpose in enumerate(("directory", "requirements", "dates"), 1):
            operations.append(Operation(f"fetch_{purpose}", 1024, page_bytes,
                                        inference_s=0.02, local_after_s=0.05))
            operations.append(Operation(f"model_step_{index}", context_bytes, 4096,
                                        inference_s=model_wait, local_after_s=0.05))
        fixtures[name] = tuple(operations)
    return fixtures


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    regime: str
    period_s: float
    outage_fraction: float
    bad_capacity_fraction: float
    phase_s: float
    phase_index: int
    rate_bytes_per_s: float
    workload: str
    detection_delay_ratio: float
    deadline_s: float
    max_attempts: int
    retry_backoff_s: float
    propagation_s: float

    @property
    def outage_duration_s(self) -> float:
        return self.period_s * self.outage_fraction

    @property
    def failure_detection_s(self) -> float:
        return self.outage_duration_s * self.detection_delay_ratio


def scenarios(config: SweepConfig) -> Iterable[Scenario]:
    """Yield all predeclared scenarios, including stable and FIFO controls."""
    rng = random.Random(config.seed)
    phases = {period: tuple((index + rng.random()) * period / config.phase_count
                            for index in range(config.phase_count))
              for period in config.periods_s}
    names = tuple(workloads())
    index = 0
    for rate, name, deadline in itertools.product(
        config.good_rates_bytes_per_s, names, config.deadlines_s
    ):
        index += 1
        yield Scenario(f"S{index:06d}", "stable_control", 15.0, 0.0, 1.0,
                       0.0, 0, rate, name, 0.0, deadline,
                       max(config.max_attempts), min(config.retry_backoffs_s),
                       config.propagation_s)
    for period, fraction, bad_fraction, rate, name in itertools.product(
        config.periods_s, config.outage_fractions,
        config.progress_bad_capacity_fractions, config.good_rates_bytes_per_s, names
    ):
        for phase_index, phase in enumerate(phases[period]):
            index += 1
            yield Scenario(f"S{index:06d}", "progress_control", period, fraction,
                           bad_fraction, phase, phase_index, rate, name, 0.0,
                           config.progress_deadline_s, max(config.max_attempts),
                           min(config.retry_backoffs_s), config.propagation_s)
    for period, fraction, ratio, deadline, attempts, backoff, rate, name in itertools.product(
        config.periods_s, config.outage_fractions, config.detection_delay_ratios,
        config.deadlines_s, config.max_attempts, config.retry_backoffs_s,
        config.good_rates_bytes_per_s, names
    ):
        for phase_index, phase in enumerate(phases[period]):
            index += 1
            yield Scenario(f"S{index:06d}", "restart_on_outage", period, fraction,
                           0.0, phase, phase_index, rate, name, ratio, deadline,
                           attempts, backoff, config.propagation_s)


def evaluate_scenario(scenario: Scenario) -> dict[str, RunResult]:
    """Evaluate paired policies on precisely the same virtual trace and work."""
    horizon = scenario.deadline_s + 5 * scenario.period_s
    trace = periodic_trace(
        horizon_s=horizon, period_s=scenario.period_s,
        bad_start_s=scenario.period_s - scenario.outage_duration_s,
        bad_duration_s=scenario.outage_duration_s,
        good_rate_bytes_per_s=scenario.rate_bytes_per_s,
        bad_rate_bytes_per_s=scenario.rate_bytes_per_s * scenario.bad_capacity_fraction,
        phase_s=scenario.phase_s, propagation_s=scenario.propagation_s)
    mode = "progress" if scenario.regime == "progress_control" else "restart_on_outage"

    def perfect_future(ready: float, operation: Operation, attempt: int) -> float:
        # Immediate dispatch is analytically optimal for the FIFO control.
        if mode == "progress":
            return ready
        return uninterrupted_dispatch_time(trace, ready, operation)

    policies = {"asap": asap_policy,
                "ideal_reactive": reactive_policy(trace),
                "perfect_future_oracle": perfect_future}
    if mode == "progress":
        wait_s = 0.5 * scenario.outage_duration_s
        policies["deliberate_wait_control"] = lambda ready, operation, attempt: ready + wait_s
    return {name: run_chain(
        trace, workloads()[scenario.workload], policy=policy, mode=mode,
        max_attempts_per_operation=scenario.max_attempts,
        retry_backoff_s=scenario.retry_backoff_s,
        failure_detection_s=scenario.failure_detection_s,
        deadline_s=scenario.deadline_s)
        for name, policy in policies.items()}


class _Accumulator:
    def __init__(self) -> None:
        self.count = 0
        self.successes = 0
        self.sums = defaultdict(float)
        self.rct = []

    def add(self, result: RunResult, deadline: float) -> None:
        self.count += 1
        self.successes += int(result.success)
        values = {
            "restricted_completion_s": result.restricted_completion_s(deadline),
            "observed_stop_s": result.elapsed_s,
            "attempts_started": len(result.attempts),
            "failed_attempts": result.failed_attempts,
            "transmitted_bytes": result.transmitted_bytes,
            "policy_wait_s": result.policy_wait_s,
            "backoff_wait_s": result.backoff_wait_s,
        }
        for key, value in values.items():
            self.sums[key] += value
        self.rct.append(values["restricted_completion_s"])

    def summary(self) -> dict:
        values = sorted(self.rct)
        count = self.count
        p95 = values[max(0, math.ceil(0.95 * count) - 1)]
        middle = count // 2
        median = values[middle] if count % 2 else (values[middle - 1] + values[middle]) / 2
        return {"runs": count, "completed_chains": self.successes,
                "chain_completion_rate": self.successes / count,
                **{f"mean_{key}": value / count for key, value in self.sums.items()},
                "median_restricted_completion_s": median,
                "p95_restricted_completion_s": p95}


class _Pairs:
    def __init__(self) -> None:
        self.count = self.better = self.tied = self.worse = 0
        self.delta = self.base_total = self.byte_delta = self.attempt_delta = 0.0
        self.completion_delta = 0

    def add(self, oracle: RunResult, baseline: RunResult, deadline: float) -> None:
        self.count += 1
        base = baseline.restricted_completion_s(deadline)
        delta = base - oracle.restricted_completion_s(deadline)
        self.better += int(delta > 1e-8)
        self.worse += int(delta < -1e-8)
        self.tied += int(abs(delta) <= 1e-8)
        self.delta += delta
        self.base_total += base
        self.byte_delta += baseline.transmitted_bytes - oracle.transmitted_bytes
        self.attempt_delta += baseline.failed_attempts - oracle.failed_attempts
        self.completion_delta += int(oracle.success) - int(baseline.success)

    def summary(self) -> dict:
        return {"paired_scenarios": self.count,
                "oracle_lower_restricted_time": self.better,
                "equal_restricted_time": self.tied,
                "oracle_higher_restricted_time": self.worse,
                "mean_restricted_time_reduction_s": self.delta / self.count,
                "aggregate_restricted_time_reduction_fraction":
                    self.delta / self.base_total if self.base_total else 0.0,
                "chain_completion_rate_difference_pp":
                    100 * self.completion_delta / self.count,
                "mean_transmitted_bytes_saved": self.byte_delta / self.count,
                "mean_failed_attempts_avoided": self.attempt_delta / self.count}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def run_study(output: Path, *, config: SweepConfig | None = None) -> dict:
    """Run the complete declared sweep and write auditable deterministic data.

    Returns the summary dict.  ``runs.csv.gz`` contains every policy/scenario
    outcome; gzip's timestamp and filename metadata are disabled so equal input
    and code produce byte-identical results.  The aggregate is an equal-weight
    sensitivity grid, not an estimate of a real deployment's expected benefit.
    """
    config = config or SweepConfig()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    workload_config = {name: [asdict(operation) for operation in operations]
                       for name, operations in workloads().items()}
    configuration = {
        "schema_version": 1, "study_kind": "synthetic_discrete_event_sensitivity_sweep",
        "sweep": asdict(config), "workloads": workload_config,
        "units": {"time": "virtual seconds", "payload": "bytes", "capacity": "bytes/second"},
        "observed_data": False, "real_llm_invocations": 0,
        "real_browser_invocations": 0, "real_leo_measurements": 0,
        "assumptions": [
            "Fixed serial chain: three website-like exchanges and three model-like exchanges.",
            "Capacity is integrated over time; one capacity trace serves both directions.",
            "Fixed one-way propagation and fixed external compute costs.",
            "Progress control preserves partial transfers and has FIFO service.",
            "Restart model loses an entire RPC session at its first outage, including during inference.",
            "Failure detection delays and bounded retry/backoff are explicit sweep inputs.",
            "Ideal reactive observes the current state and resumes exactly when capacity returns, free of sensing cost.",
            "Perfect-future admission knows the entire future trace; it is an upper bound, not a learned predictor.",
            "Deadlines include admission waits, detection, backoff, transfer, inference, and local work.",
            "Aggregates equally weight chosen grid points; they do not estimate a population effect.",
        ],
    }
    _write_json(output / "configuration.json", configuration)
    accumulators: dict[tuple[str, str], _Accumulator] = defaultdict(_Accumulator)
    by_detection: dict[tuple[float, str], _Accumulator] = defaultdict(_Accumulator)
    pairs: dict[tuple[str, str], _Pairs] = defaultdict(_Pairs)
    detection_pairs: dict[float, _Pairs] = defaultdict(_Pairs)
    scenario_counts = defaultdict(int)
    row_count = 0
    fifo_violations = 0
    fields = [*Scenario.__dataclass_fields__, "outage_duration_s", "failure_detection_s",
              "policy", "completed_chain", "completed_operations", "finish_s",
              "observed_stop_s", "restricted_completion_s", "attempts_started",
              "failed_attempts", "transmitted_bytes", "policy_wait_s", "backoff_wait_s",
              "failure_reason"]
    with (output / "runs.csv.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for scenario in scenarios(config):
                    scenario_counts[scenario.regime] += 1
                    results = evaluate_scenario(scenario)
                    oracle = results["perfect_future_oracle"]
                    for policy, result in results.items():
                        row_count += 1
                        writer.writerow({
                            **asdict(scenario),
                            "outage_duration_s": scenario.outage_duration_s,
                            "failure_detection_s": scenario.failure_detection_s,
                            "policy": policy, "completed_chain": int(result.success),
                            "completed_operations": result.completed_operations,
                            "finish_s": result.finish_s, "observed_stop_s": result.elapsed_s,
                            "restricted_completion_s": result.restricted_completion_s(scenario.deadline_s),
                            "attempts_started": len(result.attempts),
                            "failed_attempts": result.failed_attempts,
                            "transmitted_bytes": result.transmitted_bytes,
                            "policy_wait_s": result.policy_wait_s,
                            "backoff_wait_s": result.backoff_wait_s,
                            "failure_reason": result.failure_reason or "",
                        })
                        accumulators[scenario.regime, policy].add(result, scenario.deadline_s)
                        if scenario.regime == "restart_on_outage":
                            by_detection[scenario.detection_delay_ratio, policy].add(result, scenario.deadline_s)
                    for baseline in ("asap", "ideal_reactive"):
                        pairs[scenario.regime, baseline].add(oracle, results[baseline], scenario.deadline_s)
                    if scenario.regime == "restart_on_outage":
                        detection_pairs[scenario.detection_delay_ratio].add(
                            oracle, results["ideal_reactive"], scenario.deadline_s)
                    if scenario.regime == "progress_control":
                        immediate = results["asap"].restricted_completion_s(scenario.deadline_s)
                        for result in results.values():
                            fifo_violations += int(
                                result.restricted_completion_s(scenario.deadline_s) < immediate - 1e-8)

    aggregate = {}
    for (regime, policy), accumulator in sorted(accumulators.items()):
        aggregate.setdefault(regime, {})[policy] = accumulator.summary()
    paired = {}
    for (regime, baseline), values in sorted(pairs.items()):
        paired.setdefault(regime, {})[f"oracle_vs_{baseline}"] = values.summary()
    detection = {}
    for ratio in config.detection_delay_ratios:
        detection[str(ratio)] = {
            "oracle_vs_ideal_reactive": detection_pairs[ratio].summary(),
            "policies": {policy: accumulator.summary()
                         for (value, policy), accumulator in sorted(by_detection.items())
                         if value == ratio},
        }
    summary = {
        "schema_version": 1, "study_kind": configuration["study_kind"],
        "interpretation": "Synthetic upper-bound and sensitivity results; not measured LEO or live-agent performance.",
        "seed": config.seed, "scenario_counts": dict(scenario_counts),
        "total_scenarios": sum(scenario_counts.values()), "policy_runs": row_count,
        "negative_control_violations": fifo_violations,
        "aggregate": aggregate, "paired_comparisons": paired,
        "restart_breakdown_by_detection_delay_ratio": detection,
    }
    _write_json(output / "summary.json", summary)
    summary_fields = ["regime", "policy", *next(iter(accumulators.values())).summary()]
    with (output / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
        writer.writeheader()
        for regime, policies in sorted(aggregate.items()):
            for policy, values in sorted(policies.items()):
                writer.writerow({"regime": regime, "policy": policy, **values})

    progress = paired["progress_control"]["oracle_vs_asap"]
    stable = paired["stable_control"]["oracle_vs_ideal_reactive"]
    fault = paired["restart_on_outage"]["oracle_vs_ideal_reactive"]
    lines = [
        "# Synthetic timing-headroom results", "",
        "These are virtual-time model outputs, not terminal measurements, live-browser trials, or LLM evaluations.",
        "The perfect-future policy is an upper bound. The equal-weight sweep is not a deployment effect estimate.", "",
        f"Seed: `{config.seed}`. Paired scenarios: **{summary['total_scenarios']:,}**. Policy runs: **{row_count:,}**.",
        f"FIFO progress-control violations: **{fifo_violations}**.", "",
        "| Regime | Paired scenarios | Oracle time reduction vs ideal reactive | Completion-rate difference |",
        "|---|---:|---:|---:|",
    ]
    for regime in ("stable_control", "progress_control", "restart_on_outage"):
        value = paired[regime]["oracle_vs_ideal_reactive"]
        lines.append(f"| {regime} | {value['paired_scenarios']:,} | "
                     f"{value['aggregate_restricted_time_reduction_fraction']:.2%} | "
                     f"{value['chain_completion_rate_difference_pp']:.2f} percentage points |")
    lines += ["", "## Mechanism boundary", "",
              "The FIFO progress-preserving model has zero timing headroom relative to immediate dispatch. "
              "The deliberately delayed control also produces no faster result. "
              "In the restart model, an outage invalidates the whole RPC, including remote-compute waits. "
              "Any positive admission headroom is conditional on this extra assumption and the chosen failure-detection delay.",
              "", "| Failure-detection delay / outage duration | Scenarios | Oracle lower restricted time | Ties | Time reduction vs ideal reactive |",
              "|---|---:|---:|---:|---:|"]
    for ratio in config.detection_delay_ratios:
        value = detection[str(ratio)]["oracle_vs_ideal_reactive"]
        lines.append(f"| {ratio:g} | {value['paired_scenarios']:,} | "
                     f"{value['oracle_lower_restricted_time']:,} | {value['equal_restricted_time']:,} | "
                     f"{value['aggregate_restricted_time_reduction_fraction']:.2%} |")
    lines += ["", "## Files", "",
              "- `configuration.json`: every sweep parameter, workload operation, unit, and model assumption.",
              "- `runs.csv.gz`: every policy/scenario outcome, including failures, waiting, bytes, and completed operation counts.",
              "- `summary.json` / `summary.csv`: all aggregates and paired comparisons.",
              "- `manifest.json`: hashes of data and generating source files plus the execution environment.", "",
              "Real Starlink traces, empirical timeout semantics, a causal forecast, a local browser/agent integration, "
              "and operator-reviewed task correctness are required before making a real-world performance claim.", ""]
    (output / "README.md").write_text("\n".join(lines))
    artifact_names = ("configuration.json", "runs.csv.gz", "summary.json", "summary.csv", "README.md")
    source_names = ("scheduling.py", "synthetic_study.py")
    manifest = {
        "schema_version": 1,
        "data_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                        for name in artifact_names},
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in source_names},
        "environment": {"python": sys.version, "platform": platform.platform()},
        "reproduce": "python -m leo_agent_study.synthetic_study --output results/synthetic",
    }
    _write_json(output / "manifest.json", manifest)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/synthetic"))
    args = parser.parse_args(argv)
    summary = run_study(args.output)
    print(json.dumps({key: summary[key] for key in
                      ("study_kind", "seed", "scenario_counts", "total_scenarios",
                       "policy_runs", "negative_control_violations")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
