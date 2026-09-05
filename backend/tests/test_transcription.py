import pytest

from signal_api.models import ConversationParticipantSide
from signal_api.transcription import (
    COMPLETED,
    DELTA,
    TranscriptionFailure,
    TranscriptState,
    parse_transcript_event,
)


def event(kind: str, item: str, text: str = "") -> dict[str, object]:
    return {"type": kind, "item_id": item, "delta": text, "transcript": text}


def test_deltas_accumulate_including_spaces_and_final_replaces_them() -> None:
    state = TranscriptState()
    state.apply("microphone", event("input_audio_buffer.committed", "1"))
    for text in ["こんに", "ちは", " ", "世界"]:
        updates = state.apply("microphone", event(DELTA, "1", text))
    assert updates[0].text == "こんにちは 世界"
    final = state.apply("microphone", event(COMPLETED, "1", "こんにちは、世界"))
    assert final[0].final
    assert final[0].side is ConversationParticipantSide.SALES_REP
    assert state.apply("microphone", event(COMPLETED, "1", "重複")) == []
    assert state.apply("microphone", event(DELTA, "1", "遅延")) == []
    assert not state.partials


def test_reversed_completions_wait_for_audio_commit_order() -> None:
    state = TranscriptState()
    for item in ["1", "2"]:
        state.apply("display", event("input_audio_buffer.committed", item))
    assert state.apply("display", event(COMPLETED, "2", "二番目")) == []
    updates = state.apply("display", event(COMPLETED, "1", "一番目"))
    assert [u.item_id for u in updates] == ["1", "2"]
    assert all(u.side is ConversationParticipantSide.CUSTOMER for u in updates)


def test_empty_final_clears_partial_and_unknown_event_is_ignored() -> None:
    state = TranscriptState()
    state.apply("display", event(DELTA, "1", "途中"))
    assert state.apply("display", event(COMPLETED, "1", "")) == []
    assert (
        state.apply("display", event("input_audio_buffer.committed", "1"))[0].text == ""
    )
    assert not state.partials
    assert parse_transcript_event("display", event("unknown", "x", "text")) is None


def test_provider_error_has_no_raw_payload() -> None:
    with pytest.raises(TranscriptionFailure, match="^provider_error$"):
        TranscriptState().apply("display", {"type": "error", "error": "secret payload"})
