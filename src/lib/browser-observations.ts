const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Reference =
  | { kind: "suggestion"; run_id: string; revision: number }
  | { kind: "transcript_partial" | "transcript_final"; session_id: string };

// Two animation frames measure a paint opportunity after React's commit. This
// is diagnostic client-reported timing, not proof that a human saw the screen.
export function observePaint(
  conversationId: string,
  reference: Reference,
  receivedAt: number,
): () => void {
  let frame = requestAnimationFrame(() => {
    frame = requestAnimationFrame(() => {
      if (document.visibilityState !== "visible") return;
      const duration = performance.now() - receivedAt;
      if (!Number.isFinite(duration) || duration < 0 || duration > 60_000) return;
      // Only explicitly named IDs/timing fields leave the browser. Never spread
      // a transcript, suggestion, error or source object into this payload.
      const body = reference.kind === "suggestion"
        ? { kind: reference.kind, run_id: reference.run_id, revision: reference.revision }
        : { kind: reference.kind, session_id: reference.session_id };
      void fetch(`${API_URL}/conversations/${conversationId}/observations`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, receive_to_paint_ms: duration }),
      }).catch(() => { /* Optional telemetry never changes product state. */ });
    });
  });
  return () => cancelAnimationFrame(frame);
}

const received = new WeakMap<object, number>();
export function recordReceived(value: object): void {
  received.set(value, performance.now());
}
export function receivedAt(value: object): number | undefined {
  return received.get(value);
}
