"""Aggregate content-free JSON logs: python -m signal_api.evaluate_traces < api.log."""

import json
import math
import sys
from collections import defaultdict, deque
from collections.abc import Iterable

TARGETS = {
    "transcription.first_partial_latency": 1000,
    "suggestion.created_to_browser_ack": 5000,
}


def evaluate(lines: Iterable[str]) -> dict[str, object]:
    values: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=10_000))
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        stage = record.get("event")
        duration = record.get("duration_ms")
        if (
            stage in TARGETS
            and isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(duration)
            and duration >= 0
        ):
            values[stage].append(float(duration))
    metrics = {}
    for stage, target in TARGETS.items():
        samples = sorted(values[stage])
        p95 = samples[math.ceil(len(samples) * 0.95) - 1] if samples else None
        metrics[stage] = {
            "samples": len(samples),
            "p95_ms": p95,
            "target_ms": target,
            "status": "unmeasured"
            if p95 is None
            else "within_target"
            if p95 <= target
            else "over_target",
        }
    return {
        "metrics": metrics,
        "sample_window": "last_10000_per_metric",
        "provenance": (
            "input_logs_only; synthetic vs real Meet must be recorded by the operator"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(sys.stdin), ensure_ascii=False))
