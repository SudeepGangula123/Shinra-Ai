import pytest

from shinri.config import MB, Settings
from shinri.validation import InputError, classify_text, sniff, validate_file, validate_text
from tests.conftest import JPEG, MP4, OGG, PNG

S = Settings()


def test_sniff_known_types():
    assert sniff(JPEG).input_type == "image"
    assert sniff(PNG).mime == "image/png"
    assert sniff(OGG).input_type == "audio"          # Telegram voice notes
    assert sniff(MP4).input_type == "video"
    assert sniff(b"\x00\x00\x00\x18ftypM4A " + b"\0" * 8).input_type == "audio"
    assert sniff(b"RIFF\x00\x00\x00\x00WAVEfmt ").mime == "audio/wav"
    assert sniff(b"MZ\x90\x00" + b"\0" * 12) is None  # an .exe is rejected whatever it is called


def test_text_rules():
    assert validate_text("  hello world  ", S, False) == "hello world"
    with pytest.raises(InputError):
        validate_text("hi", S, False)                 # too short and no file
    assert validate_text("", S, True) == ""           # file alone is fine
    with pytest.raises(InputError) as e:
        validate_text("x" * 5000, S, False)
    assert e.value.status == 413


def test_classify_text():
    assert classify_text("https://example.com/a?b=1") == "link"
    assert classify_text("see https://example.com now") == "text"
    assert classify_text("plain claim") == "text"


def test_file_limits():
    with pytest.raises(InputError) as e:
        validate_file(b"", S)
    assert "empty" in e.value.message
    with pytest.raises(InputError) as e:
        validate_file(b"not a media file at all", S)
    assert e.value.status == 415
    big = JPEG + b"\0" * (11 * MB)
    with pytest.raises(InputError) as e:
        validate_file(big, S)
    assert e.value.status == 413 and "10 MB" in e.value.message
    assert validate_file(MP4 + b"\0" * (5 * MB), S).input_type == "video"
