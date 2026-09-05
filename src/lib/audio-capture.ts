export type AudioCapture = {
  displayStream: MediaStream;
  microphoneStream: MediaStream;
};

export type AudioCaptureFailure =
  "cancelled" | "missing-tab-audio" | "permission-denied";

export async function startAudioCapture(): Promise<AudioCapture> {
  const displayStream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: "browser" },
    audio: true,
  });
  if (displayStream.getAudioTracks().length === 0) {
    stopStream(displayStream);
    throw new Error("missing-tab-audio");
  }

  try {
    const microphoneStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });
    return { displayStream, microphoneStream };
  } catch (error) {
    stopStream(displayStream);
    throw error;
  }
}

export function stopStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}

export function captureFailure(error: unknown): AudioCaptureFailure {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "permission-denied";
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return "cancelled";
  }
  if (error instanceof Error && error.message === "missing-tab-audio") {
    return "missing-tab-audio";
  }
  return "cancelled";
}
