import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/dom";
import { startLiveTranscription } from "./live-transcription";

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  bufferedAmount = 0;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  onerror?: () => void;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; this.onclose?.(); });
  constructor(public url: URL) { Socket.instances.push(this); }
  event(event: object) { this.onmessage?.({ data: JSON.stringify(event) }); }
}
class Node {
  disconnect = vi.fn();
  connect = vi.fn(() => this);
}
class Worklet extends Node {
  static instances: Worklet[] = [];
  port = {
    onmessage: undefined as ((event: { data: unknown }) => void) | undefined,
    postMessage: vi.fn(() => this.port.onmessage?.({ data: "flushed" })),
  };
  constructor() { super(); Worklet.instances.push(this); }
}
class Context {
  static instances: Context[] = [];
  sampleRate = 24000;
  close = vi.fn(async () => {});
  resume = vi.fn(async () => {});
  audioWorklet = { addModule: vi.fn(async () => {}) };
  destination = new Node();
  createMediaStreamSource = vi.fn(() => new Node());
  constructor() { Context.instances.push(this); }
}
const capture = {
  displayStream: { getAudioTracks: () => [] },
  microphoneStream: { getAudioTracks: () => [] },
} as unknown as Parameters<typeof startLiveTranscription>[0];

beforeEach(() => {
  Socket.instances = []; Worklet.instances = []; Context.instances = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal("AudioWorkletNode", Worklet);
  vi.stubGlobal("MediaStream", class {});
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
async function begin() {
  const controller = new AbortController(), onTranscript = vi.fn(), onError = vi.fn();
  const opening = startLiveTranscription(capture, "conversation-1", controller.signal, onTranscript, onError);
  await waitFor(() => expect(Socket.instances).toHaveLength(2));
  Socket.instances.forEach((socket) => socket.event({ type: "ready" }));
  return { live: await opening, controller, onTranscript, onError };
}

describe("live transcription lifecycle", () => {
  it("sends sources separately and forwards partial/final before graceful stop", async () => {
    const { live, onTranscript } = await begin();
    expect(Socket.instances.map((s) => s.url.pathname.split("/").pop())).toEqual(["display", "microphone"]);
    const pcm = new ArrayBuffer(4800);
    Worklet.instances[0].port.onmessage?.({ data: pcm });
    expect(Socket.instances[0].send).toHaveBeenCalledWith(pcm);
    expect(Socket.instances[1].send).not.toHaveBeenCalled();
    Socket.instances[0].event({ type: "partial", text: "途中" });
    Socket.instances[0].event({ type: "final", text: "確定" });
    expect(onTranscript.mock.calls.map(([e]) => e.type)).toEqual(["partial", "final"]);
    const stopping = live.stop();
    await waitFor(() => expect(Socket.instances[0].send).toHaveBeenCalledWith('{"type":"stop"}'));
    expect(Context.instances[0].close).not.toHaveBeenCalled();
    Socket.instances.forEach((s) => s.event({ type: "stopped" }));
    await stopping;
    expect(Context.instances[0].close).toHaveBeenCalledOnce();
    expect(Worklet.instances.every((n) => n.disconnect.mock.calls.length === 1)).toBe(true);
  });
  it("closes both sockets on startup failure without exposing provider text", async () => {
    const onError = vi.fn();
    const opening = startLiveTranscription(capture, "id", new AbortController().signal, vi.fn(), onError);
    const rejected = expect(opening).rejects.toThrow("provider_error");
    await waitFor(() => expect(Socket.instances).toHaveLength(2));
    Socket.instances[0].event({ type: "error", code: "provider_error", message: "secret" });
    await rejected;
    expect(Socket.instances.every((s) => s.close.mock.calls.length === 1)).toBe(true);
    expect(Context.instances[0].close).toHaveBeenCalledOnce();
  });
  it("cleans up abort during handshake and ignores stale transcripts", async () => {
    const controller = new AbortController(), callback = vi.fn();
    const opening = startLiveTranscription(capture, "id", controller.signal, callback, vi.fn());
    const rejected = expect(opening).rejects.toThrow();
    await waitFor(() => expect(Socket.instances).toHaveLength(2));
    controller.abort();
    await rejected;
    Socket.instances[0].event({ type: "partial", text: "stale" });
    expect(callback).not.toHaveBeenCalled();
    expect(Context.instances[0].close).toHaveBeenCalledOnce();
  });
  it("bounds queued audio and stops both sources on disconnect", async () => {
    const { onError } = await begin();
    Socket.instances[0].bufferedAmount = 240001;
    Worklet.instances[0].port.onmessage?.({ data: new ArrayBuffer(4800) });
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toContain("接続が遅い");
    expect(Socket.instances.every((s) => s.close.mock.calls.length === 1)).toBe(true);
  });
  it("times out final acknowledgement and releases audio resources", async () => {
    const { live } = await begin();
    vi.useFakeTimers();
    const stopping = live.stop();
    const rejected = expect(stopping).rejects.toThrow("stop_timeout");
    await vi.advanceTimersByTimeAsync(15000);
    await rejected;
    expect(Context.instances[0].close).toHaveBeenCalledOnce();
  });
});
