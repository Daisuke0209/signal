"""Single-process orchestration with durable queue and guarded publication."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.documents import search_document_pages
from signal_api.domain_traces import span, trace, trace_context
from signal_api.models import (
    ConfirmationItemStatus,
    ConfirmationSource,
    Conversation,
    ConversationConfirmationItem,
    ConversationDocument,
    ConversationMessage,
    ConversationParticipant,
    ConversationStatus,
    Document,
    DocumentProcessingStatus,
    SuggestionErrorCode,
    SuggestionKind,
    SuggestionRun,
    SuggestionRunStatus,
    confirmation_item_key,
)
from signal_api.suggestion_agent import (
    AgentFailure,
    AgentOutput,
    AgentPhase,
    Evidence,
    SuggestionAgent,
)
from signal_api.suggestion_events import events
from signal_api.suggestions import (
    SuggestionDraft,
    complete_suggestion_run,
    fail_suggestion_run,
    latest_suggestions,
    start_suggestion_run,
)

logger = logging.getLogger("signal.suggestions")


def transaction[T](operation: Callable[[Session], T]) -> T:
    with SessionLocal() as db:
        result = operation(db)
        db.commit()
        return result


class SuggestionRuntime:
    def __init__(self, agent: SuggestionAgent) -> None:
        self.agent = agent
        self.tasks: dict[uuid.UUID, tuple[int, asyncio.Task[None]]] = {}
        self.capacity = asyncio.Semaphore(4)

    async def start(self) -> None:
        events.loop = asyncio.get_running_loop()
        events.on_input = self.kick

        # A restart invalidates incomplete provider calls, and resumes queued inputs.
        def recover(db: Session) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
            runs = list(
                db.scalars(
                    select(SuggestionRun)
                    .where(
                        SuggestionRun.status.in_(
                            [SuggestionRunStatus.RUNNING, SuggestionRunStatus.QUEUED]
                        )
                    )
                    .order_by(SuggestionRun.generation)
                )
            )
            pending = []
            for run in runs:
                if run.status is SuggestionRunStatus.RUNNING:
                    fail_suggestion_run(db, run.id, SuggestionErrorCode.INTERRUPTED)
                else:
                    pending.append((run.conversation_id, run.id, run.generation))
            return pending

        for cid, rid, generation in await asyncio.to_thread(transaction, recover):
            self.kick(cid, rid, generation)

    def kick(self, cid: uuid.UUID, rid: uuid.UUID, generation: int) -> None:
        previous = self.tasks.get(cid)
        if previous:
            if previous[0] >= generation:
                return
            previous[1].cancel()
        with trace_context(cid, run_id=rid, generation=generation):
            trace("suggestion.queued")
            task = asyncio.create_task(self.work(cid, rid))
        self.tasks[cid] = (generation, task)

        def finished(done: asyncio.Task[None]) -> None:
            if self.tasks.get(cid, (None, None))[1] is done:
                self.tasks.pop(cid, None)
            if not done.cancelled() and done.exception() is not None:
                logger.error("suggestion_state_persistence_failed")

        task.add_done_callback(finished)

    async def close(self) -> None:
        events.on_input = None
        events.loop = None
        tasks = [value[1] for value in self.tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def publish(self, cid: uuid.UUID) -> None:
        snapshot = await asyncio.to_thread(
            transaction, lambda db: latest_suggestions(db, cid).model_dump(mode="json")
        )
        events.publish(cid, snapshot)

    def prepare(
        self, db: Session, cid: uuid.UUID, rid: uuid.UUID
    ) -> tuple[str, uuid.UUID, set[uuid.UUID]] | None:
        conversation = db.scalar(
            select(Conversation).where(Conversation.id == cid).with_for_update()
        )
        if conversation is None:
            return None
        runs = list(
            db.scalars(
                select(SuggestionRun)
                .where(SuggestionRun.conversation_id == cid)
                .order_by(SuggestionRun.generation.desc())
            )
        )
        if not runs or runs[0].id != rid:
            return None
        for old in runs[1:]:
            if old.status in (SuggestionRunStatus.QUEUED, SuggestionRunStatus.RUNNING):
                fail_suggestion_run(db, old.id, SuggestionErrorCode.INTERRUPTED)
        run = runs[0]
        if conversation.status is not ConversationStatus.ACTIVE:
            if run.status in (SuggestionRunStatus.QUEUED, SuggestionRunStatus.RUNNING):
                fail_suggestion_run(db, rid, SuggestionErrorCode.INTERRUPTED)
            return None
        if run.status is not SuggestionRunStatus.QUEUED:
            return None
        start_suggestion_run(db, rid)
        rows = db.execute(
            select(ConversationMessage, ConversationParticipant)
            .join(
                ConversationParticipant,
                ConversationParticipant.id == ConversationMessage.participant_id,
            )
            .where(
                ConversationMessage.conversation_id == cid,
                ConversationMessage.sequence_number <= run.input_sequence_number,
            )
            .order_by(ConversationMessage.sequence_number.desc())
            .limit(12)
        ).all()
        selected_ids = set(
            db.scalars(
                select(Document.id)
                .join(ConversationDocument)
                .where(
                    ConversationDocument.conversation_id == conversation.id,
                    Document.organization_id == conversation.organization_id,
                    Document.processing_status == DocumentProcessingStatus.READY,
                )
            )
        )
        context = json.dumps(
            {
                "documents": "available" if selected_ids else "no_searchable_documents",
                "conversation": [
                    {
                        "id": str(message.id),
                        "side": participant.side.value,
                        "text": message.content[:1500],
                    }
                    for message, participant in reversed(rows)
                ],
                "confirmation_items": [
                    {
                        "id": str(item.id),
                        "content": item.content,
                        "status": item.status,
                    }
                    for item in db.scalars(
                        select(ConversationConfirmationItem).where(
                            ConversationConfirmationItem.conversation_id == cid
                        )
                    )
                ],
            },
            ensure_ascii=False,
        )
        return context, conversation.organization_id, selected_ids

    def phase(
        self, db: Session, cid: uuid.UUID, rid: uuid.UUID, phase: AgentPhase
    ) -> None:
        run = db.scalar(
            select(SuggestionRun).where(SuggestionRun.id == rid).with_for_update()
        )
        if (
            run
            and run.status is SuggestionRunStatus.RUNNING
            and run.phase != phase.value
        ):
            run.phase = phase.value
            run.revision += 1

    def finish(
        self,
        db: Session,
        cid: uuid.UUID,
        rid: uuid.UUID,
        output: AgentOutput,
        evidence: dict[str, Evidence],
    ) -> None:
        conversation = db.scalar(
            select(Conversation).where(Conversation.id == cid).with_for_update()
        )
        run = db.get(SuggestionRun, rid)
        if (
            conversation is None
            or run is None
            or run.status is not SuggestionRunStatus.RUNNING
        ):
            return
        latest = db.scalar(
            select(func.max(ConversationMessage.sequence_number)).where(
                ConversationMessage.conversation_id == cid
            )
        )
        generation = db.scalar(
            select(func.max(SuggestionRun.generation)).where(
                SuggestionRun.conversation_id == cid
            )
        )
        if (
            conversation.status is not ConversationStatus.ACTIVE
            or latest != run.input_sequence_number
            or generation != run.generation
        ):
            fail_suggestion_run(db, rid, SuggestionErrorCode.INTERRUPTED)
            return
        origin_message_id = db.scalar(
            select(ConversationMessage.id).where(
                ConversationMessage.conversation_id == cid,
                ConversationMessage.sequence_number == run.input_sequence_number,
            )
        )
        for suggestion in output.suggestions:
            if suggestion.kind not in (
                SuggestionKind.CONFIRMATION.value,
                SuggestionKind.QUESTION.value,
            ):
                continue
            normalized_content = confirmation_item_key(suggestion.content)
            existing = db.scalar(
                select(ConversationConfirmationItem).where(
                    ConversationConfirmationItem.conversation_id == cid,
                    ConversationConfirmationItem.normalized_content
                    == normalized_content,
                )
            )
            if existing is None:
                db.add(
                    ConversationConfirmationItem(
                        conversation_id=cid,
                        content=suggestion.content,
                        normalized_content=normalized_content,
                        origin_message_id=origin_message_id,
                    )
                )
        for match in output.confirmation_evidence:
            item = db.scalar(
                select(ConversationConfirmationItem)
                .where(
                    ConversationConfirmationItem.id == match.confirmation_item_id,
                    ConversationConfirmationItem.conversation_id == cid,
                )
                .with_for_update()
            )
            message = db.scalar(
                select(ConversationMessage).where(
                    ConversationMessage.id == match.message_id,
                    ConversationMessage.conversation_id == cid,
                )
            )
            if (
                item is not None
                and message is not None
                and item.status == ConfirmationItemStatus.OPEN.value
                and item.confirmation_source != ConfirmationSource.MANUAL.value
            ):
                item.status = ConfirmationItemStatus.CONFIRMED
                item.confirmation_source = ConfirmationSource.AUTO
                item.evidence_message_id = message.id
                item.version += 1
        complete_suggestion_run(
            db,
            rid,
            [
                SuggestionDraft(
                    kind=SuggestionKind(item.kind),
                    content=item.content,
                    sources=[evidence[key] for key in dict.fromkeys(item.evidence_ids)],
                )
                for item in output.suggestions
            ],
        )

    async def fail(self, cid: uuid.UUID, rid: uuid.UUID, code: str) -> None:
        def mark(db: Session) -> None:
            run = db.scalar(
                select(SuggestionRun).where(SuggestionRun.id == rid).with_for_update()
            )
            if run and run.status in (
                SuggestionRunStatus.QUEUED,
                SuggestionRunStatus.RUNNING,
            ):
                fail_suggestion_run(db, rid, SuggestionErrorCode(code))

        await asyncio.to_thread(transaction, mark)
        trace(
            "suggestion.failure",
            outcome="failed",
            error_code=code,
            retryable=code in {"timeout", "provider_unavailable", "generation_failed"},
        )
        await self.publish(cid)

    async def work(self, cid: uuid.UUID, rid: uuid.UUID) -> None:
        try:
            queued = time.perf_counter()
            await self.publish(cid)
            async with self.capacity:
                trace(
                    "suggestion.queue_wait",
                    duration_ms=(time.perf_counter() - queued) * 1000,
                )
                with span("suggestion.prepare"):
                    prepared = await asyncio.to_thread(
                        transaction, lambda db: self.prepare(db, cid, rid)
                    )
                await self.publish(cid)
                if prepared is None:
                    return
                context, org_id, selected_ids = prepared

                async def report(phase: AgentPhase) -> None:
                    await asyncio.to_thread(
                        transaction, lambda db: self.phase(db, cid, rid, phase)
                    )
                    await self.publish(cid)

                async def search(query: str) -> list[Evidence]:
                    def lookup(db: Session) -> list[Evidence]:
                        return [
                            Evidence.model_validate(item.model_dump(exclude={"score"}))
                            for item in search_document_pages(
                                db, org_id, query, document_ids=selected_ids, limit=5
                            )
                        ]

                    with span("suggestion.search"):
                        result = await asyncio.to_thread(transaction, lookup)
                    trace("suggestion.search_results", count=len(result))
                    return result

                with span("suggestion.generate"):
                    output, evidence = await self.agent.generate(
                        context, search if selected_ids else None, report
                    )
                with span("suggestion.persist"):
                    await asyncio.to_thread(
                        transaction,
                        lambda db: self.finish(db, cid, rid, output, evidence),
                    )
                await self.publish(cid)
        except asyncio.CancelledError:
            await self.fail(cid, rid, "interrupted")
            raise
        except AgentFailure as error:
            await self.fail(cid, rid, error.code)
        except Exception:
            # No traceback/provider body/conversation/PDF content in logs.
            logger.error("suggestion_generation_failed", extra={"run_id": str(rid)})
            await self.fail(cid, rid, "generation_failed")


def create_agent(client: httpx.AsyncClient) -> SuggestionAgent:
    settings = get_settings()
    return SuggestionAgent(
        client,
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else "",
        settings.suggestion_model,
        settings.suggestion_timeout_seconds,
    )
