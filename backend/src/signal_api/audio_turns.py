"""Small energy gate for the streaming model, which does not support server VAD.

20 ms frames, 200 ms pre-roll, 700 ms silence, 15 s maximum turn.
This is not speaker detection. Each source has its own gate.
"""

import math
import struct
from collections import deque

FRAME_BYTES = 960  # PCM16 mono, 24 kHz, 20 ms


class AudioTurns:
    def __init__(self, threshold: float = 0.005) -> None:
        self.threshold = threshold
        self.buffer = bytearray()
        self.pre_roll: deque[bytes] = deque(maxlen=10)
        self.active = False
        self.frames = 0
        self.silence = 0

    def feed(self, audio: bytes) -> list[bytes | None]:
        self.buffer.extend(audio)
        output: list[bytes | None] = []
        while len(self.buffer) >= FRAME_BYTES:
            frame = bytes(self.buffer[:FRAME_BYTES])
            del self.buffer[:FRAME_BYTES]
            samples = struct.unpack("<480h", frame)
            voiced = (
                math.sqrt(sum(s * s for s in samples) / 480) / 32768 >= self.threshold
            )
            if not self.active:
                if not voiced:
                    self.pre_roll.append(frame)
                    continue
                self.active = True
                output.extend(self.pre_roll)
                self.frames = len(self.pre_roll)
                self.pre_roll.clear()
            output.append(frame)
            self.frames += 1
            self.silence = 0 if voiced else self.silence + 1
            if self.silence >= 35 or self.frames >= 750:
                output.append(None)  # explicit provider commit
                self.active = False
                self.frames = self.silence = 0
        return output

    def finish(self) -> list[bytes | None]:
        output: list[bytes | None] = []
        if self.buffer:
            output.extend(self.feed(bytes(FRAME_BYTES - len(self.buffer))))
        if self.active:
            # OpenAI requires at least 100 ms on an explicit commit.
            if self.frames < 5:
                output.append(bytes((5 - self.frames) * FRAME_BYTES))
            output.append(None)
        self.active = False
        self.pre_roll.clear()
        return output
