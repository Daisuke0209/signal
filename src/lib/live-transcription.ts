import { recordReceived } from "./browser-observations";
import type { AudioCapture } from "./audio-capture";
import type { ConversationDetail } from "./auth-api";

export type Source = "display" | "microphone";
export type TranscriptEvent = {
  type: "partial" | "final";
  source: Source;
  item_id: string;
  session_id?: string;
  text: string;
  side: "sales_rep" | "customer";
  message: ConversationDetail["messages"][number] | null;
};
export type LiveTranscription = { abort: () => void; stop: () => Promise<void> };

const SAFE_ERRORS: Record<string, string> = {
  authentication_required: "ログインの有効期限が切れました。再ログインしてください。",
  conversation_ended: "この商談は終了しました。文字起こしを停止しました。",
  conversation_unavailable: "この商談を利用できません。",
  transcription_unavailable: "文字起こしの接続設定がありません。",
  network_slow: "接続が遅いため文字起こしを停止しました。接続を確認して再開してください。",
};
export function transcriptionError(code: string): string {
  return SAFE_ERRORS[code] ?? "文字起こしが中断しました。確定済みの発言は保存されています。接続を確認して再開してください。";
}

export async function startLiveTranscription(
  capture: AudioCapture,
  conversationId: string,
  signal: AbortSignal,
  onTranscript: (event: TranscriptEvent) => void,
  onError: (message: string) => void,
): Promise<LiveTranscription> {
  const context = new AudioContext({ sampleRate: 24000 });
  const sockets: WebSocket[] = [];
  const nodes: AudioNode[] = [];
  const flushers: (() => Promise<void>)[] = [];
  const stopped: Promise<void>[] = [];
  let closed = false;
  let started = false;
  let stopPromise: Promise<void> | undefined;
  const abort = () => {
    if (closed) return;
    closed = true;
    nodes.forEach((node) => node.disconnect());
    sockets.forEach((socket) => socket.close());
    void context.close();
    signal.removeEventListener("abort", abort);
  };
  const fail = (code: string) => {
    if (closed) return;
    abort();
    if (started) onError(transcriptionError(code));
  };
  signal.addEventListener("abort", abort, { once: true });
  try {
    if (signal.aborted) { abort(); throw new Error("aborted"); }
    if (context.sampleRate !== 24000) throw new Error("unsupported_audio");
    await context.resume();
    await context.audioWorklet.addModule("/pcm-capture-worklet.js");
    if (closed) throw new Error("aborted");
    await Promise.all((["display", "microphone"] as const).map(async (source) => {
      const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const url = new URL(`/conversations/${conversationId}/transcription/${source}`, base);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url);
      sockets.push(socket);
      let resolveStopped: () => void;
      let rejectStopped: (error: Error) => void;
      const stopResult = new Promise<void>((resolve, reject) => {
        resolveStopped = resolve; rejectStopped = reject;
      });
      // A socket can fail during capture, before stop() consumes this promise.
      void stopResult.catch(() => {});
      stopped.push(stopResult);
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error("connection_timeout")); fail("connection_timeout");
        }, 20000);
        const rejected = (code: string) => {
          clearTimeout(timeout);
          reject(new Error(code));
          rejectStopped(new Error(code));
          fail(code);
        };
        let cleanStop = false;
        socket.onmessage = (message) => {
          if (closed) return;
          let event;
          try { event = JSON.parse(message.data); }
          catch { rejected("invalid_response"); return; }
          if (event.type === "ready") {
            clearTimeout(timeout); resolve();
          } else if (event.type === "partial" || event.type === "final") {
            recordReceived(event as TranscriptEvent);
            onTranscript(event as TranscriptEvent);
          } else if (event.type === "stopped") {
            cleanStop = true; resolveStopped();
          } else if (event.type === "error") {
            rejected(event.code);
          }
        };
        socket.onerror = () => rejected("connection_failed");
        socket.onclose = () => {
          clearTimeout(timeout);
          if (!cleanStop) rejected("connection_closed");
        };
      });
      if (closed) throw new Error("aborted");
      const stream = source === "display" ? capture.displayStream : capture.microphoneStream;
      const input = context.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
      const worklet = new AudioWorkletNode(context, "pcm-capture");
      nodes.push(input, worklet);
      let flushed: (() => void) | undefined;
      worklet.port.onmessage = ({ data }) => {
        if (data === "flushed") { flushed?.(); return; }
        if (closed || socket.readyState !== WebSocket.OPEN) return;
        if (socket.bufferedAmount > 240000) { fail("network_slow"); return; }
        socket.send(data);
      };
      worklet.onprocessorerror = () => fail("audio_failed");
      flushers.push(() => new Promise<void>((resolve) => {
        flushed = resolve;
        worklet.port.postMessage("flush");
      }));
      input.connect(worklet).connect(context.destination);
    }));
    if (closed) throw new Error("aborted");
    started = true;
    return {
      abort,
      stop: () => {
        if (stopPromise) return stopPromise;
        stopPromise = (async () => {
          let timer: ReturnType<typeof setTimeout> | undefined;
          try {
            await Promise.race([
              (async () => {
                await Promise.all(flushers.map((flush) => flush()));
                sockets.forEach((socket) => socket.send('{"type":"stop"}'));
                await Promise.all(stopped);
              })(),
              new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new Error("stop_timeout")), 15000);
              }),
            ]);
          } finally {
            clearTimeout(timer);
            abort();
          }
        })();
        return stopPromise;
      },
    };
  } catch (error) {
    abort();
    throw error;
  }
}
