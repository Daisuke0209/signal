"""Provider events are transient; only ordered completions cross persistence."""

from dataclasses import dataclass, field, replace
from typing import Literal

from signal_api.models import ConversationParticipantSide

Source = Literal["microphone", "display"]
DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"


class TranscriptionFailure(Exception):
    """Safe machine code only. Never include provider payloads or credentials."""


@dataclass(frozen=True)
class TranscriptUpdate:
    source_id: Source
    item_id: str
    side: ConversationParticipantSide
    text: str
    final: bool


def source_side(source_id: Source) -> ConversationParticipantSide:
    return (
        ConversationParticipantSide.SALES_REP
        if source_id == "microphone"
        else ConversationParticipantSide.CUSTOMER
    )


def parse_transcript_event(
    source_id: Source, event: dict[str, object]
) -> TranscriptUpdate | None:
    event_type, item_id = event.get("type"), event.get("item_id")
    if event_type not in (DELTA, COMPLETED):
        return None
    text = event.get("delta" if event_type == DELTA else "transcript")
    if not isinstance(item_id, str) or not isinstance(text, str):
        return None
    return TranscriptUpdate(
        source_id, item_id, source_side(source_id), text, event_type == COMPLETED
    )


@dataclass
class TranscriptState:
    partials: dict[str, TranscriptUpdate] = field(default_factory=dict)
    finalized: set[str] = field(default_factory=set)
    committed: list[str] = field(default_factory=list)
    completions: dict[str, TranscriptUpdate] = field(default_factory=dict)

    def apply(self, source: Source, event: dict[str, object]) -> list[TranscriptUpdate]:
        if event.get("type") in (
            "error",
            "conversation.item.input_audio_transcription.failed",
        ):
            raise TranscriptionFailure("provider_error")
        item_id = event.get("item_id")
        if (
            event.get("type") == "input_audio_buffer.committed"
            and isinstance(item_id, str)
            and item_id not in self.committed
            and item_id not in self.finalized
        ):
            self.committed.append(item_id)
        update = parse_transcript_event(source, event)
        if update and update.item_id not in self.finalized:
            if update.final:
                self.completions[update.item_id] = update
            else:
                previous = self.partials.get(update.item_id)
                update = replace(
                    update, text=(previous.text if previous else "") + update.text
                )
                self.partials[update.item_id] = update
                return [update]
        results = []
        # committed events arrive in audio order; completed events can arrive reversed.
        while self.committed and self.committed[0] in self.completions:
            key = self.committed.pop(0)
            self.finalized.add(key)
            self.partials.pop(key, None)
            results.append(self.completions.pop(key))
        if len(self.partials) + len(self.committed) + len(self.completions) > 100:
            raise TranscriptionFailure("provider_backlog")
        return results
