"""Meaningful controls for the synthetic scheduling model, using unittest."""

import math
import random
import unittest

from leo_agent_study.scheduling import (
    CapacitySegment, LinkTrace, Operation, asap_policy, exchange_finish,
    first_outage, periodic_trace, reactive_policy, run_chain,
    transmission_finish, uninterrupted_dispatch_time,
)


class CapacityServiceTests(unittest.TestCase):
    def test_progress_is_preserved_across_zero_capacity(self):
        trace = LinkTrace((CapacitySegment(0, 1, 100),
                           CapacitySegment(1, 4, 0),
                           CapacitySegment(4, 10, 100)))
        self.assertEqual(transmission_finish(trace, 0, 200), 5)
        self.assertEqual(transmission_finish(trace, 4, 200), 6)

    def test_capacity_and_fixed_propagation_are_integrated(self):
        trace = LinkTrace((CapacitySegment(0, 1, 100),
                           CapacitySegment(1, 10, 200)), propagation_s=0.1)
        operation = Operation("exchange", 150, 200, inference_s=0.5)
        self.assertAlmostEqual(exchange_finish(trace, 0, operation), 2.95)

    def test_outage_boundary_is_end_exclusive(self):
        trace = LinkTrace((CapacitySegment(0, 1, 100),
                           CapacitySegment(1, 2, 0),
                           CapacitySegment(2, 3, 100)))
        self.assertIsNone(first_outage(trace, 0, 1))
        self.assertEqual(first_outage(trace, 1, 2), 1)
        self.assertIsNone(first_outage(trace, 2, 3))

    def test_trace_exhaustion_is_not_extrapolated(self):
        trace = LinkTrace((CapacitySegment(0, 1, 100),))
        self.assertEqual(transmission_finish(trace, 0, 100), 1)
        self.assertTrue(math.isinf(transmission_finish(trace, 0, 101)))
        result = run_chain(trace, [Operation("too_large", 0, 101)])
        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "trace_exhausted")
        self.assertEqual(result.transmitted_bytes, 100)
        # A later deadline must not turn an unobserved trace suffix into service.
        bounded = run_chain(trace, [Operation("too_large", 0, 101)], deadline_s=10)
        self.assertEqual(bounded.failure_reason, "trace_exhausted")
        self.assertEqual(bounded.finish_s, 1)

    def test_invalid_noncontiguous_and_negative_traces_rejected(self):
        with self.assertRaises(ValueError):
            LinkTrace((CapacitySegment(0, 1, 1), CapacitySegment(2, 3, 1)))
        with self.assertRaises(ValueError):
            LinkTrace((CapacitySegment(0, 1, -1),))


