# Measured US Starlink traces

These are normalized extracts of the Maui, Hawaii road-test release accompanying
[Wang et al., *Exploring the 5G Digital Divide in the Non-Contiguous US: LEO Satellites to the Rescue?*](https://doi.org/10.1145/3771568).
The primary source is the [NUWiNS artifact](https://github.com/NUWiNS/sigmetrics26-exploring-the-5g-digital-divide-in-the-non-contiguous-us-leo-satellites-to-the-rescue),
pinned to commit `b5f330d508e08e8e1fcd2300529a45f1bbb3231d`.
The measurements come from mobile drive tests in August 2024; they are not
measurements of disaster hubs, Hurricane Helene, North Carolina, or AI agents.

## Files

| File | Contents | Rows |
| --- | --- | ---: |
| `hawaii_starlink_ping.csv` | Complete released Starlink ICMP RTT trace, normalized timestamps and original labels | 6,815 |
| `hawaii_starlink_terminal.csv.gz` | Complete released Starlink terminal telemetry; compressed CSV | 53,044 |
| `provenance.json` | URLs, upstream commit, archive and extract SHA256 hashes, transformations, quality statistics and limitations | — |
| `normalize.py` | Standard-library downloader, archive verifier and deterministic normalizer | — |
| `LICENSE-CC-BY-4.0.txt` | Verbatim upstream data license and creator/copyright notices | — |

The ping CSV begins with `timestamp_s,rtt_ms`. `timestamp_s` is Unix UTC seconds
parsed from the **offset-aware `local_dt` field**, preserving microseconds.
The exact source `utc_ts` remains in `source_utc_ts`. `source_row` is the original
CSV data-row number, starting at one. `source_session` identifies the campaign;
it does **not** imply a continuous measurement run.

Terminal telemetry has `timestamp_s`, gRPC `request_timestamp_s` and
`response_timestamp_s`, `source_row`, `source_utc_ts`, and all original remaining
fields, including reported `latency_ms`, obstruction and outage context.
The terminal latency metric is distinct from the ping RTT and from an application
request's service time. Terminal `tput_dl_bps`/`tput_ul_bps` are achieved traffic
rates retained for context; they do not establish available service capacity.

## Reproduce

Python 3.11 or later is sufficient; no packages are required. Keep the 21 MB
original archive outside the repository:

```sh
python3 data/normalize.py --download --archive /tmp/leo-agent-study-data/hawaii_road_test_202408.processed.tar.gz
```

For a previously downloaded archive, omit `--download`. Download URL:

```text
https://media.githubusercontent.com/media/NUWiNS/sigmetrics26-exploring-the-5g-digital-divide-in-the-non-contiguous-us-leo-satellites-to-the-rescue/b5f330d508e08e8e1fcd2300529a45f1bbb3231d/datasets/hawaii_road_test_202408.processed.tar.gz
```

Expected archive size is **20,882,185 bytes**, with SHA256
`1244e57095b057d460e2cf986f5cec6d85ba40b52d41874fa438e2711edba013`.
The normalizer refuses any other archive. It reads only the two named CSV members;
it does not extract or execute upstream code. The downloaded original archive was
downloaded from the default branch, hash checked, and matched against the Git LFS
pointer at the pinned commit.

## Timestamp and missing-data findings

All observations are retained in their original order. No samples are interpolated,
resampled, imputed, or fabricated. Both streams are timestamp ordered, have no
duplicate timestamps and contain finite latency values in every released row.

| Property | ICMP RTT | Terminal telemetry |
| --- | ---: | ---: |
| Local observation dates (Hawaii UTC−10) | Aug 16–19, 2024 | Aug 16–19, 2024 |
| Median interval | 0.203567 s | 0.438538 s |
| 95th percentile interval | 0.247234 s | 0.686763 s |
| Intervals over 2 s | 69 | 278 |
| Intervals over 60 s | 51 | 51 |
| Sum of adjacent positive intervals no greater than 2 s | 1,422.84 s | 24,451.48 s |
| Median latency | 109 ms | 75.50 ms |
| 95th percentile latency | 161 ms | 126.64 ms |

These duration sums describe observed adjacent intervals, not continuous uptime,
experiment duration, or a measured outage rate. The upstream README's nominal
200 ms ping and 500 ms telemetry cadences are approximate; use actual timestamps.

**Timestamp inconsistency:** every ping `utc_ts` is exactly **36,000 seconds earlier**
than the same row's offset-aware `local_dt`. The normalizer uses `local_dt` for both
streams and preserves the original numeric value. Terminal `utc_ts` uses integer
milliseconds and agrees with `local_dt` to millisecond truncation. Cross-stream
clock synchronization has not been independently validated.

**RTT availability:** the release does not establish whether the ping's timestamp
labels probe send or reply. A causal predictor therefore makes a finite RTT
observation available only at `timestamp_s + rtt_ms/1000`. Do not use a sample
before its RTT could be observed.

**Loss is unknown:** the released ping CSV contains no failed-probe rows, sequence
numbers or sent-probe count. Missing intervals cannot identify packet loss or its
duration. Terminal outage fields can repeat events; a nonempty outage cause is not
independently verified to mean the terminal is currently down. Do not convert
either into loss labels without validating upstream collection semantics.

## Evaluation boundaries

Use chronological training and held-out future blocks or leave one local date out.
Reset history at collection gaps and document the gap threshold. Never randomly
split adjacent rows. Avoid overlapping prediction windows across split boundaries;
training targets and preprocessing must use training data only. Score only points
whose future target window is observed; report the resulting coverage.

Recent-history and calendar/phase models can be compared on these data, but a
predictable timestamp pattern alone does not establish satellite-phase causality.
Mobility, route, measurement load and collection behavior are confounders. Results
are a preliminary network trace study. Agent deadlines, task completion, terminal
stationarity and disaster-hub representativeness require separate evaluation.

## Attribution and licensing

Copyright (c) 2024–2026 Sizhe Wang, Moinak Ghoshal, Yufei Feng, Imran Khan,
Phuc Dinh, Omar Basit, Zhekun Yu, Y. Charlie Hu, and Dimitrios Koutsonikolas.
The original data and these normalized extracts are licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), supplied as-is and
as-available without warranties; see `LICENSE-CC-BY-4.0.txt`.
Modifications here consist of timestamp normalization, column selection/naming,
row identifiers, metadata and lossless compression, as documented above. Upstream
authors and organizations do not endorse this study.

```bibtex
@article{wang2025noncontiguous,
  author = {Wang, Sizhe and Ghoshal, Moinak and Feng, Yufei and Khan, Imran and Dinh, Phuc and Basit, Omar and Yu, Zhekun and Hu, Y. Charlie and Koutsonikolas, Dimitrios},
  title = {Exploring the 5G Digital Divide in the Non-Contiguous US: LEO Satellites to the Rescue?},
  year = {2025},
  journal = {Proceedings of the ACM on Measurement and Analysis of Computing Systems},
  doi = {10.1145/3771568}
}
```
