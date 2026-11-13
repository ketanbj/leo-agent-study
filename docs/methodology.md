# Methodology and interpretation

This preliminary study asks whether information available before a dispatch
decision can help complete a correct task before its deadline over a changing
LEO link. It distinguishes three forms of evidence: retrospective forecasts on
measured public network data, an executed localhost software-capability probe,
and explicit synthetic scheduling mechanisms. None is a measurement of a real
browser agent or LLM completing recovery tasks over Starlink.

## Reproduction and artifact boundaries

From the repository root, Python 3.11 or later runs the complete standard-library
study without installation or external service credentials:

```sh
PYTHONPATH=src python3 -m leo_agent_study forecast
PYTHONPATH=src python3 -m leo_agent_study http-probe
PYTHONPATH=src python3 -m leo_agent_study synthetic
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The forecast reads the committed ping extract. The probe uses real loopback HTTP
requests to a temporary local fixture server; the synthetic experiment uses
virtual time. The study writes machine-readable artifacts under `results/`.
The HTTP probe's generated timestamp and elapsed durations are measured anew and
are not expected to match byte for byte across runs. Forecast/bootstrap seeds
and synthetic inputs are recorded for reproducibility. Optional plotting tools
are not needed for the numerical results or tests.

Regenerate the normalized public inputs separately:

```sh
python3 data/normalize.py --download --archive /tmp/leo-agent-study-data/hawaii_road_test_202408.processed.tar.gz
```

The archive stays outside the repository. Its exact Git LFS object SHA256 and
size are checked before normalization. The [data README](../data/README.md),
[normalizer](../data/normalize.py) and [provenance](../data/provenance.json) record
the pinned upstream commit, archive members, output hashes, transformations and
quality statistics. A second normalization of the verified archive produces
byte-identical extracts and provenance.

## Tier 1: forecasts on measured public RTT

### Source and timestamp handling

The input is the complete released Starlink ICMP RTT CSV from the Maui, Hawaii
mobile-drive campaign in August 2024. It contains 6,815 finite successful RTT
measurements spread across four local dates. Nominal sampling is 200 ms; the
observed median interval is 203.567 ms. There are 69 intervals longer than two
seconds and 51 longer than 60 seconds. The sum of adjacent positive intervals no
greater than two seconds is approximately 1,422.84 seconds, not four days of
continuous link observation.

Normalization parses the source offset-aware `local_dt` field into UTC Unix
seconds, retaining microseconds. Every original ping `utc_ts` is exactly 36,000
seconds earlier than this parsed timestamp. The original value remains in
`source_utc_ts` and the discrepancy is documented. This is an explicit
normalization choice, not independent verification of the source clock.

The source does not identify whether a ping timestamp labels its send or reply.
An observation with recorded timestamp t and RTT r milliseconds is therefore
made available conservatively at **t + r/1000 seconds**. Predictions and training
use this availability time, not merely the recorded timestamp. Clock
synchronization between independent streams has not been independently verified.

All source observations remain in the normalized data. The forecast loader
accepts strictly increasing timestamps and positive finite RTT targets, reporting
invalid/missing rows if encountered. A gap greater than two seconds starts a new
continuity segment. This is an analysis rule for missing coverage; it does not
identify a new physical session, packet loss or a network outage.

The terminal extract contains 53,044 rows with a median 438.538 ms interval. In
all rows, its `local_dt` equals the gRPC response timestamp. These telemetry data
are preserved for future analysis; their `latency_ms` is a vendor-reported metric
and is not substituted for the ICMP target or an application request service
time. Achieved throughput is not a measurement of available service capacity.

### Splits, candidates and selection

The declared split is chronological by observation count: the first 60% defines
the training boundary, the next 20% provides validation and the last 20% is test.
Because sampling is irregular, this is not a split into equal fractions of
elapsed wall time. Boundary timestamps are retained in the report. The training
profile uses only observations whose **availability time** is no later than the
training cutoff.

The baseline family contains the training median, persistence and the recent
mean. Candidate empirical phase profiles use periods of 5, 10, 15 and 30 seconds
with 0.5-second bins. The profiles are fitted on training data only and remain
frozen during validation and test. An adaptive level correction uses recent
available observations from the current continuity segment. Empty phase bins
fall back to the training median. These are empirical time-of-day/modulo
features; they are not satellite handover labels or an orbital/route predictor.

For each declared horizon (0.5, 1, 2 and 5 seconds), validation MAE selects a
baseline and a phase candidate separately. Neither family is selected using test
error. All declared candidates and horizons remain in the report, so the reader
can compare the selected candidate with strong alternatives rather than only a
favorable selected baseline.

The result is interpreted accordingly: a static baseline can win validation even
when an adaptive recent-mean baseline performs better on test. The validation-selected phase
candidates do not beat the recent-mean test comparator; the study therefore does
not demonstrate added predictive value from phase. A favorable comparison with a
different baseline or horizon is not used to reverse that conclusion.

### Forecast origin, target eligibility and causal history

Origins occur when a recorded observation becomes available. At origin o, the
requested forecast time is o plus the declared horizon. Its target is the first
recorded sample at or after that requested time, provided that it is at most
0.4 seconds late and is in the same continuity segment. The report records both
requested target time and actual measured target time/lead. Phase is evaluated
at the requested target time; the future observed sample's timestamp is not
supplied to the predictor.

The predictor sees only observations available by the origin. Validation origins
whose target timestamps or target availability cross into the test interval are excluded. Persistence means the last received RTT; replies can arrive out of send order. Repeated target use, actual lead ranges, exclusions and continuity-segment counts are reported. No target window spans
a missing-data segment. Missing future coverage is excluded and must be counted
through the eligible sample denominator; excluded intervals are not assumed to
be successful, failed or representative of observed intervals. The current
forecast task estimates RTT conditional on observed eligible samples, not
availability or loss.

Metrics include MAE, RMSE, signed bias and the 90th percentile of absolute error,
along with sample counts. Paired time-block bootstrap summaries compare errors
using 15-, 60- and 120-second occupied blocks within continuity segments. They
are descriptive uncertainty summaries for this trace, not confidence intervals
over independent sites, users or disaster scenarios. Short fragmented coverage,
autocorrelation and model selection limit interpretation.

## Tier 2: measured localhost capability probe

The probe executes a scripted plan/read/read/synthesize workflow over actual
localhost HTTP and JSON. The fixture information, plan and synthesis service are
deterministic and synthetic. One read deliberately returns a transient 503 on
its first attempt. Immediate dispatch and bounded-wait policies use the same
retry budget and in-memory retention of completed read results.

The probe records operation dependencies, readiness/dispatch/completion events,
requested waits, attempts, response status, JSON payload bytes, retained source
identifiers, final output and its hash. An independent server-side request audit
helps verify which operations actually executed. Identical validated outputs and
the absence of duplicate already-completed reads establish these specific
capabilities. Payload-byte counts exclude headers, TLS, TCP and total wire
traffic.

The bounded wait is imposed to exercise dispatch control; it is not selected by
a network predictor. Localhost elapsed time is a measurement of the fixture on
that machine, not evidence that waiting improves completion performance. This
probe has no browser, LLM reasoning, remote inference, Starlink link, provider
queue, token stream, durable checkpoint or crash-recovery test. Retained state
exists only in memory during the process.

## Tier 3: synthetic scheduling mechanism and controls

The simulator represents serial operations as request bytes, remote inference
wait, response bytes and local work. Link service is a finite sequence of
nonnegative byte-rate intervals with fixed propagation. Request and response
progress integrate service across time, including network changes after
dispatch. An entire request does not receive a latency or capacity sampled only
at its dispatch instant. Inference time is an explicit external service cost;
the dispatch controller does not shorten it.

Synthetic rate intervals and failures are not claimed to reconstruct Starlink.
The public trace's measured achieved throughput is not converted into a service
capacity trace. Successful-only ping gaps are not converted into synthetic loss
labels. Parameters, deadlines, retry/detection delays and policy waits remain
explicit in each run's artifacts.

### Progress-preserving FIFO negative control

In the progress-preserving case, bytes already delivered remain delivered and
the same serial task follows the same link-service process. Starting work as
soon as it is ready cannot finish later than deferring that work. Waiting may
tie immediate dispatch when it merely consumes otherwise unusable service; it
cannot improve completion under these assumptions. This negative control is
retained to detect an apparent scheduling benefit produced by an inconsistent
model or dispatch-time sampling artifact.

### Conditional restart-on-outage experiment

A separate, deliberately stronger assumption makes an RPC require uninterrupted
session availability from dispatch through response arrival. A zero-capacity
interval discards the attempt's progress, including an attempt waiting for
remote inference. Explicit detection and retry delays then apply. Real TCP,
browsers, LLM APIs and streaming protocols do not universally behave this way;
the study makes no such assertion.

A policy with perfect knowledge of future intervals may avoid a doomed attempt
under this restart assumption. Any improvement is **conditional oracle
headroom**: an upper-bound-style mechanism illustration that assumes both the
failure behavior and future knowledge. It is not a demonstrated causal forecast
benefit. A deployable policy requires an actual predictor whose inputs are
available before the decision, and whose errors, staleness and waiting costs are
included. Claims about measured transport require the separate emulator and
field work listed in the roadmap.

### Task outcomes

Report correct completion within the deadline, completed operations, attempts,
transmitted bytes, policy waiting, retry waiting and failure reason separately.
An early failed run can have a short observed elapsed time; it does not become a
fast successful task. All attempted tasks belong in the outcome denominator.
The synthetic model does not evaluate semantic correctness of an LLM-generated
answer; that requires real task outputs and an independent rubric.

## Limits, follow-on evidence and licensing

The parent research project plans to deploy Starlink measurement terminals. No project-operated connection or project-recorded trace is available to this initial study; integration with that planned deployment is tracked in issue #1. Integration with the parent
project's route/RTT predictor is future work. Public reports of recovery-hub
connectivity motivate a candidate context; they do not establish recurring agent
delays, operator willingness or partnership. Maui mobile drive tests cannot
establish performance at stationary North Carolina recovery hubs.

The [roadmap](roadmap.md) and [open GitHub issues](https://github.com/ketanbj/leo-agent-study/issues) distinguish the required
experiments, integrations and features: current continuous US measurements with
explicit loss, the actual parent predictor, a real local-browser agent and remote
LLM JSON/stream instrumentation, transport-realistic emulation, task/operator
validation, durable state and held-out multi-site evaluation. Every item is
marked as not yet implemented. Negative results and unmet access/coverage targets
remain part of the evidence.

Original study code uses the repository MIT license. The public measurement data
and normalized extracts remain under CC BY 4.0, with separate creator,
copyright, modification and as-is warranty notices in
[data documentation](../data/README.md),
[provenance](../data/provenance.json) and the
[original data license](../data/LICENSE-CC-BY-4.0.txt). The source is Wang et al.,
[*Exploring the 5G Digital Divide in the Non-Contiguous US: LEO Satellites to the Rescue?*](https://doi.org/10.1145/3771568),
pinned to the upstream commit recorded in provenance. Upstream authors and
operators do not endorse this study.
