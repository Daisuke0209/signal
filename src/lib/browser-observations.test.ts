import { afterEach, describe, expect, it, vi } from "vitest";
import { observePaint, receivedAt, recordReceived } from "./browser-observations";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function frames() {
  let next = 0;
  const pending = new Map<number, FrameRequestCallback>();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    pending.set(++next, callback); return next;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => pending.delete(id));
  return () => { const entries = [...pending.values()]; pending.clear(); entries.forEach(fn => fn(0)); };
}

describe("content-free browser timing", () => {
  it("waits for a paint opportunity and sends only allowed fields", async () => {
    const flush = frames();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(performance, "now").mockReturnValue(150);
    const fetcher = vi.fn().mockResolvedValue({ ok: true }); vi.stubGlobal("fetch", fetcher);
    const reference = { kind: "suggestion" as const, run_id: "run", revision: 4, content: "private" };
    observePaint("conversation", reference, 100);
    flush(); expect(fetcher).not.toHaveBeenCalled();
    flush(); expect(fetcher).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({kind: "suggestion", run_id: "run", revision: 4, receive_to_paint_ms: 50});
  });
  it("cancels stale observations and ignores hidden screens", () => {
    const flush = frames(); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const cancel = observePaint("old", {kind: "transcript_final", session_id: "s"}, 0);
    flush(); cancel(); flush(); expect(fetcher).not.toHaveBeenCalled();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    observePaint("new", {kind: "transcript_partial", session_id: "s"}, 0);
    flush(); flush(); expect(fetcher).not.toHaveBeenCalled();
  });
  it("keeps receive timing outside serializable application content", () => {
    vi.spyOn(performance, "now").mockReturnValue(12);
    const value = { text: "private" }; recordReceived(value);
    expect(receivedAt(value)).toBe(12); expect(Object.keys(value)).toEqual(["text"]);
  });
});
