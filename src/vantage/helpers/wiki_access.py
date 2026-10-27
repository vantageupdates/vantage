"""Respect Wiki access limits and preserve successful on-demand references.

This is a partial local reference cache, not a mirror of the Wiki. Challenges
are never solved or retried automatically; all Wiki views share the pause.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from vantage.helpers.wiki_source import MAX_PAGE_BYTES, SOURCE_NAME, parse_page, title_from_url
from urllib.parse import urlsplit


class WikiAccess:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._until = 0.0
        self._failures = 0
        self._reason = ""

    def pause(self, reason, retry_after="", challenge=False):
        self._failures += 1
        delay = min(3600, (300 if challenge else 60) *
                    2 ** min(self._failures - 1, 6))
        try:
            requested = float(retry_after)
        except (TypeError, ValueError):
            try:
                requested = (parsedate_to_datetime(str(retry_after)) -
                             datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                requested = 0
        if math.isfinite(requested):
            delay = max(delay, min(86400, requested))
        self._until = max(self._until, self._clock() + delay)
        self._reason = reason

    def status(self):
        remaining = self._until - self._clock()
        if remaining <= 0:
            return ""
        return (f"{self._reason} · Wiki refresh paused for "
                f"{max(1, math.ceil(remaining / 60))} min")

    def succeeded(self):
        # A late success from another in-flight request must not clear a pause.
        if self._clock() >= self._until:
            self._failures = 0


wiki_access = WikiAccess()


def _header(reply, name):
    lookup = getattr(reply, "rawHeader", None)
    if not callable(lookup):
        return ""
    name = name.decode("ascii") if isinstance(name, bytes) else str(name)
    # Current PySide accepts str (QAnyStringView); older bindings and some
    # reply adapters use bytes. Prefer the native signature but preserve both
    # adapters, including mappings that return empty for the other key type.
    for key in (name, name.encode("ascii")):
        try:
            value = lookup(key)
        except TypeError:
            continue
        if value:
            return value if isinstance(value, str) else bytes(value).decode(
                "ascii", errors="replace")
    return ""


def read_wiki_bytes(reply, *, allow_html=False):
    """Reject challenges and HTTP failures before accepting JSON or an image."""
    raw = bytes(reply.readAll()) if hasattr(reply, "readAll") else b""
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) \
        if hasattr(reply, "attribute") else None
    status = int(status or 0)
    prefix = raw[:8192].decode("utf-8", errors="replace").lstrip().casefold()
    html = prefix.startswith(("<!doctype html", "<html"))
    challenge = (_header(reply, b"cf-mitigated").casefold() == "challenge" or
                 (html and any(marker in prefix for marker in (
                     "just a moment", "cf-chl-", "challenge-platform",
                     "verify you are human"))))
    if challenge or status in {403, 429, 503}:
        reason = ("Wiki access requires browser verification" if challenge else
                  "Wiki access temporarily restricted" if status == 403 else
                  "Wiki is limiting requests" if status == 429 else
                  "Wiki temporarily unavailable")
        wiki_access.pause(reason, _header(reply, b"retry-after"),
                          challenge=challenge or status == 403)
        raise ValueError(wiki_access.status())
    if reply.error() != QNetworkReply.NetworkError.NoError:
        raise ValueError(reply.errorString() if hasattr(reply, "errorString")
                         else "Wiki unavailable")
    if status >= 400 or html and not allow_html:
        raise ValueError("Wiki returned an error page; saved references retained")
    url = reply.url().toString() if callable(getattr(reply, 'url', None)) else ''
    if url:
        try:
            parsed_url = urlsplit(url)
            trusted = (parsed_url.scheme == 'https' and parsed_url.hostname in
                       {'wiki.project1999.com', 'p99.funcamp.net'} and
                       not parsed_url.username and not parsed_url.password and
                       parsed_url.port in (None, 443))
        except ValueError:
            trusted = False
        if not trusted:
            raise ValueError('Wiki redirected outside the reference source')
    return raw


def read_wiki_reply(reply, *, page=False, rendered=False):
    """Read mirror pages while retaining existing validated API/cache support."""
    raw = read_wiki_bytes(reply, allow_html=True)
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError('Wiki response is larger than the safe limit')
    if raw.lstrip().startswith(b'<'):
        url = reply.url().toString() if callable(getattr(reply, 'url', None)) else ''
        payload = parse_page(raw, title_from_url(url))
        wiki_access.succeeded()
        return payload
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Wiki returned no usable data")
    if "query" in payload and not isinstance(payload["query"], dict):
        raise ValueError("Wiki returned unreadable query data")
    error = payload.get("error")
    if "error" in payload:
        code = str(error.get("code") or "") if isinstance(error, dict) else ""
        if code in {"maxlag", "ratelimited", "readonly"}:
            wiki_access.pause("Wiki is limiting requests",
                              _header(reply, b"retry-after"))
            raise ValueError(wiki_access.status())
        raise ValueError("Wiki page unavailable; saved references retained")
    if page:
        parsed = payload.get("parse")
        source = parsed.get("wikitext") if isinstance(parsed, dict) else None
        source = source.get("*") if isinstance(source, dict) else source
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Wiki returned no page content; saved reference retained")
        if rendered:
            text = parsed.get("text")
            text = text.get("*") if isinstance(text, dict) else text
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Wiki returned incomplete page content; saved reference retained")
    wiki_access.succeeded()
    return payload


def write_wiki_cache(path, payload):
    """Atomically save validated data; a failed write keeps the previous copy."""
    if not isinstance(payload, dict) or not payload:
        return False
    saved = dict(payload)
    saved["_wiki_cache"] = {
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": payload.get('_source') or SOURCE_NAME,
        "coverage": "on-demand reference",
    }
    try:
        encoded = json.dumps(saved, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return write_wiki_cache_bytes(path, encoded)


def write_wiki_cache_bytes(path, payload):
    """Commit an already validated reference or image without truncating its backup."""
    target = Path(path)
    pending = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent,
                prefix=target.name + ".", suffix=".part", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(payload)
        os.replace(pending, target)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass


def cached_reference_status(payload):
    metadata = payload.get("_wiki_cache") if isinstance(payload, dict) else None
    stamp = metadata.get("saved_at") if isinstance(metadata, dict) else None
    try:
        saved = datetime.fromisoformat(str(stamp)).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return "cached · freshness unverified"
    return f"cached {saved} · freshness unverified"
