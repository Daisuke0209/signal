import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest

from signal_api.suggestion_agent import (
    AgentFailure,
    AgentPhase,
    Evidence,
    SuggestionAgent,
)


def answer(evidence_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "message",
        "content": [
            {
                "type": "output_text",
                "text": json.dumps(
                    {
                        "suggestions": [
                            {
                                "kind": "response",
                                "content": "SSOの利用条件を確認します。",
                                "evidence_ids": evidence_ids or [],
                            }
                        ]
                    }
                ),
            }
        ],
    }


def tool_call(query: str = "SSO") -> dict[str, Any]:
    return {
        "type": "function_call",
        "name": "search_documents",
        "call_id": "call_1",
        "arguments": json.dumps({"query": query}),
    }


def test_tool_loop_preserves_reasoning_and_only_returns_retrieved_evidence() -> None:
    async def scenario() -> None:
        requests: list[dict[str, Any]] = []
        phases: list[AgentPhase] = []
        evidence = Evidence(
            document_id=uuid.uuid4(),
            document_name="仕様.pdf",
            page_number=2,
            excerpt="SSOはBusinessプランで利用できます。",
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            output = (
                [{"type": "reasoning", "id": "rs_1", "summary": []}, tool_call()]
                if len(requests) == 1
                else [answer(["s1p1"])]
            )
            return httpx.Response(200, json={"status": "completed", "output": output})

        async def search(query: str) -> list[Evidence]:
            assert query == "SSO"
            return [evidence]

        async def phase(value: AgentPhase) -> None:
            phases.append(value)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result, sources = await SuggestionAgent(client, "test-only").generate(
                "顧客: SSOは使えますか？", search, phase
            )
        assert result.suggestions[0].evidence_ids == ["s1p1"]
        assert sources == {"s1p1": evidence}
        assert phases == [
            AgentPhase.GENERATING,
            AgentPhase.SEARCHING,
            AgentPhase.GENERATING,
        ]
        assert requests[0]["store"] is False
        assert requests[1]["input"][1]["type"] == "reasoning"
        assert requests[1]["input"][-1]["type"] == "function_call_output"
        assert "仕様.pdf" in requests[1]["input"][-1]["output"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "output",
    [
        [answer(["invented"])],
        [tool_call()],
        [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
    ],
)
def test_unavailable_tool_unknown_evidence_and_refusal_fail_closed(
    output: list[Any],
) -> None:
    async def scenario() -> None:
        async def phase(value: AgentPhase) -> None:
            pass

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"status": "completed", "output": output}
                )
            )
        ) as client:
            with pytest.raises(AgentFailure, match="generation_failed"):
                await SuggestionAgent(client, "test-only").generate("会話", None, phase)

    asyncio.run(scenario())


def test_search_budget_is_bounded_and_third_tool_call_is_rejected() -> None:
    async def scenario() -> None:
        count = 0
        searches = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal count
            count += 1
            if count == 3:
                assert json.loads(request.content)["tools"] == []
            return httpx.Response(
                200, json={"status": "completed", "output": [tool_call()]}
            )

        async def search(query: str) -> list[Evidence]:
            nonlocal searches
            searches += 1
            return []

        async def phase(value: AgentPhase) -> None:
            pass

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(AgentFailure):
                await SuggestionAgent(client, "test-only").generate(
                    "会話", search, phase
                )
        assert count == 3
        assert searches == 2

    asyncio.run(scenario())


def test_timeout_and_provider_error_do_not_expose_response_body() -> None:
    async def scenario() -> None:
        async def phase(value: AgentPhase) -> None:
            pass

        async def slow(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(10)
            return httpx.Response(200)

        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            with pytest.raises(AgentFailure, match="timeout"):
                await SuggestionAgent(
                    client, "test-only", timeout_seconds=0.01
                ).generate("会話", None, phase)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, text="private-provider-error")
            )
        ) as client:
            with pytest.raises(AgentFailure) as caught:
                await SuggestionAgent(client, "test-only").generate("会話", None, phase)
            assert str(caught.value) == "provider_unavailable"

    asyncio.run(scenario())
