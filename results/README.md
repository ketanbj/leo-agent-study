# Executed preliminary results

Run date: November 13, 2026. The inputs, configurations and numerical outputs are committed. These experiments establish a reproducible starting point, not a measured improvement in agent task completion over LEO.

## Public Starlink RTT forecasting

The complete 6,815-row successful-ping extract uses chronological 60/20/20 splitting and a two-second continuity-gap threshold. Only already received observations are available to the predictor. Each selected phase model and selected non-phase baseline is chosen on validation MAE, separately at each nominal horizon.

| Nominal horizon | Test forecast instances / origins | Training median MAE | Last received RTT MAE | Recent mean MAE | Validation-selected phase | Selected phase MAE |
| --- | --- | --- | --- | --- | --- | --- |
| 0.5 s | 1,325 / 1,363 | 21.861 ms | 20.582 ms | 21.893 ms | phase_adaptive_5s | 21.976 ms |
| 1.0 s | 1,304 / 1,363 | 21.612 ms | 21.355 ms | 22.147 ms | phase_adaptive_10s | 22.258 ms |
| 2.0 s | 1,254 / 1,363 | 22.366 ms | 28.530 ms | 21.301 ms | phase_adaptive_10s | 21.437 ms |
| 5.0 s | 1,105 / 1,363 | 24.214 ms | 22.604 ms | 20.092 ms | phase_adaptive_10s | 20.189 ms |

The validation-selected non-phase baseline is the training median at all four horizons. It is not the strongest comparator on every test horizon. The validation-selected phase candidate does not outperform recent mean at any declared test horizon. The complete report also contains the other phase candidates; choosing one based on its test result would be post-hoc selection.

At nominal five seconds, phase MAE is 20.189 ms versus recent-mean MAE 20.092 ms (phase minus recent mean: +0.097 ms). The descriptive 60-second block-bootstrap interval for **MAE reduction** versus recent mean is [-0.235, +0.053] ms. This does not establish incremental phase value. It also does not test the parent project’s route/orbital predictor, which is not yet integrated.

At five seconds, eligibility is 1,105 / 1,363 response origins (81.1%), conditional on a recorded successful future target in the same segment. Actual lead times range from 5.0004 to 5.3907 seconds. There are 1,068 distinct target observations, 10 continuity segments and 11 occupied 60-second blocks; these are not 1,105 independent experiments. Missing coverage is not loss. The historical mobile Maui measurements are not a stationary North Carolina hub deployment.

Artifacts: [complete report](forecast/forecast_report.json), [per-forecast predictions](forecast/forecasts.csv), [provenance](../data/provenance.json).

## Actual localhost HTTP capability

Both immediate dispatch and the bounded-wait probe produce the same validated synthetic brief. Each executes five actual HTTP requests: a JSON plan, two document reads with one deliberately injected 503 and retry, and JSON synthesis. The already successful first document is fetched once. Each run sends 518 request-payload bytes and receives 1,070 response-payload bytes, including the failed attempt. These counts exclude headers and transport overhead.

The bounded-wait run requests 50 ms total policy delay to exercise dispatch control. This is a capability test, not a prediction policy or performance improvement. Wall-clock timings are machine-dependent and retained in the raw artifact. The service supplies deterministic fixtures: no real model, browser or satellite link is involved, and retained state is memory-only.

Artifacts: [summary and independent server audit](http_probe/summary.json), [event log](http_probe/events.jsonl).

## Synthetic timing headroom

The complete sweep contains **11,028 paired scenarios / 33,732 policy runs**, with all inputs and outcomes in the [synthetic artifact](synthetic/README.md). There are 648 progress-preserving controls, 12 stable controls, and 10,368 restart-on-outage scenarios. Controls have zero timing gain and zero invariant violations.

In the stronger synthetic restart model, perfect-future admission lowers aggregate deadline-restricted completion time by **8.13%** versus ideal reactive control (20.785 to 19.095 seconds) and raises chain completion from **75.75% to 79.01%**. **8,192 / 10,368** scenarios tie. At detection-delay/outage-duration ratios 0, 0.5, 1 and 2, time reductions are respectively **0.30%, 0.45%, 6.53% and 21.67%**. This sensitivity exposes the assumed failure costs as a major determinant of headroom.

The grid equally weights chosen settings; these averages do not estimate a population effect. Restart invalidates the whole RPC even during inference, which is deliberately stronger than progress-preserving transport and is not established for Starlink, a browser or an LLM provider. The ideal reactive policy has instantaneous free current-state observation; the oracle has perfect future knowledge. Neither experiment establishes benefit from the empirical phase model or the unintegrated parent predictor.

## Reproduction

Run the three module commands in the [README](../README.md). Forecast outputs are deterministic for the committed input and seed 20261113. Synthetic outputs are deterministic for their declared parameter grid. Local HTTP timestamps and elapsed times vary. Source-data hashes and normalization are documented separately; the original archive is pinned by hash and commit.
