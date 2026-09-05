from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from signal_api.auth import router as auth_router
from signal_api.config import get_settings
from signal_api.conversations import router as conversations_router
from signal_api.database import get_db_session
from signal_api.documents import router as documents_router
from signal_api.domain_traces import configure_domain_logging
from signal_api.observability import (
    RequestLoggingMiddleware,
    configure_request_logging,
)
from signal_api.suggestion_runtime import SuggestionRuntime, create_agent
from signal_api.suggestion_stream import router as suggestion_stream_router
from signal_api.suggestions import router as suggestions_router
from signal_api.trace_routes import router as trace_router
from signal_api.transcription_routes import router as transcription_router

settings = get_settings()

configure_request_logging()
configure_domain_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not get_settings().suggestions_enabled:
        yield
        return
    async with httpx.AsyncClient(
        timeout=get_settings().suggestion_timeout_seconds
    ) as client:
        runtime = SuggestionRuntime(create_agent(client))
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()


app = FastAPI(title="Signal API", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(suggestions_router)
app.include_router(suggestion_stream_router)
app.include_router(transcription_router)
app.include_router(trace_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

DatabaseSession = Annotated[Session, Depends(get_db_session)]


class HealthResponse(BaseModel):
    status: str
    database: str


@app.get("/health", response_model=HealthResponse)
def health(db: DatabaseSession) -> HealthResponse:
    database_name = db.execute(text("SELECT current_database()")).scalar_one()
    return HealthResponse(status="ok", database=str(database_name))
