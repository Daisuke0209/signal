import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import patch

from signal_api.config import Settings
from signal_api.transcription import COMPLETED
from signal_api.transcription_provider import OpenAIProvider


class Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def __aiter__(self) -> "Socket":
        return self

    async def __anext__(self) -> str:
        return await self.incoming.get()


async def next_provider_event(
    events: AsyncIterator[dict[str, object]],
) -> dict[str, object]:
    return await anext(events)


def test_finish_waits_until_final_consumer_has_persisted() -> None:
    async def run() -> None:
        socket = Socket()
        with patch(
            "signal_api.transcription_provider.get_settings",
            return_value=Settings(database_url="unused"),
        ):
            provider = OpenAIProvider(socket)  # type: ignore[arg-type]
        await provider.send_audio(b"\xd0\x07" * 480)
        finishing = asyncio.create_task(provider.finish())
        await asyncio.sleep(0)
        assert socket.sent[-1]["type"] == "input_audio_buffer.commit"
        assert not finishing.done()
        events = provider.events()
        await socket.incoming.put(
            json.dumps({"type": COMPLETED, "item_id": "1", "transcript": "最後"})
        )
        assert (await anext(events))["transcript"] == "最後"
        assert not finishing.done()  # consumer has not resumed after persistence yet
        next_event = asyncio.create_task(next_provider_event(events))
        await finishing
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)

    asyncio.run(run())


def test_finish_silence_never_commits() -> None:
    async def run() -> None:
        socket = Socket()
        with patch(
            "signal_api.transcription_provider.get_settings",
            return_value=Settings(database_url="unused"),
        ):
            provider = OpenAIProvider(socket)  # type: ignore[arg-type]
        await provider.send_audio(bytes(48000))
        await provider.finish()
        assert socket.sent == []

    asyncio.run(run())
