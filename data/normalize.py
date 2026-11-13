#!/usr/bin/env python3
"""Verify and normalize the pinned, CC-BY-4.0 US Starlink measurement release.

No rows are resampled, interpolated, dropped, or converted to packet-loss labels.
Run: python3 data/normalize.py --archive /tmp/hawaii_road_test_202408.processed.tar.gz
or:  python3 data/normalize.py --download --archive /tmp/hawaii_road_test_202408.processed.tar.gz
"""

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile
import urllib.request

REPOSITORY = "NUWiNS/sigmetrics26-exploring-the-5g-digital-divide-in-the-non-contiguous-us-leo-satellites-to-the-rescue"
COMMIT = "b5f330d508e08e8e1fcd2300529a45f1bbb3231d"
ARCHIVE_NAME = "hawaii_road_test_202408.processed.tar.gz"
ARCHIVE_SHA256 = "1244e57095b057d460e2cf986f5cec6d85ba40b52d41874fa438e2711edba013"
ARCHIVE_BYTES = 20882185
ARCHIVE_URL = f"https://media.githubusercontent.com/media/{REPOSITORY}/{COMMIT}/datasets/{ARCHIVE_NAME}"
PING_MEMBER = "hawaii_road_test_202408/processed/ping/starlink_ping.csv"
TELEMETRY_MEMBER = "hawaii_road_test_202408/processed/starlink/starlink_metric.app_tput_filtered.csv"
SOURCE_BASE = f"https://github.com/{REPOSITORY}/blob/{COMMIT}"
AUTHORS = "Sizhe Wang, Moinak Ghoshal, Yufei Feng, Imran Khan, Phuc Dinh, Omar Basit, Zhekun Yu, Y. Charlie Hu, Dimitrios Koutsonikolas"


def epoch(value):
    timestamp = dt.datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError(f"Timezone missing: {value}")
    return timestamp.timestamp()


def number(value):
    return f"{value:.6f}"


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def percentile(values, quantile):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * quantile)] if ordered else None


def quality(rows, latency_column, source_epoch_divisor):
    timestamps = [epoch(row["local_dt"]) for row in rows]
    differences = [b - a for a, b in zip(timestamps, timestamps[1:])]
    valid = [float(row[latency_column]) for row in rows
             if row[latency_column] and math.isfinite(float(row[latency_column]))]
    result = {
        "rows": len(rows),
        "timestamp_start_utc": dt.datetime.fromtimestamp(min(timestamps), dt.timezone.utc).isoformat(),
        "timestamp_end_utc": dt.datetime.fromtimestamp(max(timestamps), dt.timezone.utc).isoformat(),
        "local_day_counts": dict(sorted(collections.Counter(row["local_dt"][:10] for row in rows).items())),
        "duplicate_timestamps": len(timestamps) - len(set(timestamps)),
        "negative_intervals": sum(value < 0 for value in differences),
        "missing_latency_rows": sum(not row[latency_column] for row in rows),
        "nonfinite_latency_rows": sum(bool(row[latency_column]) and not math.isfinite(float(row[latency_column])) for row in rows),
        "interval_seconds_quantiles_nearest_order_statistic": {str(q): percentile(differences, q) for q in [0, .01, .25, .5, .75, .95, .99, 1]},
        "latency_ms_quantiles_nearest_order_statistic": {str(q): percentile(valid, q) for q in [0, .01, .25, .5, .75, .95, .99, 1]},
        "gaps_gt_2s": sum(value > 2 for value in differences),
        "gaps_gt_5s": sum(value > 5 for value in differences),
        "gaps_gt_60s": sum(value > 60 for value in differences),
        "sum_intervals_at_most_2s": sum(value for value in differences if 0 < value <= 2),
        "source_utc_ts_minus_offset_aware_time_s_min": min(float(row["utc_ts"]) / source_epoch_divisor - timestamp for row, timestamp in zip(rows, timestamps)),
        "source_utc_ts_minus_offset_aware_time_s_max": max(float(row["utc_ts"]) / source_epoch_divisor - timestamp for row, timestamp in zip(rows, timestamps)),
    }
    if latency_column == "latency_ms":
        result["outage_cause_row_counts_not_outage_durations"] = dict(sorted(collections.Counter(row["outage_cause"] or "EMPTY" for row in rows).items()))
        result["unique_source_segment_ids"] = len({row["segment_id"] for row in rows})
    return result


def read_member(archive, member):
    return list(csv.DictReader(io.TextIOWrapper(archive.extractfile(member), encoding="utf-8", newline="")))


