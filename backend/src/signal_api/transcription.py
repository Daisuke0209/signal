from dataclasses import dataclass, field
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from signal_api.models import ConversationParticipantSide


@dataclass(frozen=True)
class TranscriptUpdate:
    source_id: str
    item_id: str
    side: ConversationParticipantSide
    text: str
    final: bool


@dataclass
class TranscriptState:
    partials: dict[tuple[str, str], TranscriptUpdate] = field(default_factory=dict)
    finalized: set[tuple[str, str]] = field(default_factory=set)

    def apply(self, update: TranscriptUpdate) -> TranscriptUpdate | None:
        key = (update.source_id, update.item_id)
        if key in self.finalized:
            return None
        if update.final:
            self.partials.pop(key, None)
            self.finalized.add(key)
            return update
        self.partials[key] = update
        return update


class TranscriptionProvider(Protocol):
    async def events(
        self, source_id: str, audio_chunks: AsyncIterator[bytes]
    ) -> AsyncIterator[dict[str, object]]: ...


def source_side(source_id: str) -> ConversationParticipantSide:
    if source_id == "microphone":
        return ConversationParticipantSide.SALES_REP
    return ConversationParticipantSide.CUSTOMER


def parse_transcript_event(
    source_id: str, event: dict[str, object]
) -> TranscriptUpdate | None:
    event_type = event.get("type")
    item_id = event.get("item_id")
    is_delta = event_type == "conversation.item.input_audio_transcription.delta"
    text = event.get("delta") if is_delta else event.get("transcript")
    if not isinstance(item_id, str) or not isinstance(text, str) or not text.strip():
        return None
    return TranscriptUpdate(
        source_id=source_id,
        item_id=item_id,
        side=source_side(source_id),
        text=text,
        final=event_type == "conversation.item.input_audio_transcription.completed",
    )


async def stream_updates(
    source_id: str,
    events: AsyncIterator[dict[str, object]],
    persist_final: Callable[[TranscriptUpdate], Awaitable[None]],
) -> AsyncIterator[TranscriptUpdate]:
    state = TranscriptState()
    async for event in events:
        update = parse_transcript_event(source_id, event)
        if update is None:
            continue
        accepted = state.apply(update)
        if accepted is None:
            continue
        if accepted.final:
            await persist_final(accepted)
        yield accepted
