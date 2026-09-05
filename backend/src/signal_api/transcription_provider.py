"""OpenAI transport. Audio and raw provider errors are never logged."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from websockets.asyncio.client import ClientConnection, connect

from signal_api.audio_turns import AudioTurns
from signal_api.config import get_settings
from signal_api.transcription import COMPLETED, TranscriptionFailure


class Provider(Protocol):
    async def send_audio(self, audio: bytes) -> None: ...
    async def finish(self) -> None: ...
    def events(self) -> AsyncIterator[dict[str, object]]: ...


class OpenAIProvider:
    def __init__(self, socket: ClientConnection):
        self.socket = socket
        self.turns = AudioTurns(get_settings().transcription_energy_threshold)
        self.pending = 0
        self.settled = asyncio.Event()
        self.settled.set()

    async def _send(self, frames: list[bytes | None]) -> None:
        for frame in frames:
            if frame is None:
                self.pending += 1
                self.settled.clear()
                await self.socket.send(
                    json.dumps({"type": "input_audio_buffer.commit"})
                )
            else:
                await self.socket.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(frame).decode(),
                        }
                    )
                )

    async def send_audio(self, audio: bytes) -> None:
        await self._send(self.turns.feed(audio))

    async def finish(self) -> None:
        await self._send(self.turns.finish())
        async with asyncio.timeout(12):
            await self.settled.wait()

    async def events(self) -> AsyncIterator[dict[str, object]]:
        async for raw in self.socket:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise TranscriptionFailure("provider_error")
            event_type = event.get("type")
            if event_type in (
                "error",
                "conversation.item.input_audio_transcription.failed",
            ):
                raise TranscriptionFailure("provider_error")
            # Yield before waking finish: persistence must finish before 'stopped'.
            yield event
            if event_type == COMPLETED:
                self.pending = max(0, self.pending - 1)
                if self.pending == 0:
                    self.settled.set()
        raise TranscriptionFailure("provider_disconnected")


@asynccontextmanager
async def connect_provider() -> AsyncIterator[Provider]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise TranscriptionFailure("transcription_unavailable")
    # No provider key or ephemeral credential is exposed to the browser.
    async with connect(
        "wss://api.openai.com/v1/realtime?intent=transcription",
        additional_headers={
            "Authorization": "Bearer " + settings.openai_api_key.get_secret_value()
        },
        open_timeout=10,
        close_timeout=2,
        max_size=1_000_000,
        max_queue=16,
    ) as socket:
        await socket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "transcription": {
                                    "model": settings.transcription_model,
                                    "languages": ["ja"],
                                    "delay": "low",
                                },
                                "turn_detection": None,
                            }
                        },
                    },
                }
            )
        )
        async with asyncio.timeout(10):
            while True:
                event = json.loads(await socket.recv())
                if event.get("type") == "error":
                    raise TranscriptionFailure("provider_error")
                if event.get("type") == "session.updated":
                    break
        yield OpenAIProvider(socket)