def write_csv(stream, fields, rows):
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Download the pinned public archive if absent.")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    if not args.archive.exists() and args.download:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ARCHIVE_URL, args.archive)
    if args.archive.stat().st_size != ARCHIVE_BYTES or sha256(args.archive) != ARCHIVE_SHA256:
        raise SystemExit("Archive size/hash mismatch; refusing to normalize.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.archive, "r:gz") as archive:
        ping = read_member(archive, PING_MEMBER)
        telemetry = read_member(archive, TELEMETRY_MEMBER)

    ping_name = "hawaii_starlink_ping.csv"
    ping_fields = ["timestamp_s", "rtt_ms", "operator", "location", "source_session", "source_row", "local_dt", "source_utc_ts", "weather", "area"]
    with (args.output_dir / ping_name).open("w", encoding="utf-8", newline="") as stream:
        write_csv(stream, ping_fields, ({
            "timestamp_s": number(epoch(row["local_dt"])), "rtt_ms": row["rtt_ms"],
            "operator": row["operator"], "location": "Maui_Hawaii_US",
            "source_session": "hawaii_road_test_202408", "source_row": index,
            "local_dt": row["local_dt"], "source_utc_ts": row["utc_ts"],
            "weather": row["weather"], "area": row["area"],
        } for index, row in enumerate(ping, 1)))

    telemetry_name = "hawaii_starlink_terminal.csv.gz"
    # Retain all source fields except redundant request/response strings (their
    # exact offset-aware epoch equivalents are retained to microsecond precision).
    preserved = [key for key in telemetry[0] if key not in {"req_time", "res_time", "utc_ts"}]
    telemetry_fields = ["timestamp_s", "request_timestamp_s", "response_timestamp_s", "source_row", "source_utc_ts", *preserved]
    with (args.output_dir / telemetry_name).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as stream:
                write_csv(stream, telemetry_fields, ({
                    "timestamp_s": number(epoch(row["local_dt"])),
                    "request_timestamp_s": number(epoch(row["req_time"])),
                    "response_timestamp_s": number(epoch(row["res_time"])),
                    "source_row": index, "source_utc_ts": row["utc_ts"],
                    **{key: row[key] for key in preserved},
                } for index, row in enumerate(telemetry, 1)))

    provenance = {
        "dataset": "Exploring the 5G Digital Divide in the Non-Contiguous US: LEO Satellites to the Rescue? — Maui, Hawaii road test, August 2024",
        "authors": AUTHORS, "paper_doi": "10.1145/3771568",
        "repository_url": f"https://github.com/{REPOSITORY}", "upstream_commit": COMMIT,
        "archive_url": ARCHIVE_URL, "archive_sha256": ARCHIVE_SHA256, "archive_bytes": ARCHIVE_BYTES,
        "archive_members": {"ping": PING_MEMBER, "terminal": TELEMETRY_MEMBER},
        "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "upstream_license_url": f"{SOURCE_BASE}/LICENSE-DATA",
        "upstream_documentation_url": f"{SOURCE_BASE}/README.md",
        "copyright_notice": f"Copyright (c) 2024-2026 {AUTHORS}",
        "warranty_notice": "Supplied as-is and as-available, without warranties; see LICENSE-CC-BY-4.0.txt.",
        "normalization": {
            "timestamp_s": "Unix UTC seconds derived from offset-aware source local_dt, retaining microseconds.",
            "ping_timestamp_semantics": "Unknown whether source time labels probe send or reply. Conservatively make a finite RTT sample usable at timestamp_s + rtt_ms/1000. Absolute local_dt is trusted over inconsistent source utc_ts; cross-stream clock synchronization is not independently validated.",
            "terminal_timestamp_semantics": "Source local_dt equals response time in inspected rows; canonical timestamp is parsed local_dt. Explicit gRPC request and response times are retained. Terminal latency_ms is a vendor-reported metric, not ICMP RTT or an application request service time.",
            "timestamp_quality_warning": "Every ping source utc_ts is exactly 36000 seconds earlier than offset-aware local_dt; terminal source utc_ts is milliseconds, truncated to integer milliseconds. source_utc_ts is preserved unmodified in both outputs.",
            "rows": "All rows retained in original order. No interpolation, resampling, artificial loss rows, or imputation. source_row is 1-based original CSV data-row number.",
            "source_session": "Constant campaign identifier; not an uninterrupted run. Split at gaps before time-series prediction.",
            "throughput": "Terminal tput_dl_bps and tput_ul_bps are measured achieved traffic rates, retained only as raw context; they do not estimate available service capacity.",
            "outages": "Outage fields are retained as source telemetry. Repeated event fields are not independently verified current-state labels or packet-loss indicators.",
            "compression": "Terminal CSV is gzip compressed with mtime=0 for deterministic output.",
        },
        "limitations": [
            "Measurements are from mobile Maui drive tests, not disaster recovery, Hurricane Helene, North Carolina, or AI agents.",
            "Ping contains only finite successful RTT measurements and has no sequence numbers, sent-probe count, or explicit failed-probe rows. Gaps cannot establish loss or outage duration.",
            "Irregular sample intervals and long collection gaps remain. Do not interpolate across gaps; report temporal hold-out and the gap threshold.",
            "Do not claim satellite-phase causality from timestamp predictability alone; shared load, mobility, route, and collection effects are confounders.",
            "A trace replay or RTT forecast is a preliminary network experiment; it is not measured agent completion performance.",
        ],
        "outputs": {},
        "quality": {
            "ping": quality(ping, "rtt_ms", 1),
            "terminal": quality(telemetry, "latency_ms", 1000),
        },
    }
    for filename in [ping_name, telemetry_name]:
        path = args.output_dir / filename
        provenance["outputs"][filename] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    (args.output_dir / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"outputs": provenance["outputs"], "ping_rows": len(ping), "terminal_rows": len(telemetry)}, indent=2))


if __name__ == "__main__":
    main()
