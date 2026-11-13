"""Measured localhost capability probe for a network-operation adapter.

This is a SCRIPTED workflow with synthetic public-information fixtures and a
deterministic JSON service. It is not an LLM evaluation, browser automation,
Starlink measurement, or demonstration of predictive-performance improvement.
The real HTTP exchanges establish dispatch control, retry accounting, dependency
recording, and in-memory preservation of completed read results across a failed
operation. It does not test crash recovery or durable checkpoint restoration.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


SCHEMA_VERSION = 1
TASK_ID = "synthetic-recovery-brief"
FIXTURES: dict[str, dict[str, Any]] = {
    "resources": {
        "source_id": "fixture-resources",
        "source_uri": "fixture://example-county/resources",
        "synthetic": True,
        "county": "Example County (synthetic)",
        "provider": "Example Recovery Information Desk (synthetic)",
        "applicable_date": "2026-01-01 (synthetic)",
    },
    "requirements": {
        "source_id": "fixture-requirements",
        "source_uri": "fixture://example-county/requirements",
        "synthetic": True,
        "documents": [
            "Photo identification (fixture only)",
            "Proof of address (fixture only)",
        ],
    },
}
EXPECTED_BRIEF: dict[str, Any] = {
    "synthetic": True,
    "county": FIXTURES["resources"]["county"],
    "provider": FIXTURES["resources"]["provider"],
    "applicable_date": FIXTURES["resources"]["applicable_date"],
    "documents": FIXTURES["requirements"]["documents"],
    "sources": [FIXTURES[k]["source_uri"] for k in ("resources", "requirements")],
    "unresolved_items": [],
    "notice": "Synthetic exercise output; not disaster assistance guidance.",
}


def _encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


@contextmanager
def _fixture_server(inject_transient_failure: bool):
    """Serve real loopback HTTP and retain an independent request audit."""
    audit: list[dict[str, Any]] = []
    visits: Counter[str] = Counter()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            pass

        def _handle(self) -> None:
            request_data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with lock:
                visits[self.path] += 1
                visit = visits[self.path]
            status = 200
            if self.command == "POST" and self.path == "/model/plan":
                response: Any = {
                    "synthetic_model": True,
                    "operations": [
                        {"operation_id": "resources", "path": "/fixtures/resources"},
                        {"operation_id": "requirements", "path": "/fixtures/requirements"},
                    ],
                }
            elif self.command == "GET" and self.path.startswith("/fixtures/"):
                name = self.path.rsplit("/", 1)[-1]
                if name == "requirements" and inject_transient_failure and visit == 1:
                    status, response = 503, {"error": "deliberate synthetic transient failure"}
                elif name in FIXTURES:
                    response = FIXTURES[name]
                else:
                    status, response = 404, {"error": "unknown synthetic fixture"}
            elif self.command == "POST" and self.path == "/model/synthesize":
                try:
                    payload = json.loads(request_data)
                    valid = payload["documents"] == [FIXTURES[k] for k in ("resources", "requirements")]
                except (ValueError, TypeError, KeyError):
                    valid = False
                if valid:
                    response = EXPECTED_BRIEF
                else:
                    status, response = 400, {"error": "required fixture evidence missing"}
            else:
                status, response = 404, {"error": "unsupported synthetic endpoint"}
            body = _encode(response)
            with lock:
                audit.append({
                    "method": self.command,
                    "path": self.path,
                    "status": status,
                    "request_payload_bytes": len(request_data),
                    "response_payload_bytes": len(body),
                })
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        do_GET = _handle
        do_POST = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", audit
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class _OperationFailure(Exception):
    pass


def _run_workflow(
    policy: str,
    policy_wait_seconds: float,
    retry_backoff_seconds: float,
    max_attempts: int,
    inject_transient_failure: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    started = time.perf_counter()
    request_counter = 0
    checkpoint: dict[str, tuple[dict[str, Any], str]] = {}
    counts: Counter[str] = Counter()
    # This capability probe is strictly loopback even on machines with an HTTP proxy.
    opener = build_opener(ProxyHandler({}))

    def emit(event: str, **fields: Any) -> None:
        events.append({
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "policy": policy,
            "event": event,
            "elapsed_seconds": time.perf_counter() - started,
            "synthetic_workflow": True,
            **fields,
        })

    def wait(seconds: float, kind: str, operation_id: str) -> None:
        if seconds <= 0:
            return
        before = time.perf_counter()
        emit("wait_start", operation_id=operation_id, wait_kind=kind, requested_seconds=seconds)
        time.sleep(seconds)
        emit("wait_end", operation_id=operation_id, wait_kind=kind,
             requested_seconds=seconds, measured_seconds=time.perf_counter() - before)

    emit("task_start")
    brief = None
    error = None
    with _fixture_server(inject_transient_failure) as (base_url, server_audit):

        def operation(operation_id: str, kind: str, path: str,
                      dependencies: list[str], payload: Any = None) -> tuple[dict[str, Any], str]:
            nonlocal request_counter
            retry_dependencies = list(dependencies)
            previous_request_id = None
            for attempt in range(1, max_attempts + 1):
                wait(policy_wait_seconds, "policy", operation_id)
                request_counter += 1
                request_id = f"{policy}-request-{request_counter:04d}"
                data = _encode(payload) if payload is not None else None
                method = "POST" if data is not None else "GET"
                counts[operation_id] += 1
                emit("request_start", request_id=request_id, operation_id=operation_id,
                     operation_kind=kind, attempt=attempt, method=method, path=path,
                     dependency_request_ids=list(retry_dependencies), retry_of=previous_request_id,
                     request_payload_bytes=len(data or b""))
                request_started = time.perf_counter()
                req = Request(base_url + path, data=data, method=method,
                              headers={"Content-Type": "application/json"})
                try:
                    with opener.open(req, timeout=2) as response:
                        status, body = response.status, response.read()
                except HTTPError as response:
                    with response:
                        status, body = response.code, response.read()
                response_body = json.loads(body)
                emit("request_end", request_id=request_id, operation_id=operation_id,
                     operation_kind=kind, attempt=attempt, status=status, response=response_body,
                     response_payload_bytes=len(body), measured_seconds=time.perf_counter() - request_started)
                if status == 200:
                    return response_body, request_id
                if status not in (408, 429, 500, 502, 503, 504) or attempt == max_attempts:
                    raise _OperationFailure(f"{operation_id}: HTTP {status} after {attempt} attempt(s)")
                previous_request_id = request_id
                retry_dependencies = [*dependencies, request_id]
                wait(retry_backoff_seconds, "retry_backoff", operation_id)
            raise AssertionError("unreachable retry loop")

        try:
            plan, plan_request_id = operation("plan", "scripted_model", "/model/plan", [],
                                              {"task": TASK_ID, "synthetic": True})
            for item in plan["operations"]:
                operation_id = item["operation_id"]
                result, request_id = operation(operation_id, "fixture_tool", item["path"], [plan_request_id])
                checkpoint[operation_id] = (result, request_id)
                emit("checkpoint_commit", operation_id=operation_id, request_id=request_id,
                     source_id=result["source_id"])
            documents = [checkpoint[k][0] for k in ("resources", "requirements")]
            successful_reads = [checkpoint[k][1] for k in ("resources", "requirements")]
            brief, _ = operation("synthesize", "scripted_model", "/model/synthesize", successful_reads,
                                 {"documents": documents, "synthetic": True})
        except _OperationFailure as exc:
            error = str(exc)
        emit("task_end", success=brief == EXPECTED_BRIEF, error=error)
        result = {
            "policy": policy,
            "success": brief == EXPECTED_BRIEF,
            "brief": brief,
            "output_sha256": hashlib.sha256(_encode(brief)).hexdigest() if brief is not None else None,
            "error": error,
            "observed_task_seconds": events[-1]["elapsed_seconds"],
            "request_attempts": request_counter,
            "attempts_by_operation": dict(counts),
            "completed_checkpoint_sources": list(checkpoint),
            "server_request_audit": list(server_audit),
            "request_payload_bytes": sum(e.get("request_payload_bytes", 0) for e in events if e["event"] == "request_start"),
            "response_payload_bytes": sum(e.get("response_payload_bytes", 0) for e in events if e["event"] == "request_end"),
            "policy_wait_requested_seconds": sum(e.get("requested_seconds", 0) for e in events if e["event"] == "wait_start" and e["wait_kind"] == "policy"),
        }
    return result, events


def run_probe(
    output_dir: str | Path,
    *,
    policy_wait_seconds: float = 0.01,
    max_policy_wait_seconds: float = 0.05,
    retry_backoff_seconds: float = 0.002,
    max_attempts: int = 2,
    inject_transient_failure: bool = True,
) -> dict[str, Any]:
    """Run immediate/bounded-wait scripted workflows and save measured artifacts.

    ``events.jsonl`` records actual client dispatch/completion and measured waits.
    ``summary.json`` includes an independent server request audit and output hashes.
    Both policies have the same retry and checkpoint rules. The imposed wait is a
    capability check, not a prediction. Byte counts cover JSON payloads only, not
    headers, TLS, TCP, or total wire traffic. Default execution is normally <1 s.
    """
    if not 0 <= policy_wait_seconds <= max_policy_wait_seconds <= 0.25:
        raise ValueError("Require 0 <= policy wait <= maximum wait <= 0.25 seconds")
    if not 0 <= retry_backoff_seconds <= 0.25:
        raise ValueError("Retry backoff must be between 0 and 0.25 seconds")
    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    all_events = []
    for policy, delay in (("immediate", 0.0), ("bounded_wait", policy_wait_seconds)):
        result, events = _run_workflow(policy, delay, retry_backoff_seconds, max_attempts,
                                      inject_transient_failure)
        runs.append(result)
        all_events.extend(events)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_type": "measured_localhost_capability_probe",
        "synthetic_workflow": True,
        "checkpoint_storage": "memory_only; no process-restart or crash-recovery test",
        "interpretation": "Dispatch/retry/checkpoint capability only; no predictive-performance or field claim.",
        "not_evaluated": ["real LLM reasoning", "browser automation", "Starlink or LEO link performance", "disaster-recovery deployment", "predictive scheduling benefit"],
        "settings": {
            "policy_wait_seconds": policy_wait_seconds,
            "max_policy_wait_seconds": max_policy_wait_seconds,
            "retry_backoff_seconds": retry_backoff_seconds,
            "max_attempts": max_attempts,
            "inject_transient_failure": inject_transient_failure,
        },
        "identical_successful_outputs": all(r["success"] for r in runs) and runs[0]["brief"] == runs[1]["brief"],
        "runs": runs,
    }
    (output_dir / "events.jsonl").write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in all_events))
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/http_probe"))
    parser.add_argument("--policy-wait-seconds", type=float, default=0.01)
    args = parser.parse_args()
    summary = run_probe(args.output, policy_wait_seconds=args.policy_wait_seconds)
    print(json.dumps({"output": str(args.output), "identical_successful_outputs": summary["identical_successful_outputs"],
                      "request_attempts": [r["request_attempts"] for r in summary["runs"]]}, sort_keys=True))


if __name__ == "__main__":
    main()
