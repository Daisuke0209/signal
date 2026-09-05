import asyncio
import json
import logging
import uuid

import pytest

from signal_api import domain_traces
from signal_api.domain_traces import span, trace, trace_context


def test_context_survives_threads_without_cross_task_leaks(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger("signal_test.traces")
    monkeypatch.setattr(domain_traces, "logger", logger)
    caplog.set_level(logging.INFO, logger=logger.name)
    ids = [uuid.uuid4(), uuid.uuid4()]

    async def task(cid: uuid.UUID) -> None:
        with trace_context(cid, generation=2):
            await asyncio.to_thread(trace, "test.thread")
            await asyncio.sleep(0)
            trace("test.async")

    async def scenario() -> None:
        await asyncio.gather(*(task(cid) for cid in ids))
        trace("test.outside")

    asyncio.run(scenario())
    records = [json.loads(record.message) for record in caplog.records]
    for cid in ids:
        assert len([r for r in records if r.get("conversation_id") == str(cid)]) == 2
    assert "conversation_id" not in records[-1]


def test_spans_measure_success_failure_and_hide_error_content(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger("signal_test.traces")
    monkeypatch.setattr(domain_traces, "logger", logger)
    caplog.set_level(logging.INFO, logger=logger.name)
    clock = iter([10.0, 10.8, 20.0, 23.5, 30.0, 31.0])
    monkeypatch.setattr(
        "signal_api.domain_traces.time.perf_counter", lambda: next(clock)
    )
    with span("test.partial_target"):
        pass
    with span("test.suggestion_target"):
        pass
    with pytest.raises(ValueError), span("test.failure"):
        raise ValueError("secret-token-and-customer-text")
    trace("test.failure_code", error_code="secret-provider-body", retryable=False)
    records = [json.loads(record.message) for record in caplog.records]
    assert records[1]["duration_ms"] == 800
    assert records[3]["duration_ms"] == 3500
    assert records[5]["duration_ms"] == 1000
    assert records[5]["outcome"] == "failed"
    assert records[-1]["error_code"] == "operation_failed"
    assert "secret-" not in caplog.text


def test_observation_limits_bound_bursts_and_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signal_api.observation_limits import ObservationLimiter

    now = [100.0]
    monkeypatch.setattr("signal_api.observation_limits.time.monotonic", lambda: now[0])
    limiter = ObservationLimiter(limit=2)
    assert limiter.allow("one")
    assert limiter.allow("one")
    assert not limiter.allow("one")
    assert limiter.allow("two")
    now[0] += 60
    assert limiter.allow("one")


def test_evaluation_separates_missing_and_over_target_without_echoing_content() -> None:
    from signal_api.evaluate_traces import evaluate

    report = evaluate(
        [
            "not json private-token",
            json.dumps(
                {"event": "transcription.first_partial_latency", "duration_ms": 800}
            ),
            json.dumps(
                {"event": "transcription.first_partial_latency", "duration_ms": 1100}
            ),
            json.dumps(
                {"event": "transcription.first_partial_latency", "duration_ms": -50}
            ),
            json.dumps(
                {
                    "event": "transcription.first_partial_latency",
                    "duration_ms": float("nan"),
                }
            ),
        ]
    )
    assert report["metrics"] == {
        "transcription.first_partial_latency": {
            "samples": 2,
            "p95_ms": 1100,
            "target_ms": 1000,
            "status": "over_target",
        },
        "suggestion.created_to_browser_ack": {
            "samples": 0,
            "p95_ms": None,
            "target_ms": 5000,
            "status": "unmeasured",
        },
    }
    assert "private-token" not in json.dumps(report)
