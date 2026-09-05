from signal_api.models import ConversationParticipantSide
from signal_api.transcription import TranscriptState, parse_transcript_event

DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"


def test_partial_is_replaced_and_final_is_deduplicated() -> None:
    state = TranscriptState()
    first = parse_transcript_event(
        "microphone", {"type": DELTA, "item_id": "item-1", "delta": "こんに"}
    )
    second = parse_transcript_event(
        "microphone", {"type": DELTA, "item_id": "item-1", "delta": "こんにちは"}
    )
    final = parse_transcript_event(
        "microphone",
        {"type": COMPLETED, "item_id": "item-1", "transcript": "こんにちは"},
    )
    assert first is not None and second is not None and final is not None
    state.apply(first)
    state.apply(second)
    assert state.partials[("microphone", "item-1")] == second
    assert state.apply(final) == final
    assert state.apply(final) is None
    assert final.side is ConversationParticipantSide.SALES_REP


def test_tab_source_is_customer() -> None:
    update = parse_transcript_event(
        "display",
        {"type": COMPLETED, "item_id": "item-2", "transcript": "資料を見ました"},
    )
    assert update is not None
    assert update.side is ConversationParticipantSide.CUSTOMER
