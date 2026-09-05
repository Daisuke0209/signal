import uuid

from sqlalchemy import delete, func, select

from signal_api.database import SessionLocal
from signal_api.models import (
    Conversation,
    ConversationMessage,
    ConversationParticipant,
    ConversationParticipantSide,
    ConversationStatus,
    Organization,
    User,
)


def test_conversation_messages_are_persisted_in_order_and_cascade_deleted() -> None:
    unique_id = uuid.uuid4()

    with SessionLocal() as db:
        organization = Organization(
            name="Conversation Test Organization",
            slug=f"conversation-test-{unique_id}",
        )
        user = User(
            name="Conversation Test User",
            email=f"conversation-test-{unique_id}@signal.local",
            password_hash="not-used-in-this-test",
        )
        db.add_all([organization, user])
        db.flush()

        conversation = Conversation(
            organization_id=organization.id,
            created_by_user_id=user.id,
        )
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id

        customer_one = ConversationParticipant(
            conversation_id=conversation_id,
            side=ConversationParticipantSide.CUSTOMER,
            speaker_label="speaker_1",
        )
        customer_two = ConversationParticipant(
            conversation_id=conversation_id,
            side=ConversationParticipantSide.CUSTOMER,
            speaker_label="speaker_2",
        )
        sales_rep_one = ConversationParticipant(
            conversation_id=conversation_id,
            side=ConversationParticipantSide.SALES_REP,
            speaker_label="speaker_3",
        )
        sales_rep_two = ConversationParticipant(
            conversation_id=conversation_id,
            side=ConversationParticipantSide.SALES_REP,
            speaker_label="speaker_4",
        )
        db.add_all([customer_one, customer_two, sales_rep_one, sales_rep_two])
        db.flush()

        db.add_all(
            [
                ConversationMessage(
                    conversation_id=conversation_id,
                    participant_id=sales_rep_two.id,
                    sequence_number=2,
                    content="現在はどのように管理されていますか？",
                ),
                ConversationMessage(
                    conversation_id=conversation_id,
                    participant_id=customer_one.id,
                    sequence_number=1,
                    content="案件管理に時間がかかっています。",
                ),
            ]
        )
        db.commit()

        try:
            stored_conversation = db.get(Conversation, conversation_id)
            assert stored_conversation is not None
            assert stored_conversation.organization_id == organization.id
            assert stored_conversation.created_by_user_id == user.id
            assert stored_conversation.status is ConversationStatus.ACTIVE

            participants = db.scalars(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id
                )
            ).all()
            assert len(participants) == 4
            assert {participant.speaker_label for participant in participants} == {
                "speaker_1",
                "speaker_2",
                "speaker_3",
                "speaker_4",
            }
            assert all(participant.display_name is None for participant in participants)

            messages = db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.sequence_number)
            ).all()
            assert [message.sequence_number for message in messages] == [1, 2]
            assert [message.participant_id for message in messages] == [
                customer_one.id,
                sales_rep_two.id,
            ]

            db.delete(stored_conversation)
            db.commit()

            message_count = db.scalar(
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
            )
            assert message_count == 0
            participant_count = db.scalar(
                select(func.count())
                .select_from(ConversationParticipant)
                .where(ConversationParticipant.conversation_id == conversation_id)
            )
            assert participant_count == 0
        finally:
            db.execute(delete(User).where(User.id == user.id))
            db.execute(delete(Organization).where(Organization.id == organization.id))
            db.commit()
