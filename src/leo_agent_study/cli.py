"""Dependency-free experiment commands. No remote LLM credentials required."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .forecasting import evaluate, load_samples


def run_forecast(data: Path, output: Path, seed: int = 20261113) -> dict:
    samples, quality = load_samples(data)
    report, rows = evaluate(samples, seed=seed)
    report["data"] = {"path": str(data), **quality}
    output.mkdir(parents=True, exist_ok=True)
    (output / "forecast_report.json").write_text(json.dumps(report, indent=2) + "\n")
    with (output / "forecasts.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    forecast = commands.add_parser("forecast", help="Held-out public Starlink RTT forecasting")
    forecast.add_argument("--data", type=Path, default=Path("data/hawaii_starlink_ping.csv"))
    forecast.add_argument("--output", type=Path, default=Path("results/forecast"))
    forecast.add_argument("--seed", type=int, default=20261113)
    probe = commands.add_parser("http-probe", help="Scripted loopback HTTP capability probe")
    probe.add_argument("--output", type=Path, default=Path("results/http_probe"))
    synthetic = commands.add_parser("synthetic", help="Synthetic timing-headroom sensitivity study")
    synthetic.add_argument("--output", type=Path, default=Path("results/synthetic"))
    args = parser.parse_args()
    if args.command == "forecast":
        report = run_forecast(args.data, args.output, args.seed)
        print(json.dumps({"kind": report["kind"], "output": str(args.output),
                          "samples": report["data"]["valid_samples"]}, indent=2))
    elif args.command == "http-probe":
        from .http_probe import run_probe
        run_probe(args.output)
        print(json.dumps({"kind": "scripted_localhost_http", "output": str(args.output)}))
    else:
        from .synthetic_study import run_study
        run_study(args.output)
        print(json.dumps({"kind": "synthetic_scheduling", "output": str(args.output)}))


if __name__ == "__main__":
    main()
