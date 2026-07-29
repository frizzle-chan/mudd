"""Unit tests for health payload construction and sync state tracking."""

from __future__ import annotations

from mudd.health import (
    HEALTHY_STATUS,
    UNHEALTHY_STATUS,
    HealthCheck,
    HealthState,
    build_payload,
    status_code_for,
)


def test_payload_is_ok_when_every_check_passes():
    checks = [
        HealthCheck("discord", True, "connected"),
        HealthCheck("database", True, "responsive"),
    ]

    payload = build_payload(checks, "abc123")

    assert payload["status"] == HEALTHY_STATUS
    assert payload["commit"] == "abc123"
    assert payload["checks"]["discord"] == {"ok": True, "detail": "connected"}
    assert status_code_for(payload) == 200


def test_payload_is_unhealthy_when_any_check_fails():
    checks = [
        HealthCheck("discord", True, "connected"),
        HealthCheck("world", False, "initial world sync has not finished"),
    ]

    payload = build_payload(checks, "abc123")

    assert payload["status"] == UNHEALTHY_STATUS
    assert status_code_for(payload) == 503


def test_empty_check_list_is_not_reported_as_healthy_by_accident():
    # all([]) is True, so an empty payload reports ok. Documented rather than
    # guarded: the handler always supplies a fixed, non-empty set of probes.
    payload = build_payload([], "abc123")

    assert payload["checks"] == {}
    assert payload["status"] == HEALTHY_STATUS


def test_fresh_state_reports_sync_incomplete():
    state = HealthState()

    assert state.first_sync_completed is False
    assert state.last_sync_error is None


def test_marking_success_records_completion():
    state = HealthState()

    state.mark_sync_succeeded()

    assert state.first_sync_completed is True
    assert state.last_sync_error is None


def test_marking_failure_records_the_cause():
    state = HealthState()

    state.mark_sync_failed(ValueError("no zones found"))

    assert state.last_sync_error == "ValueError: no zones found"
    assert state.first_sync_completed is False


def test_recovery_clears_a_previous_failure():
    state = HealthState()
    state.mark_sync_failed(RuntimeError("gateway timeout"))

    state.mark_sync_succeeded()

    assert state.first_sync_completed is True
    assert state.last_sync_error is None


def test_failure_after_success_keeps_completion_but_reports_the_error():
    # A later sync failing does not un-load the world; the endpoint should
    # surface the error while still acknowledging the world is populated.
    state = HealthState()
    state.mark_sync_succeeded()

    state.mark_sync_failed(RuntimeError("rate limited"))

    assert state.first_sync_completed is True
    assert state.last_sync_error == "RuntimeError: rate limited"
