import { afterEach, describe, expect, it, vi } from "vitest";

import { connectSuggestionEvents, getLatestSuggestions } from "./suggestions-api";

class EventSourceMock {
  listeners = new Map<string, ((event: Event) => void)[]>();
  close = vi.fn();

  constructor(
    readonly url: string,
    readonly options: EventSourceInit,
  ) {}

  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  emit(type: string, data = "") {
    const event = new MessageEvent(type, { data });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

afterEach(() => vi.unstubAllGlobals());

describe("suggestion API", () => {
  it("requests the authenticated latest snapshot", async () => {
    const state = { conversation_id: "conversation-1", latest_run: null };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(state), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getLatestSuggestions("conversation-1")).resolves.toEqual(state);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/conversations/conversation-1/suggestions",
      { credentials: "include" },
    );
  });

  it("uses a credentialed EventSource and forwards valid state events", () => {
    class CapturingEventSource extends EventSourceMock {
      static source: EventSourceMock | undefined;

      constructor(url: string, options: EventSourceInit) {
        super(url, options);
        CapturingEventSource.source = this;
      }
    }
    vi.stubGlobal(
      "EventSource",
      CapturingEventSource,
    );
    const onState = vi.fn();
    const onError = vi.fn();
    const onAccessRevoked = vi.fn();

    const disconnect = connectSuggestionEvents(
      "conversation-1",
      onState,
      onError,
      onAccessRevoked,
    );

    const source = CapturingEventSource.source;
    expect(source?.url).toBe(
      "http://localhost:8000/conversations/conversation-1/suggestions/events",
    );
    expect(source?.options).toEqual({ withCredentials: true });
    source?.emit(
      "suggestion_state",
      JSON.stringify({ conversation_id: "conversation-1", latest_run: null }),
    );
    source?.emit("error");
    source?.emit("access_revoked");
    expect(onState).toHaveBeenCalledWith({
      conversation_id: "conversation-1",
      latest_run: null,
    });
    expect(onError).toHaveBeenCalledOnce();
    expect(onAccessRevoked).toHaveBeenCalledOnce();
    expect(source?.close).toHaveBeenCalledOnce();

    disconnect();
    expect(source?.close).toHaveBeenCalledTimes(2);
  });
});
