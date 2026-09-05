import { afterEach, describe, expect, it, vi } from "vitest";
import { captureFailure, startAudioCapture, stopStream } from "./audio-capture";

type StreamMock = {
  getTracks: ReturnType<typeof vi.fn>;
  getAudioTracks: ReturnType<typeof vi.fn>;
};

function stream(audioTracks: MediaStreamTrack[] = []): StreamMock {
  return {
    getTracks: vi.fn(() => audioTracks),
    getAudioTracks: vi.fn(() => audioTracks),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("audio capture", () => {
  it("reports a cancelled tab share", async () => {
    const failure = new DOMException("cancelled", "AbortError");
    vi.stubGlobal("navigator", {
      mediaDevices: { getDisplayMedia: vi.fn().mockRejectedValue(failure) },
    });
    await expect(startAudioCapture()).rejects.toBe(failure);
    expect(captureFailure(failure)).toBe("cancelled");
  });

  it("stops a display stream with no shared audio", async () => {
    const display = stream();
    vi.stubGlobal("navigator", {
      mediaDevices: { getDisplayMedia: vi.fn().mockResolvedValue(display) },
    });
    await expect(startAudioCapture()).rejects.toThrow("missing-tab-audio");
    expect(display.getTracks).toHaveBeenCalled();
  });

  it("releases tab audio when microphone permission is denied", async () => {
    const track = { stop: vi.fn() } as unknown as MediaStreamTrack;
    const display = stream([track]);
    const failure = new DOMException("denied", "NotAllowedError");
    vi.stubGlobal("navigator", {
      mediaDevices: {
        getDisplayMedia: vi.fn().mockResolvedValue(display),
        getUserMedia: vi.fn().mockRejectedValue(failure),
      },
    });
    await expect(startAudioCapture()).rejects.toBe(failure);
    expect(track.stop).toHaveBeenCalledOnce();
    expect(captureFailure(failure)).toBe("permission-denied");
  });

  it("stops every track when capture is explicitly stopped", () => {
    const first = { stop: vi.fn() } as unknown as MediaStreamTrack;
    const second = { stop: vi.fn() } as unknown as MediaStreamTrack;
    stopStream(stream([first, second]) as unknown as MediaStream);
    expect(first.stop).toHaveBeenCalledOnce();
    expect(second.stop).toHaveBeenCalledOnce();
  });
});
