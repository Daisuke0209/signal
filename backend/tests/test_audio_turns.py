import struct

from signal_api.audio_turns import FRAME_BYTES, AudioTurns

VOICE = struct.pack("<480h", *([2000] * 480))
SILENCE = bytes(FRAME_BYTES)


def test_silence_not_sent_and_preroll_bounded() -> None:
    gate = AudioTurns()
    assert gate.feed(SILENCE * 500) == []
    frames = gate.feed(VOICE)
    assert frames == [SILENCE] * 10 + [VOICE]
    assert gate.finish() == [None]


def test_fragmented_pcm_and_trailing_short_speech_flush() -> None:
    gate = AudioTurns()
    assert gate.feed(VOICE[:100]) == []
    assert gate.feed(VOICE[100:]) == [VOICE]
    assert gate.finish() == [bytes(FRAME_BYTES * 4), None]
    assert gate.finish() == []


def test_silence_and_max_turn_commit_without_duplicate_stop() -> None:
    gate = AudioTurns()
    assert gate.feed(VOICE * 750).count(None) == 1
    assert gate.finish() == []
    assert gate.feed(VOICE + SILENCE * 35).count(None) == 1
    assert gate.finish() == []


def test_leftover_frame_at_stop_is_not_lost() -> None:
    gate = AudioTurns()
    gate.feed(VOICE[:100])
    frames = gate.finish()
    assert frames[0] == VOICE[:100] + bytes(FRAME_BYTES - 100)
    assert frames[-1] is None


def test_configurable_threshold_preserves_soft_voice_and_preroll() -> None:
    soft = struct.pack("<480h", *([180] * 480))  # RMS 0.0055
    gate = AudioTurns(threshold=0.005)
    assert gate.feed(SILENCE * 10) == []
    assert gate.feed(soft) == [SILENCE] * 10 + [soft]
    # A trailing sub-frame is padded and forwarded before commit.
    assert gate.feed(soft[:100]) == []
    tail = gate.finish()
    assert tail == [soft[:100] + bytes(FRAME_BYTES - 100), None]
    assert AudioTurns(threshold=0.01).feed(soft) == []
