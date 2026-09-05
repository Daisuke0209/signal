"""Short synchronous transactions, called in a worker thread by the WS boundary."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.conversations import ConversationMessageResponse
from signal_api.database import SessionLocal
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationStatus,
    Membership,
    TranscriptionItem,
    TranscriptionSession,
)
from signal_api.session_store import get_valid_session
from signal_api.transcription import Source, TranscriptionFailure, TranscriptUpdate


def authorize(db: Session, token: str, conversation_id: uuid.UUID) -> Conversation:
    session = get_valid_session(db, token)
    if session is None:
        raise TranscriptionFailure("authentication_required")
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None:
        raise TranscriptionFailure("conversation_unavailable")
    if (
        db.get(
            Membership,
            {
                "organization_id": conversation.organization_id,
                "user_id": session.user_id,
            },
        )
        is None
    ):
        raise TranscriptionFailure("conversation_unavailable")
    if conversation.status is not ConversationStatus.ACTIVE:
        raise TranscriptionFailure("conversation_ended")
    return conversation


def open_session(token: str, conversation_id: uuid.UUID, source: Source) -> uuid.UUID:
    with SessionLocal() as db:
        authorize(db, token, conversation_id)
        session = TranscriptionSession(conversation_id=conversation_id, source=source)
        db.add(session)
        db.commit()
        return session.id


def check_access(token: str, conversation_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        authorize(db, token, conversation_id)


def close_session(session_id: uuid.UUID, status: str) -> None:
    with SessionLocal() as db:
        session = db.get(TranscriptionSession, session_id)
        if session:
            session.status = status
            db.commit()


def persist_final(
    token: str, session_id: uuid.UUID, update: TranscriptUpdate
) -> dict[str, object] | None:
    if not update.final:
        raise ValueError("Only final transcripts can be persisted")
    with SessionLocal() as db:
        session = db.get(TranscriptionSession, session_id)
        if (
            session is None
            or session.status != "active"
            or session.source != update.source_id
        ):
            raise TranscriptionFailure("session_unavailable")
        authorize(db, token, session.conversation_id)
        existing = db.get(
            TranscriptionItem, {"session_id": session_id, "item_id": update.item_id}
        )
        message = (
            db.get(ConversationMessage, existing.message_id)
            if existing and existing.message_id
            else None
        )
        if existing and message is None:
            return None
        if message is None:
            # Empty final still consumes the provider item ID, without an empty message.
            if not update.text.strip():
                db.add(TranscriptionItem(session_id=session_id, item_id=update.item_id))
                db.commit()
                return None
            label = (
                "自分（マイク）"
                if update.source_id == "microphone"
                else "通話相手（共有音声）"
            )
            participant = db.scalar(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == session.conversation_id,
                    ConversationParticipant.speaker_label == label,
                )
            )
            if participant is None:
                participant = ConversationParticipant(
                    conversation_id=session.conversation_id,
                    speaker_label=label,
                    side=update.side,
                )
                db.add(participant)
                db.flush()
            if participant.side != update.side:
                raise TranscriptionFailure("speaker_conflict")
            latest = db.scalar(
                select(func.max(ConversationMessage.sequence_number)).where(
                    ConversationMessage.conversation_id == session.conversation_id
                )
            )
            message = ConversationMessage(
                conversation_id=session.conversation_id,
                participant_id=participant.id,
                sequence_number=(latest or 0) + 1,
                content=update.text.strip(),
            )
            db.add(message)
            db.flush()
            db.add(
                TranscriptionItem(
                    session_id=session_id, item_id=update.item_id, message_id=message.id
                )
            )
            db.commit()
        participant = db.get(ConversationParticipant, message.participant_id)
        assert participant is not None
        return ConversationMessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            participant_id=participant.id,
            speaker_label=participant.speaker_label,
            side=participant.side,
            sequence_number=message.sequence_number,
            content=message.content,
        ).model_dump(mode="json")
