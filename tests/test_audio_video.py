import os
import pytest
from shinri.audio_video import media_processor


def test_audio_transcription_handler(tmp_path):
    # Test with non-existent file
    assert media_processor.transcribe_audio("non_existent.mp3")["text"] == ""

    # Test with an existing dummy file
    dummy_audio = tmp_path / "dummy.mp3"
    dummy_audio.write_bytes(b"ID3" + b"\x00" * 200)

    res = media_processor.transcribe_audio(str(dummy_audio))
    assert "transcribed" in res["text"].lower() or "voice" in res["text"].lower()


def test_video_processor_handler():
    res = media_processor.process_video("tests/non_existent.mp4")
    assert "frames" in res
    assert "transcript" in res
