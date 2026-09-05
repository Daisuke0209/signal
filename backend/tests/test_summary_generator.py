import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from signal_api.config import get_settings
from signal_api.summary_generator import SummaryFailure, generate_summary


@pytest.mark.parametrize("mode", ["success", "http_error", "invalid", "refusal"])
def test_summary_boundary_uses_only_transcript_and_normalizes_failures(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "suggestions_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key-never-log"))

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["input"] == "fictional transcript"
        assert "tools" not in body
        if mode == "http_error":
            return httpx.Response(429, text="private-provider-body")
        content = {
            "type": "output_text",
            "text": json.dumps(
                {
                    "overview": "架空の商談",
                    "decisions": [],
                    "unresolved": [],
                    "next_actions": [],
                }
            ),
        }
        if mode == "invalid":
            content["text"] = "private-invalid-json"
        if mode == "refusal":
            content = {"type": "refusal", "refusal": "private-refusal"}
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"type": "message", "content": [content]}],
            },
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        monkeypatch.setattr(
            "signal_api.summary_generator.httpx.AsyncClient", lambda **kwargs: client
        )
        if mode == "success":
            assert (
                await generate_summary("fictional transcript")
            ).overview == "架空の商談"
        else:
            with pytest.raises(SummaryFailure) as failure:
                await generate_summary("fictional transcript")
            assert str(failure.value) in {"provider_unavailable", "generation_failed"}
            assert "private" not in str(failure.value)

    asyncio.run(scenario())
