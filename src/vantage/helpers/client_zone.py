"""Read confirmed zone changes from the selected EQ client's debug log."""
from datetime import datetime
import os
from pathlib import Path
import re
import time


INITIAL_READ_BYTES = 256 * 1024
INCREMENTAL_READ_BYTES = 64 * 1024
MAX_LINE_BYTES = 16 * 1024

_ENTRY = re.compile(
    r'^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\t'
    r'(?P<message>[^\r\n]+)$')
_PLAYER = re.compile(
    r'^Player = (?P<character>[A-Za-z]{1,64}), '
    r'zone = (?P<zone>[A-Za-z][A-Za-z0-9 .\'()/_:-]{0,95})$')
_WAITING = re.compile(
    r'^Waiting to connect to zone\.\.\.(?: Character [A-Za-z]{1,64})?$')
_READY = frozenset({
    'Zone initialized.',
    'Zone Connect -- Received MSG_READY_ENTER_WORLD',
})


class ClientZoneTracker:
    """Bounded, read-only tail of ``Logs/dbg.txt``; no game or Qt access.

    ``poll`` returns only a confirmed character/zone record. The record's
    confirmation timestamp and byte offset stay unchanged on idle polls.
    Server identity must be supplied by the caller from a known character log.
    """

    def __init__(self, logs_directory):
        self.path = Path(os.path.abspath(os.fspath(logs_directory))) / 'dbg.txt'
        self._reset()

    def _reset(self):
        self._identity = None
        self._signature = None
        self._offset = 0
        self._partial = b''
        self._discard_line = False
        self._pending = None
        self._current = None

    @staticmethod
    def _file_identity(stat):
        return stat.st_dev, stat.st_ino

    def poll(self):
        """Read at most one bounded chunk and return a stable current record."""
        try:
            stat = self.path.stat()
            identity = self._file_identity(stat)
            signature = (identity, stat.st_size, stat.st_mtime_ns)
            if (self._signature == signature and
                    self._offset >= stat.st_size):
                return dict(self._current) if self._current else None

            replaced = (self._identity is not None and
                        (identity != self._identity or
                         stat.st_size < self._offset or
                         (self._signature is not None and
                          stat.st_size <= self._signature[1] and
                          signature != self._signature)))
            if replaced:
                self._reset()
            initial = self._identity is None
            start = (max(0, stat.st_size - INITIAL_READ_BYTES)
                     if initial else self._offset)
            limit = INITIAL_READ_BYTES if initial else INCREMENTAL_READ_BYTES
            starts_mid_line = False
            with self.path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                # A replacement between stat and open is retried next poll.
                if self._file_identity(opened) != identity:
                    self._reset()
                    return None
                if initial and start:
                    # One boundary byte distinguishes a cut record from a
                    # complete Player line exactly at the tail's beginning.
                    stream.seek(start - 1)
                    starts_mid_line = stream.read(1) != b'\n'
                else:
                    stream.seek(start)
                payload = stream.read(min(limit, max(0, stat.st_size - start)))

            after = self.path.stat()
            if (self._file_identity(after) != identity or
                    after.st_size < start + len(payload) or
                    (after.st_size == stat.st_size and
                     after.st_mtime_ns != stat.st_mtime_ns)):
                self._reset()
                return None

            self._identity = identity
            if initial:
                # The bounded tail may begin in the middle of a record.
                self._discard_line = starts_mid_line
            self._consume(payload, start)
            self._offset = start + len(payload)
            # Preserve the pre-read size, so concurrent appends are read next.
            self._signature = signature
            return dict(self._current) if self._current else None
        except (OSError, ValueError):
            # Inaccessible, removed, or replaced logs cannot certify an old zone.
            self._reset()
            return None

    def _consume(self, payload, start):
        data = self._partial + payload
        base = start - len(self._partial)
        self._partial = b''
        position = 0
        while True:
            newline = data.find(b'\n', position)
            if newline < 0:
                break
            end = newline + 1
            line = data[position:end]
            if self._discard_line:
                self._discard_line = False
            elif len(line) <= MAX_LINE_BYTES and line.endswith(b'\r\n'):
                self._consume_line(line[:-2], base + end)
            position = end
        remainder = data[position:]
        if not self._discard_line:
            if len(remainder) > MAX_LINE_BYTES:
                self._discard_line = True
            else:
                self._partial = remainder

    def _consume_line(self, raw, offset):
        try:
            line = raw.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            return
        match = _ENTRY.fullmatch(line)
        if match is None:
            return
        try:
            timestamp = datetime.fromisoformat(match['timestamp'])
        except ValueError:
            return
        message = match['message']
        if message == 'ZONING' or _WAITING.fullmatch(message):
            self._pending = self._current = None
            return
        player = _PLAYER.fullmatch(message)
        if player is not None:
            self._current = None
            self._pending = (player['character'], player['zone'].strip(), timestamp)
            return
        if message in _READY and self._pending is not None:
            character, zone, started = self._pending
            if timestamp < started:
                return
            self._current = dict(
                character=character, zone=zone, timestamp=timestamp,
                path=str(self.path), identity=self._identity, offset=offset,
                captured_at=time.monotonic(), source='client_debug')
            self._pending = None
