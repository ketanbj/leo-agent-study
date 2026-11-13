# Synthetic timing-headroom results

These are virtual-time model outputs, not terminal measurements, live-browser trials, or LLM evaluations.
The perfect-future policy is an upper bound. The equal-weight sweep is not a deployment effect estimate.

Seed: `20261113`. Paired scenarios: **11,028**. Policy runs: **33,732**.
FIFO progress-control violations: **0**.

| Regime | Paired scenarios | Oracle time reduction vs ideal reactive | Completion-rate difference |
|---|---:|---:|---:|
| stable_control | 12 | 0.00% | 0.00 percentage points |
| progress_control | 648 | 0.00% | 0.00 percentage points |
| restart_on_outage | 10,368 | 8.13% | 3.26 percentage points |

## Mechanism boundary

The FIFO progress-preserving model has zero timing headroom relative to immediate dispatch. The deliberately delayed control also produces no faster result. In the restart model, an outage invalidates the whole RPC, including remote-compute waits. Any positive admission headroom is conditional on this extra assumption and the chosen failure-detection delay.

| Failure-detection delay / outage duration | Scenarios | Oracle lower restricted time | Ties | Time reduction vs ideal reactive |
|---|---:|---:|---:|---:|
| 0 | 2,592 | 124 | 2,468 | 0.30% |
| 0.5 | 2,592 | 280 | 2,312 | 0.45% |
| 1 | 2,592 | 876 | 1,716 | 6.53% |
| 2 | 2,592 | 896 | 1,696 | 21.67% |

## Files

- `configuration.json`: every sweep parameter, workload operation, unit, and model assumption.
- `runs.csv.gz`: every policy/scenario outcome, including failures, waiting, bytes, and completed operation counts.
- `summary.json` / `summary.csv`: all aggregates and paired comparisons.
- `manifest.json`: hashes of data and generating source files plus the execution environment.

Real Starlink traces, empirical timeout semantics, a causal forecast, a local browser/agent integration, and operator-reviewed task correctness are required before making a real-world performance claim.