class SchedulingControls(unittest.TestCase):
    def test_arbitrary_waits_cannot_improve_progress_preserving_chain(self):
        """A broad seeded invariant, rather than one favorable parameter case."""
        rng = random.Random(1345827)
        for case in range(200):
            period = rng.uniform(3, 20)
            bad_duration = rng.uniform(0, period * 0.45)
            trace = periodic_trace(
                horizon_s=2000, period_s=period, bad_start_s=0,
                bad_duration_s=bad_duration,
                good_rate_bytes_per_s=rng.uniform(100, 500),
                bad_rate_bytes_per_s=rng.choice([0, 1, 20]),
                phase_s=rng.uniform(0, period), propagation_s=rng.uniform(0, 0.2))
            operations = [Operation(str(i), rng.uniform(1, 400),
                                    rng.uniform(1, 1000),
                                    inference_s=rng.uniform(0, 3),
                                    local_after_s=rng.uniform(0, 1))
                          for i in range(6)]
            waits = {operation.name: rng.uniform(0, period) for operation in operations}
            def delayed(ready, operation, attempt):
                return ready + waits[operation.name]
            start = rng.uniform(0, period)
            immediate = run_chain(trace, operations, start_s=start)
            waited = run_chain(trace, operations, start_s=start, policy=delayed)
            self.assertTrue(immediate.success, case)
            self.assertTrue(waited.success, case)
            self.assertGreaterEqual(waited.finish_s + 1e-9, immediate.finish_s, case)

    def test_no_outage_modes_agree(self):
        trace = LinkTrace((CapacitySegment(0, 100, 100),), propagation_s=0.1)
        operations = [Operation("a", 100, 200, 0.5, 0.2),
                      Operation("b", 20, 50, 0.1)]
        first = run_chain(trace, operations)
        second = run_chain(trace, operations, mode="restart_on_outage")
        self.assertEqual(first, second)

    def test_strong_reactive_can_match_perfect_future_completion(self):
        """Prediction does not get a forced time advantage over a strong control."""
        trace = periodic_trace(horizon_s=50, period_s=7, bad_start_s=5,
                               bad_duration_s=2, good_rate_bytes_per_s=100)
        operation = Operation("read", 0, 200)
        def oracle(ready, operation, attempt):
            return uninterrupted_dispatch_time(trace, ready, operation)
        reactive = run_chain(trace, [operation], start_s=4,
                             policy=reactive_policy(trace), mode="restart_on_outage")
        predicted = run_chain(trace, [operation], start_s=4,
                              policy=oracle, mode="restart_on_outage")
        self.assertTrue(reactive.success)
        self.assertTrue(predicted.success)
        self.assertEqual(reactive.finish_s, 9)
        self.assertEqual(predicted.finish_s, 9)
        self.assertEqual(reactive.failed_attempts, 1)
        self.assertEqual(predicted.failed_attempts, 0)
        self.assertGreater(reactive.transmitted_bytes, predicted.transmitted_bytes)

    def test_slow_failure_detection_can_create_admission_headroom(self):
        """Positive timing gain has an explicit extra assumption and cost."""
        trace = periodic_trace(horizon_s=50, period_s=7, bad_start_s=5,
                               bad_duration_s=2, good_rate_bytes_per_s=100)
        operation = Operation("read", 0, 200)
        def oracle(ready, operation, attempt):
            return uninterrupted_dispatch_time(trace, ready, operation)
        reactive = run_chain(trace, [operation], start_s=4,
                             policy=reactive_policy(trace), mode="restart_on_outage",
                             failure_detection_s=3)
        predicted = run_chain(trace, [operation], start_s=4,
                              policy=oracle, mode="restart_on_outage",
                              failure_detection_s=3)
        self.assertEqual(reactive.finish_s, 10)
        self.assertEqual(predicted.finish_s, 9)
        self.assertEqual(predicted.policy_wait_s, 3)

    def test_retry_limit_is_finite_even_with_zero_detection_and_backoff(self):
        trace = LinkTrace((CapacitySegment(0, 10, 0),))
        result = run_chain(trace, [Operation("unavailable", 1, 1)],
                           mode="restart_on_outage", max_attempts_per_operation=4)
        self.assertFalse(result.success)
        self.assertEqual(result.failure_reason, "retry_exhausted")
        self.assertEqual(len(result.attempts), 4)
        self.assertEqual(result.finish_s, 0)
        self.assertEqual(result.restricted_completion_s(10), 10)

    def test_deadline_charges_policy_wait_and_early_failure(self):
        trace = LinkTrace((CapacitySegment(0, 100, 100),))
        result = run_chain(trace, [Operation("read", 100, 100)],
                           policy=lambda ready, operation, attempt: ready + 20,
                           deadline_s=10)
        self.assertFalse(result.success)
        self.assertEqual(result.policy_wait_s, 10)
        self.assertEqual(result.restricted_completion_s(10), 10)
        self.assertEqual(len(result.attempts), 0)

    def test_local_work_counts_against_deadline(self):
        trace = LinkTrace((CapacitySegment(0, 100, 100),))
        result = run_chain(trace, [Operation("read", 100, 100, local_after_s=10)],
                           deadline_s=5)
        self.assertFalse(result.success)
        self.assertEqual(result.finish_s, 5)
        self.assertEqual(result.completed_operations, 0)
        self.assertEqual(result.restricted_completion_s(5), 5)

    def test_backoff_is_counted_and_retry_limit_includes_initial_attempt(self):
        trace = LinkTrace((CapacitySegment(0, 10, 0), CapacitySegment(10, 20, 100)))
        result = run_chain(trace, [Operation("read", 1, 1)],
                           mode="restart_on_outage", retry_backoff_s=2,
                           max_attempts_per_operation=3)
        self.assertFalse(result.success)
        self.assertEqual(result.backoff_wait_s, 4)
        self.assertEqual(result.finish_s, 4)
        self.assertEqual([a.dispatch_s for a in result.attempts], [0, 2, 4])
        self.assertEqual(result.failure_reason, "retry_exhausted")

    def test_backwards_policy_rejected(self):
        trace = LinkTrace((CapacitySegment(0, 10, 100),))
        with self.assertRaises(ValueError):
            run_chain(trace, [Operation("read", 1, 1)], start_s=1,
                      policy=lambda ready, operation, attempt: ready - 0.1)


if __name__ == "__main__":
    unittest.main()
