# LEO Agent Study

A reproducible preliminary study for reliable, timely completion of agent tasks
over low-Earth-orbit (LEO) Internet. The research question is whether a causal
forecast of link conditions can improve a task's chance of finishing correctly
before its deadline, after accounting for the cost of waiting, retries and work
already in progress.

This repository separates measured network evidence, an implemented software
capability and synthetic mechanism tests. It does **not** demonstrate improved
performance of a real browser agent or LLM over Starlink. It contains no field
experiment in a disaster-recovery hub. The proposed North Carolina recovery-hub
setting motivates future validation; no operator partnership or access is
established here.

## Run the study

Python **3.11 or later** is sufficient. All study commands and tests use the Python
standard library; no API key, LLM account, browser installation, Starlink terminal
or package installation is required. Run from the repository root:

```sh
git clone https://github.com/ketanbj/leo-agent-study.git
cd leo-agent-study

PYTHONPATH=src python3 -m leo_agent_study forecast
PYTHONPATH=src python3 -m leo_agent_study http-probe
PYTHONPATH=src python3 -m leo_agent_study synthetic
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The forecast uses the committed normalized public trace. The HTTP probe starts
and stops its own localhost fixture server; it makes no external service calls.
The synthetic study runs in virtual time. Results are written under `results/`;
the HTTP probe's wall-clock times vary across machines and runs.

To re-download and normalize the original public archive, keep it outside the
repository and verify its pinned hash:

```sh
python3 data/normalize.py --download --archive /tmp/leo-agent-study-data/hawaii_road_test_202408.processed.tar.gz
```

This optional command downloads approximately 21 MB. The normalizer refuses an
archive with the wrong size or SHA256. See [data documentation](data/README.md)
and [provenance](data/provenance.json) for source URLs, licensing, timestamp
semantics and exact transformations. See `--help` for the study commands' options.

## What the artifacts establish

| Evidence tier | Implemented artifact | Supported interpretation |
| --- | --- | --- |
| Measured public network data | Causal, chronologically held-out ICMP RTT forecasts on a historical Maui Starlink drive-test trace | A retrospective comparison of RTT predictors on the eligible observed samples |
| Measured software capability | Scripted localhost HTTP/JSON workflow with dispatch control, a deliberate transient failure, retries and retained completed reads | The probe exposes operation boundaries and preserve completed read results in memory |
| Synthetic mechanism study | Explicit request/response work, time-varying service, deadlines and separately labeled failure assumptions | Conditional timing headroom and controls under the model's stated assumptions |

The public trace contains **6,815 successful ping observations** from August
16–19, 2024 in Maui, Hawaii. Its median interval is approximately **204 ms**, but
long collection gaps remain; it is not a continuous four-day recording. There are
no failed-probe rows or sequence numbers, so gaps cannot identify packet loss.
The accompanying **53,044 terminal-telemetry rows** are included with provenance,
but terminal-reported latency is distinct from application RTT. Measured achieved
throughput does not establish available link capacity.

The release's ping `utc_ts` disagrees with offset-aware `local_dt` by exactly ten
hours. Normalization consistently uses `local_dt`, preserves the source numeric
timestamp and records the discrepancy. Because ping send-versus-reply timestamp
semantics are uncertain, a forecast cannot use an observation until its recorded
time plus its measured RTT.

## Preliminary results

The checked-in run completes all three experiments. The [full results](results/README.md) report every forecast horizon and baseline, coverage, and the conditional synthetic mechanism.

| Study | Executed result | Interpretation |
| --- | --- | --- |
| Held-out RTT forecasting | At nominal 5 s, selected phase MAE **20.189 ms** versus recent mean **20.092 ms**, on **1,105 / 1,363** eligible test origins | The validation-selected phase model supplies no demonstrated added value; all horizons/candidates remain reported |
| Localhost HTTP capability | Both policies produce identical synthetic briefs in **5 HTTP requests**, retain the completed first read during a 503 retry, and send/receive **518 / 1,070 payload bytes** | Executes dispatch/retry instrumentation with deterministic JSON fixtures; no real-agent performance claim |
| Synthetic scheduling | **11,028 paired scenarios / 33,732 policy runs**; **0%** timing gain in FIFO controls; conditional restart oracle **8.13%** lower restricted completion time and **+3.26 pp** completion versus ideal reaction | Equal-weight synthetic sensitivity grid with perfect future knowledge; **8,192 / 10,368** restart scenarios tie, and gains depend on detection/retry assumptions |

Detailed outputs: [forecast JSON](results/forecast/forecast_report.json), [HTTP summary](results/http_probe/summary.json), [synthetic results](results/synthetic/README.md). The executed test suite passes **31 tests** (26 study checks and 5 artifact-comparison checks). GitHub Actions reruns tests and compares all regenerated numerical artifacts with a 1e-9 absolute float tolerance (zero relative tolerance); structures, counts, labels and model selections match exactly.
Model selection uses validation data. A static training-median baseline can beat
adaptive predictors on validation, while the recent-mean comparator performs
better on the held-out test. The validation-selected phase candidates do not beat that
recent-mean test comparator, so this study does not establish **added value from
phase prediction**. Retain this negative result and the complete comparison;
selecting a favorable baseline or horizon after inspecting the test would change
the research question.

The progress-preserving FIFO model is a negative control: starting the same
serial work as soon as possible cannot finish later than deferring it. A
perfect-future oracle can have headroom under a separate restart-on-outage
assumption that discards attempt progress. Such headroom is conditional on that
assumption and future knowledge; it is neither an implementable causal policy
nor measured Starlink, browser or LLM behavior.

## Scope and next steps

The current forecast uses empirical phase and recent-RTT baselines. It does not
integrate the parent research project's route/orbital predictor. The HTTP probe
uses a deterministic JSON service and synthetic public-information fixtures; it
has no LLM reasoning, browser automation, durable checkpoint restoration or
predictive-performance comparison. The parent research project plans to deploy Starlink measurement terminals. No project-operated connection or project-recorded trace is available to this initial study; [issue #1](https://github.com/ketanbj/leo-agent-study/issues/1) connects the collection protocol to that planned deployment.

The [methodology](docs/methodology.md) defines the causal evaluation, outputs and
limits. The [roadmap](docs/roadmap.md) and [eight open GitHub issues](https://github.com/ketanbj/leo-agent-study/issues) specify
the next experiments and integrations: continuous measured US traces, the actual
parent predictor, a real local-browser agent, remote LLM JSON/stream timing,
transport-realistic emulation, operator-reviewed tasks and multi-site validation.
These are explicitly marked as unimplemented. Faster execution counts as success
only when the output is correct and meets the task deadline.

Artifact version: [v0.1.1](https://github.com/ketanbj/leo-agent-study/tree/v0.1.1). The [reproduction manifest](results/reproducibility.json) records commands, environment, verification and SHA256 hashes. [CITATION.cff](CITATION.cff) supplies versioned citation metadata.

## Attribution and licenses

Original study code is licensed under the repository's **MIT license**. The
public measurements and normalized extracts have a separate **CC BY 4.0** license;
the MIT code license does not replace the data license.

The data are from Sizhe Wang, Moinak Ghoshal, Yufei Feng, Imran Khan, Phuc Dinh,
Omar Basit, Zhekun Yu, Y. Charlie Hu and Dimitrios Koutsonikolas,
[*Exploring the 5G Digital Divide in the Non-Contiguous US: LEO Satellites to the Rescue?*](https://doi.org/10.1145/3771568),
released through the [NUWiNS artifact](https://github.com/NUWiNS/sigmetrics26-exploring-the-5g-digital-divide-in-the-non-contiguous-us-leo-satellites-to-the-rescue).
The pinned upstream commit, creator/copyright notices, changes and as-is warranty
notice are retained in [data/README.md](data/README.md),
[provenance.json](data/provenance.json) and the
[verbatim data license](data/LICENSE-CC-BY-4.0.txt). Upstream creators do not endorse
this study.
