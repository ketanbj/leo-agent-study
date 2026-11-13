"""Deterministic scheduling models for a *synthetic* timing-headroom study.

This module does not model an LLM's reasoning, claim to reproduce Starlink, or
sample an entire request's latency from the state at dispatch.  Every payload is
served by integrating the nonnegative link capacity over time.  Propagation is
fixed, so the progress-preserving model is FIFO: deferring the same serial work
cannot make it finish earlier.  This is a scientific negative control.

``restart_on_outage`` is a separate, deliberately stronger fault assumption:
an RPC requires uninterrupted session availability from dispatch to response
arrival.  A zero-capacity interval loses that attempt's progress, including a
session that is waiting for remote inference.  Detection and retry delay are
explicit parameters.  This is not asserted to be the behavior of any real
browser, TCP connection, LLM API, or LEO network.  Its purpose is to reveal which
additional failure assumptions are needed for admission timing to have value.

All times are virtual seconds and all rates are *bytes* per second.  A dispatch
policy receives ``(ready_s, operation, attempt_number)`` and returns an absolute
dispatch time no earlier than readiness.  Its closure can contain causal
forecasts, a training-only calendar, or a clearly labeled perfect-future oracle.
The simulator never supplies future trace data to a policy automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, Literal


@dataclass(frozen=True, slots=True)
class CapacitySegment:
    start_s: float
    end_s: float
    rate_bytes_per_s: float


@dataclass(frozen=True, slots=True)
class LinkTrace:
    """A contiguous finite capacity trace, with fixed one-way propagation."""

    segments: tuple[CapacitySegment, ...]
    propagation_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "segments", tuple(self.segments))
        if not self.segments:
            raise ValueError("a trace must have at least one segment")
        if not math.isfinite(self.propagation_s) or self.propagation_s < 0:
            raise ValueError("propagation_s must be finite and nonnegative")
        previous_end = None
        for segment in self.segments:
            if not all(math.isfinite(value) for value in
                       (segment.start_s, segment.end_s, segment.rate_bytes_per_s)):
                raise ValueError("segment values must be finite")
            if segment.start_s < 0 or segment.end_s <= segment.start_s:
                raise ValueError("segments require 0 <= start_s < end_s")
            if segment.rate_bytes_per_s < 0:
                raise ValueError("capacity cannot be negative")
            if previous_end is not None and not math.isclose(
                segment.start_s, previous_end, abs_tol=1e-10, rel_tol=0.0
            ):
                raise ValueError("segments must be ordered, contiguous, and nonoverlapping")
            previous_end = segment.end_s

    @property
    def start_s(self) -> float:
        return self.segments[0].start_s

    @property
    def end_s(self) -> float:
        return self.segments[-1].end_s

    def rate_at(self, time_s: float) -> float:
        """Return instantaneous capacity; the last endpoint is not covered."""
        for segment in self.segments:
            if segment.start_s <= time_s < segment.end_s:
                return segment.rate_bytes_per_s
        raise ValueError("time is outside the trace")

    def next_available_time(self, time_s: float) -> float:
        """First covered time at/after ``time_s`` having positive capacity."""
        for segment in self.segments:
            if segment.end_s > time_s and segment.rate_bytes_per_s > 0:
                return max(time_s, segment.start_s)
        return math.inf


@dataclass(frozen=True, slots=True)
class Operation:
    """One serial read-only request, remote compute, response, then local work.

    Request and response payloads include whatever protocol/header overhead the
    fixture chooses to model.  ``inference_s`` is a fixed external service cost;
    the controller cannot shorten it.  ``local_after_s`` does not use the link.
    The name is an identifier, not a claim that a real model/tool was invoked.
    """

    name: str
    request_bytes: float
    response_bytes: float
    inference_s: float = 0.0
    local_after_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("operation name cannot be empty")
        for value in (self.request_bytes, self.response_bytes,
                      self.inference_s, self.local_after_s):
            if not math.isfinite(value) or value < 0:
                raise ValueError("operation amounts must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class Attempt:
    operation: str
    attempt_number: int
    ready_s: float
    dispatch_s: float
    finish_s: float
    status: Literal["success", "outage", "deadline", "trace_exhausted"]
    transmitted_bytes: float


@dataclass(frozen=True, slots=True)
class RunResult:
    start_s: float
    finish_s: float
    success: bool
    completed_operations: int
    attempts: tuple[Attempt, ...]
    policy_wait_s: float
    backoff_wait_s: float
    failure_reason: str | None = None

    @property
    def elapsed_s(self) -> float:
        """Observed stop time, including early failure; NOT a success metric."""
        return self.finish_s - self.start_s

    @property
    def transmitted_bytes(self) -> float:
        return sum(attempt.transmitted_bytes for attempt in self.attempts)

    @property
    def failed_attempts(self) -> int:
        return sum(attempt.status != "success" for attempt in self.attempts)

    def restricted_completion_s(self, deadline_s: float) -> float:
        """Elapsed correct-completion time, charging failures the full deadline.

        ``deadline_s`` is absolute, not a duration.  Calling code must score
        semantic correctness separately when using a real agent.  In this fixed
        trace model, ``success`` means that every specified operation completes.
        """
        if deadline_s < self.start_s or not math.isfinite(deadline_s):
            raise ValueError("deadline must be finite and no earlier than start")
        if self.success and self.finish_s <= deadline_s:
            return self.elapsed_s
        return deadline_s - self.start_s


DispatchPolicy = Callable[[float, Operation, int], float]
RetryBackoff = float | Callable[[int], float]


def asap_policy(ready_s: float, operation: Operation, attempt_number: int) -> float:
    """Dispatch every ready attempt immediately."""
    return ready_s


def reactive_policy(trace: LinkTrace) -> DispatchPolicy:
    """An idealized strong reactive comparator: dispatch when currently up.

    It has instantaneous state observation and wakes exactly when an outage
    ends, with zero sensing cost.  Thus it is an optimistic reactive bound,
    stronger than a real periodically polling implementation.  It does not
    inspect an operation's future interval before starting it.
    """
    def policy(ready_s: float, operation: Operation, attempt_number: int) -> float:
        return trace.next_available_time(ready_s)
    return policy


def transmission_finish(trace: LinkTrace, start_s: float, payload_bytes: float) -> float:
    """Integrate service until a payload finishes, excluding propagation.

    Zero-capacity intervals preserve progress.  A later dispatch cannot overtake
    the same earlier payload in this model.  Infinity indicates insufficient
    trace coverage/capacity, never an invented post-trace extrapolation.
    """
    if not math.isfinite(start_s) or start_s < trace.start_s:
        raise ValueError("start must be finite and inside/after the trace start")
    if not math.isfinite(payload_bytes) or payload_bytes < 0:
        raise ValueError("payload must be finite and nonnegative")
    if payload_bytes == 0:
        return start_s
    remaining = payload_bytes
    for segment in trace.segments:
        if segment.end_s <= start_s or segment.rate_bytes_per_s == 0:
            continue
        begin = max(start_s, segment.start_s)
        available = (segment.end_s - begin) * segment.rate_bytes_per_s
        if remaining <= available:
            return begin + remaining / segment.rate_bytes_per_s
        remaining -= available
    return math.inf


def transfer_finish(trace: LinkTrace, start_s: float, payload_bytes: float) -> float:
    """Payload transmission followed by fixed one-way propagation."""
    finish_s = transmission_finish(trace, start_s, payload_bytes)
    return finish_s + trace.propagation_s


def exchange_finish(trace: LinkTrace, start_s: float, operation: Operation) -> float:
    """Response arrival for one request/compute/response exchange."""
    request_arrival = transfer_finish(trace, start_s, operation.request_bytes)
    if not math.isfinite(request_arrival):
        return math.inf
    response_ready = request_arrival + operation.inference_s
    return transfer_finish(trace, response_ready, operation.response_bytes)


def first_outage(trace: LinkTrace, start_s: float, end_s: float) -> float | None:
    """First zero-capacity time in [start_s, end_s); the end is exclusive."""
    for segment in trace.segments:
        if (segment.rate_bytes_per_s == 0 and segment.end_s > start_s
                and segment.start_s < end_s):
            return max(start_s, segment.start_s)
    return None


def uninterrupted_dispatch_time(trace: LinkTrace, ready_s: float,
                                operation: Operation) -> float:
    """Perfect-future admission oracle for the restart-on-outage assumption.

    This is NOT a deployable predictor.  It searches readiness and outage-end
    boundaries for the first start whose entire exchange avoids zero capacity.
    Fixed FIFO propagation/service makes each within-up-interval completion
    nondecreasing in dispatch time, so these candidates suffice for this bound.
    """
    candidate = trace.next_available_time(ready_s)
    while math.isfinite(candidate) and candidate < trace.end_s:
        finish = exchange_finish(trace, candidate, operation)
        outage = first_outage(trace, candidate, finish)
        if outage is None:
            return candidate if math.isfinite(finish) else math.inf
        candidate = trace.next_available_time(outage)
    return math.inf


def _bytes_until(trace: LinkTrace, start_s: float, stop_s: float,
                 payload_bytes: float) -> float:
    if stop_s <= start_s:
        return 0.0
    supplied = 0.0
    for segment in trace.segments:
        begin = max(start_s, segment.start_s)
        end = min(stop_s, segment.end_s)
        if end > begin:
            supplied += (end - begin) * segment.rate_bytes_per_s
    return min(payload_bytes, supplied)


def _exchange_bytes_until(trace: LinkTrace, dispatch_s: float, stop_s: float,
                          operation: Operation) -> float:
    request_bytes = _bytes_until(trace, dispatch_s, stop_s, operation.request_bytes)
    request_arrival = transfer_finish(trace, dispatch_s, operation.request_bytes)
    response_ready = request_arrival + operation.inference_s
    response_bytes = _bytes_until(trace, response_ready, stop_s, operation.response_bytes)
    return request_bytes + response_bytes


def run_chain(trace: LinkTrace, operations: Iterable[Operation], *,
              start_s: float = 0.0, policy: DispatchPolicy = asap_policy,
              mode: Literal["progress", "restart_on_outage"] = "progress",
              max_attempts_per_operation: int = 3,
              retry_backoff_s: RetryBackoff = 0.0,
              failure_detection_s: float = 0.0,
              deadline_s: float = math.inf) -> RunResult:
    """Execute a serial fixed operation chain under an admission policy.

    The primary ``progress`` mode preserves partial transfers, even across an
    outage.  Its completion cannot improve through nonnegative dispatch waits.
    ``restart_on_outage`` invalidates an RPC at its first intersecting outage;
    detection takes ``failure_detection_s`` and the retry starts after the
    configured backoff.  No bytes progress after the invalidating outage.

    ``max_attempts_per_operation`` includes the initial attempt.  A callable
    backoff receives the failed attempt number (starting at one).  All waits
    count against an absolute ``deadline_s``.  Failure returns the actual stop
    time; use ``restricted_completion_s`` when computing completion metrics.
    """
    if mode not in ("progress", "restart_on_outage"):
        raise ValueError("unknown mode")
    if (not isinstance(max_attempts_per_operation, int)
            or isinstance(max_attempts_per_operation, bool)
            or max_attempts_per_operation < 1):
        raise ValueError("max_attempts_per_operation must be a positive integer")
    if not math.isfinite(start_s) or start_s < trace.start_s:
        raise ValueError("invalid start_s")
    if math.isnan(deadline_s) or deadline_s < start_s:
        raise ValueError("deadline must be no earlier than start")
    if not math.isfinite(failure_detection_s) or failure_detection_s < 0:
        raise ValueError("failure_detection_s must be finite and nonnegative")
    if not callable(retry_backoff_s) and (
        not math.isfinite(retry_backoff_s) or retry_backoff_s < 0
    ):
        raise ValueError("retry_backoff_s must be finite and nonnegative")

    records: list[Attempt] = []
    now = start_s
    completed = 0
    policy_wait = 0.0
    backoff_wait = 0.0

    def result(success: bool, reason: str | None = None) -> RunResult:
        return RunResult(start_s, now, success, completed, tuple(records),
                         policy_wait, backoff_wait, reason)

    for operation in operations:
        for attempt_number in range(1, max_attempts_per_operation + 1):
            if now >= deadline_s:
                now = deadline_s
                return result(False, "deadline")
            if now >= trace.end_s:
                return result(False, "trace_exhausted")
            ready = now
            dispatch = policy(ready, operation, attempt_number)
            if math.isnan(dispatch) or dispatch < ready:
                raise ValueError("policy must return a dispatch time >= readiness")
            if not math.isfinite(dispatch):
                stop = min(deadline_s, trace.end_s)
                policy_wait += max(0.0, stop - ready)
                now = stop
                return result(False, "policy_no_dispatch")
            if dispatch >= min(deadline_s, trace.end_s):
                now = min(deadline_s, trace.end_s)
                policy_wait += now - ready
                return result(False, "deadline" if deadline_s <= trace.end_s
                              else "trace_exhausted")
            policy_wait += dispatch - ready
            finish = exchange_finish(trace, dispatch, operation)
            outage = (first_outage(trace, dispatch, finish)
                      if mode == "restart_on_outage" else None)
            invalid_at = outage if outage is not None else finish
            event_end = (outage + failure_detection_s
                         if outage is not None else finish)

            if not math.isfinite(finish) and outage is None:
                now = min(deadline_s, trace.end_s)
                status = "deadline" if deadline_s <= trace.end_s else "trace_exhausted"
                records.append(Attempt(operation.name, attempt_number, ready,
                                       dispatch, now, status,
                                       _exchange_bytes_until(trace, dispatch, now, operation)))
                return result(False, status)
            if deadline_s < event_end:
                now = deadline_s
                records.append(Attempt(operation.name, attempt_number, ready,
                                       dispatch, now, "deadline",
                                       _exchange_bytes_until(trace, dispatch,
                                                             min(now, invalid_at), operation)))
                return result(False, "deadline")
            if event_end > trace.end_s and not math.isfinite(finish):
                now = trace.end_s
                records.append(Attempt(operation.name, attempt_number, ready,
                                       dispatch, now, "trace_exhausted",
                                       _exchange_bytes_until(trace, dispatch,
                                                             min(now, invalid_at), operation)))
                return result(False, "trace_exhausted")
            now = event_end
            if outage is not None:
                records.append(Attempt(operation.name, attempt_number, ready,
                                       dispatch, now, "outage",
                                       _exchange_bytes_until(trace, dispatch, outage, operation)))
                if attempt_number == max_attempts_per_operation:
                    return result(False, "retry_exhausted")
                backoff = (retry_backoff_s(attempt_number)
                           if callable(retry_backoff_s) else retry_backoff_s)
                if not math.isfinite(backoff) or backoff < 0:
                    raise ValueError("backoff must be finite and nonnegative")
                delay = min(backoff, max(0.0, deadline_s - now))
                backoff_wait += delay
                now += delay
                continue
            records.append(Attempt(operation.name, attempt_number, ready,
                                   dispatch, now, "success",
                                   operation.request_bytes + operation.response_bytes))
            now += operation.local_after_s
            if now > deadline_s:
                now = deadline_s
                return result(False, "deadline")
            completed += 1
            break
    return result(True)


def periodic_trace(*, horizon_s: float, period_s: float,
                   bad_start_s: float, bad_duration_s: float,
                   good_rate_bytes_per_s: float,
                   bad_rate_bytes_per_s: float = 0.0,
                   phase_s: float = 0.0,
                   propagation_s: float = 0.0) -> LinkTrace:
    """Build an explicitly synthetic periodic trace; phase is phase at t=0.

    The bad interval cannot wrap within the period; ``phase_s`` shifts the trace
    and can be any finite real number.  These parameters are experimental
    assumptions, not measurements or default characteristics of Starlink.
    """
    values = (horizon_s, period_s, bad_start_s, bad_duration_s,
              good_rate_bytes_per_s, bad_rate_bytes_per_s, phase_s)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("periodic parameters must be finite")
    if horizon_s <= 0 or period_s <= 0:
        raise ValueError("horizon and period must be positive")
    if not 0 <= bad_start_s <= period_s:
        raise ValueError("bad_start_s must be within the period")
    if bad_duration_s < 0 or bad_start_s + bad_duration_s > period_s:
        raise ValueError("bad interval must fit inside the period")
    if good_rate_bytes_per_s < 0 or bad_rate_bytes_per_s < 0:
        raise ValueError("capacity cannot be negative")
    phase_s %= period_s
    boundaries = {0.0, horizon_s}
    for cycle in range(-1, math.ceil(horizon_s / period_s) + 2):
        for offset in (bad_start_s, bad_start_s + bad_duration_s):
            boundary = cycle * period_s + offset - phase_s
            if 0 < boundary < horizon_s:
                boundaries.add(boundary)
    ordered = sorted(boundaries)
    segments = []
    for begin, end in zip(ordered, ordered[1:]):
        phase = ((begin + end) / 2 + phase_s) % period_s
        bad = bad_start_s <= phase < bad_start_s + bad_duration_s
        rate = bad_rate_bytes_per_s if bad else good_rate_bytes_per_s
        segments.append(CapacitySegment(begin, end, rate))
    return LinkTrace(tuple(segments), propagation_s)
