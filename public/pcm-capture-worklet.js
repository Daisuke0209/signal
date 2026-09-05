/* global AudioWorkletProcessor, registerProcessor */
// AudioContext supplies mono 24 kHz; transfer PCM16 every 100 ms.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(2400);
    this.offset = 0;
    this.stopped = false;
    this.port.onmessage = () => {
      this.stopped = true;
      this.flush();
      this.port.postMessage("flushed");
    };
  }
  flush() {
    if (!this.offset) return;
    const pcm = this.buffer.slice(0, this.offset);
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
    this.offset = 0;
  }
  process(inputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] / channels.length;
      value = Math.max(-1, Math.min(1, value));
      this.buffer[this.offset++] = Math.round(value * (value < 0 ? 32768 : 32767));
      if (this.offset === this.buffer.length) this.flush();
    }
    // Outputs stay silent: never play microphone/tab audio through the speakers.
    return true;
  }
}
registerProcessor("pcm-capture", PcmCapture);
