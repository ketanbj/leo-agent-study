# Research and integration roadmap

The current repository supports three bounded activities: a causal RTT-forecast
comparison on a historical public Starlink trace, a synthetic scheduling model
with explicit transport/failure assumptions, and a scripted localhost HTTP
capability probe. The probe uses synthetic information and deterministic JSON;
it does not run a real browser agent or a remote LLM. Empirical phase forecasting
does not integrate the parent award's orbital/route predictor. Results from these
activities do not establish performance in North Carolina recovery hubs.

The next stage connects measured network behavior to correct, timely completion
of realistic tasks by an agent running a local browser. The table below separates
experiments, requested integrations and requested features. **Every item is not
yet implemented.** The machine-readable issue specifications, including full acceptance
criteria, are in [issues.json](issues.json). Descriptive dependency identifiers
remain stable alongside the published GitHub issue links below.

| Identifier | Type | Priority | Deliverable | Dependencies |
| --- | --- | --- | --- | --- |
| `current-us-starlink-traces` | Experiment | P0 | Continuous current US traces with explicit loss, timing, collection-gap and data-rights semantics | None |
| `parent-award-predictor` | Integration request | P0 | Actual route/RTT predictor adapter and held-out comparison against phase/recent-history baselines | Current US traces |
| `measured-network-emulation` | Experiment | P0 | Time-varying packet/transport replay that affects in-flight requests, plus negative controls | Current US traces |
| `validated-recovery-tasks` | Experiment | P0 | Versioned, source-backed recovery-information tasks and independent correctness criteria; operator review if obtained | None |
| `local-browser-agent` | Integration request | P0 | A real agent controlling a browser on the local side of the LEO link, with operation-level event logs | Validated tasks; measured network emulation |
| `llm-json-streaming` | Integration request | P0 | Actual remote structured-output and streaming API instrumentation | Measured network emulation |
| `durable-task-state` | Feature request | P1 | Persisted evidence and verified restoration after process/network interruption | Local browser agent; remote LLM instrumentation; validated tasks |
| `continuous-multisite-validation` | Experiment | P1 | Future-session and multi-site validation with task correctness, deadlines and failure denominators | Current traces; parent predictor; browser agent; LLM instrumentation; validated tasks |

P0 items establish whether the proposed mechanism exists under realistic
conditions. P1 items test recovery and generalization after the initial adapters
and measurement path work. This ordering is a dependency plan, not a claim of
available partners, sites, equipment or implementation dates.

## Evidence required before stronger claims

The parent research project plans to deploy Starlink measurement terminals. That deployment supplies a prospective measurement path; the initial study has no project-operated Starlink connection or project-recorded traces. Issue #1 connects the collection protocol to this planned resource.

Current traces must record the distinction between a failed probe and a stopped
logger. Successful-only public ping gaps do not measure loss, and achieved
throughput does not establish available capacity. Forecasts need issuance times
and causal availability; orbital/route information needs an actual integration
and an ablation before it can support a claim beyond empirical predictability.

Transport experiments must preserve request progress as conditions change.
Assigning a whole operation the latency observed at dispatch can manufacture
benefits from waiting. The existing synthetic FIFO negative control remains part
of validation; results that show no gain are retained. Loss, reconnection, stream
restart and checkpoint assumptions require observation or explicit sensitivity
analysis.

A useful task result is both correct and completed within its deadline. Network
forecast error, oracle timing headroom, measured agent completion, correctness,
policy-induced waiting, retries and abstention are reported separately. A
controlled emulator result and a field measurement remain identifiable in every
artifact. All attempted tasks belong in outcome denominators.

## Operator participation and scope

North Carolina recovery/community hubs are a candidate validation setting. No
organization has committed to access, task definition or a pilot. Any contact
requires separate authorization; these issue drafts initiate no outreach. A
public report of Starlink deployment does not establish recurring agent delays
or willingness to collaborate. The initial task suite is read-only and uses
versioned public information; actual benefits submissions or emergency decisions
are outside it.

Issue acceptance criteria require a clear statement when access, validation or
coverage targets remain unmet. Reports preserve those limitations instead of
substituting synthetic fixtures for field evidence.

## Open GitHub issues

- [#1: Experiment: collect continuous US Starlink traces with explicit loss and timestamp semantics](https://github.com/ketanbj/leo-agent-study/issues/1)
- [#2: Integration request: connect the parent-award route and RTT predictor to causal dispatch control](https://github.com/ketanbj/leo-agent-study/issues/2)
- [#3: Integration request: instrument a real agent operating a local browser across the LEO link](https://github.com/ketanbj/leo-agent-study/issues/3)
- [#4: Integration request: measure real remote LLM JSON and streaming interactions over LEO](https://github.com/ketanbj/leo-agent-study/issues/4)
- [#5: Experiment: replay measured delay and explicit loss with transport-realistic request progress](https://github.com/ketanbj/leo-agent-study/issues/5)
- [#6: Experiment: validate representative recovery-information tasks and correctness criteria with an operator](https://github.com/ketanbj/leo-agent-study/issues/6)
- [#7: Experiment: test continuous-session and multi-location generalization before pilot claims](https://github.com/ketanbj/leo-agent-study/issues/7)
- [#8: Feature request: persist completed evidence and restore a task after interruption](https://github.com/ketanbj/leo-agent-study/issues/8)
