"""Share transport never imports a pack or expands unbounded input."""
import base64
import json
import random
import zlib

import pytest

from vantage.helpers.trigger_sharing import (
    MAX_CODE_CHARS, MAX_DECODED_BYTES, SHARE_BASE_URL, TriggerShareError,
    create_trigger_share_code, decode_trigger_share_code, trigger_share_url)


def _unchecked_code(compressed):
    return "VT1:" + base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")


def test_native_json_round_trip_in_code_and_exact_static_link():
    payload = json.dumps({
        "format": "vantage-trigger-pack", "version": 1,
        "triggers": [{"name": "Kael – enrage", "text": "<script>never HTML</script>"}],
        "groups": {"Raid/Kael": {"enabled": False}}, "media": {},
    }, ensure_ascii=False).encode("utf-8")
    code = create_trigger_share_code(payload)
    assert code.startswith("VT1:") and code.isascii() and "=" not in code
    assert decode_trigger_share_code(code) == payload
    url = trigger_share_url(code)
    assert url == SHARE_BASE_URL + "#" + code
    assert decode_trigger_share_code(url) == payload
    assert decode_trigger_share_code(" \r\n" + url + "\t ") == payload


def test_native_import_review_is_separate_and_disabled():
    from vantage.helpers.gina_import import (
        import_vantage_package_bytes, serialize_vantage_package)
    from vantage.parsers.spells import CustomTrigger

    trigger = CustomTrigger(
        name="Shared timer", text="Start {c}", enabled=True,
        timer_type="countdown", time="00:01:00", category="Raid/Kael",
        timer_ending_delivery="tts", timer_ending_tts="{c} ending")
    payload, warnings = serialize_vantage_package([trigger])
    assert not warnings
    code = create_trigger_share_code(payload)
    batch = import_vantage_package_bytes(decode_trigger_share_code(code))
    assert len(batch) == 1
    restored = batch[0]
    assert not restored.enabled
    assert (restored.name, restored.text, restored.category) == (
        trigger.name, trigger.text, trigger.category)
    assert restored.timer_ending_tts == "{c} ending"


@pytest.mark.parametrize("payload", [None, "", bytearray(b"pack"), 42, False, b""])
def test_creation_rejects_wrong_type_or_empty_data(payload):
    with pytest.raises(TriggerShareError):
        create_trigger_share_code(payload)


@pytest.mark.parametrize("value", [
    None, b"VT1:eJw", 42, False, "", "VT1:", "vt1:eJw",
    "prefix VT1:eJw", "VT1:eJw\nembedded", "VT1:eJw=", "VT1:eJw+",
    "VT1:eJw/", "VT1:eJw\u200b", "VT1:eJwé", "VT1:A", "VT1:AB",
    "https://other.example/share.html#VT1:eJw",
    "http://vantageupdates.github.io/vantage/companion/share.html#VT1:eJw",
    SHARE_BASE_URL + "?upload=1#VT1:eJw",
    SHARE_BASE_URL + "#VT1%3AeJw",
])
def test_decoder_rejects_nonexact_ascii_transport(value):
    with pytest.raises(TriggerShareError):
        decode_trigger_share_code(value)


def test_decoded_limit_is_enforced_before_unbounded_inflation():
    payload = b"x" * MAX_DECODED_BYTES
    assert decode_trigger_share_code(create_trigger_share_code(payload)) == payload
    with pytest.raises(TriggerShareError, match="256 KiB"):
        create_trigger_share_code(payload + b"x")
    bomb = _unchecked_code(zlib.compress(payload + b"x"))
    assert len(bomb) < MAX_CODE_CHARS
    with pytest.raises(TriggerShareError, match="256 KiB"):
        decode_trigger_share_code(bomb)


def test_encoded_limit_rejects_without_truncating_or_dropping_data():
    payload = random.Random(17).randbytes(40 * 1024)
    assert len(payload) < MAX_DECODED_BYTES
    with pytest.raises(TriggerShareError, match="file instead"):
        create_trigger_share_code(payload)
    with pytest.raises(TriggerShareError, match="too long"):
        decode_trigger_share_code("VT1:" + "A" * MAX_CODE_CHARS)


@pytest.mark.parametrize("compressed", [
    zlib.compress(b"pack")[:-1],
    zlib.compress(b"pack") + b"trailing",
    zlib.compress(b"pack") + zlib.compress(b"another"),
    zlib.compress(b""),
    b"not zlib",
])
def test_incomplete_corrupt_trailing_and_empty_streams_are_rejected(compressed):
    with pytest.raises(TriggerShareError):
        decode_trigger_share_code(_unchecked_code(compressed))


def test_corrupted_checksum_is_rejected():
    compressed = bytearray(zlib.compress(b"complete native package"))
    compressed[-1] ^= 1
    with pytest.raises(TriggerShareError, match="damaged"):
        decode_trigger_share_code(_unchecked_code(compressed))


def test_noncanonical_final_base64_bits_are_rejected():
    # A complete stream whose encoding ends in 2 or 3 characters. Mutating the
    # unused low final bits otherwise decodes to identical bytes in Python.
    for length in range(1, 32):
        code = create_trigger_share_code(b"a" * length)
        body = code[4:]
        if len(body) % 4 in (2, 3):
            break
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last = alphabet.index(body[-1])
    altered = code[:-1] + alphabet[last | 1]
    assert altered != code
    with pytest.raises(TriggerShareError, match="malformed"):
        decode_trigger_share_code(altered)


def test_link_creation_does_not_accept_damaged_stream():
    with pytest.raises(TriggerShareError):
        trigger_share_url("VT1:eJw")
