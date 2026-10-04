"""Bounded, self-contained transport for reviewed Vantage trigger packs.

Codes carry opaque native-package bytes, not a hosted pack ID. Semantic JSON,
regex, and audio validation stays in the existing disabled import review.
Nothing here reads files, uploads content, imports triggers, or enables them.
"""
from __future__ import annotations

import base64
import binascii
import re
import zlib

MAX_DECODED_BYTES = 256 * 1024
MAX_CODE_CHARS = 48 * 1024
SHARE_BASE_URL = "https://vantageupdates.github.io/vantage/companion/share.html"
SHARE_CODE_PREFIX = "VT1:"
_CODE = re.compile(r"VT1:[A-Za-z0-9_-]+\Z", re.ASCII)


class TriggerShareError(ValueError):
    """A share code is malformed or too large for safe clipboard transport."""


def _exact_code(text: str) -> str:
    if not isinstance(text, str):
        raise TriggerShareError("A trigger share code must be plain text.")
    if len(text) > MAX_CODE_CHARS + len(SHARE_BASE_URL) + 65:
        raise TriggerShareError("The share code is too long. Ask for a pack file instead.")
    if not text.isascii():
        raise TriggerShareError("The share code must contain ASCII characters only.")
    value = text.strip(" \t\r\n")
    if value.startswith(SHARE_BASE_URL + "#"):
        value = value[len(SHARE_BASE_URL) + 1:]
    if len(value) > MAX_CODE_CHARS:
        raise TriggerShareError("The share code is too long. Ask for a pack file instead.")
    if not _CODE.fullmatch(value):
        raise TriggerShareError("Paste a complete VT1: code or a Vantage share link.")
    return value


def create_trigger_share_code(payload: bytes) -> str:
    """Compress package bytes without dropping audio or truncating content."""
    if not isinstance(payload, bytes):
        raise TriggerShareError("Trigger share data must be bytes from a native pack.")
    if not payload:
        raise TriggerShareError("The trigger share data is empty.")
    if len(payload) > MAX_DECODED_BYTES:
        raise TriggerShareError(
            "Share data exceeds 256 KiB. Export a .gtp or native file instead.")
    encoded = base64.urlsafe_b64encode(zlib.compress(payload, level=9))
    code = SHARE_CODE_PREFIX + encoded.rstrip(b"=").decode("ascii")
    if len(code) > MAX_CODE_CHARS:
        raise TriggerShareError(
            "This pack is too large for a share code. Export a .gtp or native file instead.")
    return code


def decode_trigger_share_code(text: str) -> bytes:
    """Decode one exact code/link with bounded inflation and stream integrity."""
    code = _exact_code(text)
    encoded = code[len(SHARE_CODE_PREFIX):]
    if len(encoded) % 4 == 1:
        raise TriggerShareError("The share code is incomplete or malformed.")
    try:
        compressed = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise TriggerShareError("The share code is incomplete or malformed.") from error
    # Reject alternate final-bit encodings instead of silently normalizing
    # clipboard damage. Codes produced here always use canonical base64url.
    if base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii") != encoded:
        raise TriggerShareError("The share code is incomplete or malformed.")
    inflater = zlib.decompressobj()
    try:
        payload = inflater.decompress(compressed, MAX_DECODED_BYTES + 1)
    except zlib.error as error:
        raise TriggerShareError("The share code contains damaged compressed data.") from error
    if len(payload) > MAX_DECODED_BYTES or inflater.unconsumed_tail:
        raise TriggerShareError("Decoded share data exceeds the 256 KiB safety limit.")
    if not inflater.eof or inflater.unused_data:
        raise TriggerShareError("The share code contains incomplete or trailing data.")
    if not payload:
        raise TriggerShareError("The trigger share data is empty.")
    return payload


def trigger_share_url(code: str) -> str:
    """Make the static handoff link; no service, upload, or account is involved."""
    # Validate transport before making a link, but do not interpret its payload.
    value = _exact_code(code)
    decode_trigger_share_code(value)
    return SHARE_BASE_URL + "#" + value
