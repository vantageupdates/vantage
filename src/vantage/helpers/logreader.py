from datetime import datetime
from glob import glob
import os
import re
import time

from PySide6.QtCore import QFileSystemWatcher, Signal, QObject, QTimer
from PySide6.QtWidgets import QApplication

from vantage.helpers import parse_line, strip_timestamp

ZONE_CONTEXT_INTERVAL_MS = 2000
ZONE_CONTEXT_SCAN_BYTES = 256 * 1024
ZONE_CONTEXT_PATTERN = re.compile(
    r'^(?:LOADING, PLEASE WAIT|You\s+have\s+(?:entered\s+|zoned\s+(?:into\s+|to\s+)?))',
    re.I)
ZONE_LOOKUP_PATTERN = re.compile(
    r'^(?:There\s+(?:is|are)\s+(?:no|\d+)\s+players?\s+in\s+|'
    r'(?:Players|Characters)\s+(?:in|on)\s+|'
    r'(?:You\s+are\s+(?:currently\s+)?in|Current\s+(?:zone|region)(?:\s+is)?|Zone)\s*[:\-])',
    re.I)


def _zone_context_record(raw, offset, path, identity):
    """Recognize context only; never turn a historical line into activity."""
    line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
    text = strip_timestamp(line)
    if not (ZONE_CONTEXT_PATTERN.match(text) or ZONE_LOOKUP_PATTERN.match(text)):
        return None
    try:
        timestamp, _text = parse_line(line)
    except (ValueError, IndexError):
        timestamp = None
    character, server = LogReader._identity(path)
    return dict(text=text, character=character, server=server, path=path,
                identity=identity, offset=offset, timestamp=timestamp,
                captured_at=time.monotonic(), periodic=True)


class LogReaderSignals(QObject):
    new_line = Signal(object)
    character_updated = Signal(str)
    server_updated = Signal(str)
    zone_context = Signal(object)
    def __init__(self):
        super().__init__()

class LogReader(QFileSystemWatcher):
    character_name = None
    server_name = None

    def __init__(self, eq_directory):
        super().__init__()

        self._eq_directory = eq_directory
        self._stopped = False
        self._reading = False
        self._read_errors = {}
        self._events_delivered = 0
        self._last_checked_at = 0
        self._last_delivered_at = 0
        self._repair_count = 0
        self._files = glob(os.path.join(eq_directory, 'eqlog_*_*.txt'))
        self._watcher = QFileSystemWatcher(self._files, self)
        self._watcher.fileChanged.connect(self._file_changed_safe_wrap)
        self._dir_watcher = QFileSystemWatcher([eq_directory], self)
        self._dir_watcher.directoryChanged.connect(self._dir_changed)

        # Every character log owns an independent byte cursor.  A single
        # global cursor silently drops lines when two EQ clients write at the
        # same time.
        self._stats = {}
        self._zone_file_state = {}
        for path in self._files:
            try:
                stat = os.stat(path)
                self._stats[path] = {
                    'last_read': stat.st_size,
                    'identity': (stat.st_dev, stat.st_ino)}
                self._zone_file_state[path] = (
                    (stat.st_dev, stat.st_ino), stat.st_size, stat.st_mtime_ns)
            except OSError:
                self._stats[path] = {'last_read': 0, 'identity': None}
        self._context_seen = set()
        self._zone_contexts = {}
        self._zone_backscans = {}
        self._zone_verified = {}
        self._zone_active_path = None
        self._checking_zone_context = False
        self._zone_context_checks = 0
        self._zone_context_timer = QTimer(self)
        self._zone_context_timer.setInterval(ZONE_CONTEXT_INTERVAL_MS)
        self._zone_context_timer.timeout.connect(self._check_zone_context)
        self._zone_context_timer.start()
        self._drain_paths = set()
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(25)
        self._drain_timer.timeout.connect(self._drain_backlog)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        # Native changes normally arrive immediately. Keep short casts live
        # when Windows loses a file notification, without rescanning the
        # entire directory four times a second.
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(250)
        self._recovery_timer.timeout.connect(self._poll_known_files)
        self._recovery_timer.start()
        self._bootstrap_timer = QTimer(self)
        self._bootstrap_timer.setSingleShot(True)
        self._bootstrap_timer.timeout.connect(self._bootstrap_context)
        self._bootstrap_timer.start(0)

    def stop(self):
        """Disconnect both native watches and the recovery poll immediately."""
        self._stopped = True
        self._poll_timer.stop()
        self._recovery_timer.stop()
        self._bootstrap_timer.stop()
        self._zone_context_timer.stop()
        self._drain_timer.stop()
        self._drain_paths.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if self._dir_watcher.directories():
            self._dir_watcher.removePaths(self._dir_watcher.directories())

    def _bootstrap_context(self):
        if self._stopped:
            return
        candidates = []
        for path in self._files:
            try:
                candidates.append((os.stat(path).st_mtime_ns, path))
            except OSError:
                continue
        if candidates:
            self._zone_active_path = max(candidates)[1]
            self._recover_context(self._zone_active_path)

    def _recover_context(self, path):
        """Read bounded historical zone context, never replay historical events."""
        if path in self._context_seen:
            return
        offset = self._stats.get(path, {}).get('last_read', 0)
        try:
            with open(path, 'rb') as stream:
                start = max(0, offset - 256 * 1024)
                stream.seek(start)
                payload = stream.read(offset - start)
        except OSError:
            return
        self._context_seen.add(path)
        lines = payload.splitlines(keepends=True)
        if start:
            lines = lines[1:]
        position = offset
        for raw in reversed(lines):
            line_end = position
            position -= len(raw)
            if not raw.endswith(b'\n'):
                continue
            text = strip_timestamp(raw.decode('utf-8', errors='replace'))
            record = _zone_context_record(
                raw, line_end, path, self._stats.get(path, {}).get('identity'))
            if record is not None:
                self._remember_zone_context(path, record)
                if not text.upper().startswith('LOADING, PLEASE WAIT'):
                    character, server = self._identity(path)
                    QApplication.instance()._signals['logreader'].zone_context.emit(
                        (text, character, server))
                break

    def _remember_zone_context(self, path, record):
        previous = self._zone_contexts.get(path)
        if (previous and previous['identity'] == record['identity'] and
                previous['offset'] == record['offset'] and
                previous['text'] == record['text']):
            return previous
        self._zone_contexts[path] = record
        self._zone_backscans.pop(path, None)
        return record

    def _observe_zone_file(self, path, stat):
        signature = ((stat.st_dev, stat.st_ino), stat.st_size, stat.st_mtime_ns)
        previous = self._zone_file_state.get(path)
        if previous and (signature[0] != previous[0] or
                         signature[1] < previous[1] or
                         (signature[1] == previous[1] and signature[2] != previous[2])):
            # A same-size rewrite must not keep certifying the old zone. Do
            # not rewind the live cursor: touching a log must not replay casts.
            self._zone_contexts.pop(path, None)
            self._zone_backscans.pop(path, None)
            self._zone_verified.pop(path, None)
        self._zone_file_state[path] = signature

    def _scan_zone_context(self, path, end, identity, *, historical=False):
        """Read one bounded page; carry split lines when looking farther back."""
        scan = self._zone_backscans.get(path) if historical else None
        if scan and (scan['identity'] != identity or end < scan['boundary']):
            scan = None
        boundary = scan['position'] if scan else end
        if historical and scan and boundary == 0:
            return
        start = max(0, boundary - ZONE_CONTEXT_SCAN_BYTES)
        with open(path, 'rb') as stream:
            stream.seek(start)
            payload = stream.read(boundary - start)
        if scan:
            payload += scan['fragment']
        lines = payload.splitlines(keepends=True)
        fragment = b''
        if start and lines:
            fragment = lines.pop(0)
        position = start + len(payload)
        for raw in reversed(lines):
            line_end = position
            position -= len(raw)
            if raw.endswith(b'\n'):
                record = _zone_context_record(raw, line_end, path, identity)
                if record is not None:
                    self._remember_zone_context(path, record)
                    return
        if historical or (path not in self._zone_contexts and
                          path not in self._zone_backscans):
            # Corrupt, oversized records must not grow memory every heartbeat.
            self._zone_backscans[path] = dict(
                identity=identity, boundary=scan['boundary'] if scan else end,
                position=start, fragment=fragment[:64 * 1024])

    def _check_zone_context(self):
        """Reconcile the active map every two seconds, independently of dispatch."""
        if self._stopped or self._reading or self._checking_zone_context:
            return
        self._checking_zone_context = True
        try:
            path = self._zone_active_path
            if path not in self._files:
                self._bootstrap_context()
                path = self._zone_active_path
            if path not in self._files or self._stopped:
                return
            self._zone_context_checks += 1
            stat = os.stat(path)
            self._observe_zone_file(path, stat)
            identity = (stat.st_dev, stat.st_ino)
            state = self._stats.get(path, {})
            if state.get('identity') != identity or stat.st_size != state.get('last_read', 0):
                if state.get('identity') != identity or stat.st_size < state.get('last_read', 0):
                    self._zone_contexts.pop(path, None)
                    self._zone_backscans.pop(path, None)
                # Independently drain new bytes even if native notifications
                # and the short recovery poll have both stopped arriving.
                self._file_changed_safe_wrap(path)
                state = self._stats.get(path, {})
                if not self._stopped:
                    # EQ can append again between the initial stat and drain.
                    # Never verify an older boundary over the freshly read zone.
                    stat = os.stat(path)
                    self._observe_zone_file(path, stat)
                    identity = (stat.st_dev, stat.st_ino)
            if self._stopped:
                return
            end = min(stat.st_size, state.get('last_read', 0))
            # Do not jump ahead of unread events or consume a partial EQ write.
            fingerprint = (identity, stat.st_size, stat.st_mtime_ns, end)
            if (self._zone_verified.get(path) != fingerprint or
                    (path not in self._zone_contexts and path not in self._zone_backscans)):
                self._scan_zone_context(path, end, identity)
                self._zone_verified[path] = fingerprint
            if path not in self._zone_contexts and path in self._zone_backscans:
                self._scan_zone_context(path, end, identity, historical=True)
            record = self._zone_contexts.get(path)
            if record and not self._stopped:
                QApplication.instance()._signals['logreader'].zone_context.emit(
                    dict(record, active=True, observed_mtime_ns=stat.st_mtime_ns))
        except OSError:
            # Temporary sharing violations are retried without moving live cursors.
            pass
        finally:
            self._checking_zone_context = False

    def _poll(self):
        # Filesystem notifications are hints, not the only source of truth.
        # This also repairs dropped watches after rotation or a missing folder.
        if self._stopped:
            return
        discovered = self._dir_changed(self._eq_directory)
        if self._stopped:
            return
        if (os.path.isdir(self._eq_directory) and
                self._eq_directory not in self._dir_watcher.directories()):
            self._dir_watcher.addPath(self._eq_directory)
        self._poll_known_files(skip=discovered)

    def _poll_known_files(self, skip=()):
        if self._stopped:
            return
        for path in tuple(self._files):
            if path in skip:
                continue
            self._file_changed_safe_wrap(path)
            if self._stopped:
                return
        missing_watches = set(self._files) - set(self._watcher.files())
        if missing_watches:
            existing = [path for path in missing_watches if os.path.isfile(path)]
            if existing:
                self._watcher.addPaths(existing)

    def health_snapshot(self):
        """Read-only diagnostics; waiting for EQ writes is not a disconnect."""
        pending_bytes = 0
        for path in self._files:
            try:
                pending_bytes += max(
                    0, os.path.getsize(path) -
                    self._stats.get(path, {}).get('last_read', 0))
            except OSError:
                pass
        return {
            'folder': self._eq_directory,
            'stopped': self._stopped,
            'reading': self._reading,
            'known_files': len(self._files),
            'watched_files': len(self._watcher.files()),
            'directory_watched': self._eq_directory in self._dir_watcher.directories(),
            'pending_files': len(self._drain_paths),
            'pending_bytes': pending_bytes,
            'events_delivered': self._events_delivered,
            'last_checked_at': self._last_checked_at,
            'last_delivered_at': self._last_delivered_at,
            'repair_count': self._repair_count,
            'zone_context_checks': self._zone_context_checks,
            'timers': {
                'poll': self._poll_timer.isActive(),
                'recovery': self._recovery_timer.isActive(),
                'drain': self._drain_timer.isActive(),
                'zone_context': self._zone_context_timer.isActive(),
            },
            'active_errors': [dict(value) for path, value in self._read_errors.items()
                              if path in self._files],
        }

    def repair(self):
        """Repair existing watches/timers without restarting or moving cursors."""
        if not self._stopped:
            needs_repair = (
                not self._poll_timer.isActive() or
                not self._recovery_timer.isActive() or
                not self._zone_context_timer.isActive() or
                bool(set(self._files) - set(self._watcher.files())) or
                self._eq_directory not in self._dir_watcher.directories() or
                (bool(self._drain_paths) and not self._drain_timer.isActive()))
            if not self._poll_timer.isActive():
                self._poll_timer.start()
            if not self._recovery_timer.isActive():
                self._recovery_timer.start()
            if not self._zone_context_timer.isActive():
                self._zone_context_timer.start()
            self._poll()
            if self._drain_paths and not self._drain_timer.isActive():
                self._drain_timer.start()
            if needs_repair:
                self._repair_count += 1
        return self.health_snapshot()

    def _queue_drain(self, path):
        if self._stopped:
            return
        self._drain_paths.add(path)
        if not self._drain_timer.isActive():
            self._drain_timer.start()

    def _drain_backlog(self):
        pending = tuple(self._drain_paths)
        self._drain_paths.clear()
        for path in pending:
            self._file_changed_safe_wrap(path)
        if not self._drain_paths:
            self._drain_timer.stop()

    @staticmethod
    def _identity(path):
        name = os.path.basename(path)
        parts = name[:-4].split("_") if name.casefold().endswith(".txt") else name.split("_")
        return (
            parts[1] if len(parts) > 1 else "Unknown",
            "_".join(parts[2:]) if len(parts) > 2 else "Unknown")

    def profiles(self, now=None):
        """Return an honest per-log activity snapshot for the profile monitor."""
        now = datetime.now().timestamp() if now is None else float(now)
        rows = []
        for path in sorted(self._files, key=str.casefold):
            character, server = self._identity(path)
            try:
                modified = os.path.getmtime(path)
                size = os.path.getsize(path)
            except OSError:
                modified, size = 0, 0
            age = max(0, now - modified) if modified else float('inf')
            status = 'ACTIVE' if age <= 90 else 'QUIET' if age <= 900 else 'STALE'
            rows.append({
                'character': character,
                'server': server,
                'status': status,
                'age_seconds': age,
                'last_write': (
                    datetime.fromtimestamp(modified).strftime('%H:%M:%S')
                    if modified else 'Unavailable'),
                'file': os.path.basename(path),
                'size': size,
            })
        return rows

    def _dir_changed(self, changed_dir):
        if self._stopped:
            return ()
        updated_files = set()
        new_files = glob(os.path.join(self._eq_directory, 'eqlog_*_*.txt'))
        if new_files != self._files:
            files_to_remove = set(self._files) - set(new_files)
            if files_to_remove:
                self._watcher.removePaths(files_to_remove)
            updated_files = set(new_files) - set(self._files)
            self._watcher.addPaths(updated_files)
            for path in updated_files:
                try:
                    stat = os.stat(path)
                    identity = (stat.st_dev, stat.st_ino)
                except OSError:
                    identity = None
                self._stats.setdefault(path, {
                    'last_read': 0, 'identity': identity})
            for path in files_to_remove:
                # Preserve its cursor across a transient disappearance. The
                # inode/size check distinguishes a returned file from rotation.
                self._context_seen.discard(path)
                self._zone_contexts.pop(path, None)
                self._zone_backscans.pop(path, None)
            self._files = new_files
        missing_watches = set(new_files) - set(self._watcher.files())
        if missing_watches:
            self._watcher.addPaths(list(missing_watches))
        # A new EQ log can already contain a complete cast when the directory
        # notification arrives. Watching it does not replay that write.
        for path in updated_files:
            self._file_changed_safe_wrap(path)
        return updated_files

    def _file_changed_safe_wrap(self, changed_file):
        if self._stopped:
            return
        if self._reading:
            # Direct Qt signals can open a nested event loop. Reading another
            # batch from that loop used to overtake the current batch or move
            # its byte cursor twice, losing cast/landing messages permanently.
            self._queue_drain(changed_file)
            return
        self._reading = True
        self._last_checked_at = time.time()
        try:
            self._file_changed(changed_file)
            self._read_errors.pop(changed_file, None)
        except OSError as error:
            # Sharing violations during an EQ write/rotation are temporary;
            # retain the cursor and retry on the next poll.
            self._read_errors[changed_file] = {
                'file': os.path.basename(changed_file),
                'error': str(error),
                'checked_at': self._last_checked_at,
            }
        finally:
            self._reading = False

    def _file_changed(self, changed_file):
        char_name, server_name = self._identity(changed_file)
        app = QApplication.instance()
        state = self._stats.setdefault(
            changed_file, {'last_read': 0, 'identity': None})
        stat = os.stat(changed_file)
        self._observe_zone_file(changed_file, stat)
        identity = (stat.st_dev, stat.st_ino)
        if (stat.st_size == state['last_read'] and
                state.get('identity') == identity):
            return
        if state.get('identity') not in (None, identity):
            # EQ or a log archiver replaced this pathname with a new file.
            # A replacement can be larger than the old cursor, so size alone
            # is not enough to detect it.
            state['last_read'] = 0
            state.pop('discard_long_line', None)
            self._context_seen.discard(changed_file)
            self._zone_contexts.pop(changed_file, None)
            self._zone_backscans.pop(changed_file, None)
        state['identity'] = identity
        with open(changed_file, 'rb') as log:
            log.seek(0, os.SEEK_END)
            end = log.tell()
            if end < state['last_read']:
                state['last_read'] = 0
                state.pop('discard_long_line', None)
                self._context_seen.discard(changed_file)
                self._zone_contexts.pop(changed_file, None)
                self._zone_backscans.pop(changed_file, None)
            log.seek(state['last_read'], os.SEEK_SET)
            payload = log.read(64 * 1024)
        consumed = 0
        if state.get('discard_long_line'):
            boundary = payload.find(b'\n')
            consumed = len(payload) if boundary < 0 else boundary + 1
            payload = payload[consumed:]
            if boundary >= 0:
                state.pop('discard_long_line', None)
        # EQ messages are short. A corrupt oversized record must not prevent
        # every later zone/chat event from ever reaching the parsers.
        if b'\n' not in payload and len(payload) == 64 * 1024:
            consumed += len(payload)
            payload = b''
            state['discard_long_line'] = True
        state['last_read'] += consumed
        # QFileSystemWatcher can fire between the timestamp/text writes and
        # the trailing CRLF. Do not consume an incomplete EQ line: the next
        # event rereads it from the same byte cursor as one intact message.
        completed_at = payload.rfind(b'\n')
        if completed_at < 0:
            lines = []
        else:
            # Bound the work per callback so a burst cannot monopolize Qt.
            completed = b''.join(payload[:completed_at + 1].splitlines(keepends=True)[:128])
            lines = completed.splitlines(keepends=True)
        if lines:
            self._recover_context(changed_file)
            if self._stopped:
                return
            if server_name != self.server_name:
                self.server_name = server_name
                app._signals['logreader'].server_updated.emit(server_name)
                if self._stopped:
                    return
            if char_name != self.character_name:
                self.character_name = char_name
                app._signals['logreader'].character_updated.emit(char_name)
                if self._stopped:
                    return
            state['last_read'] += len(completed)
        line_offset = state['last_read'] - len(completed) if lines else state['last_read']
        for raw_line in lines:
            if self._stopped:
                return
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
            try:
                timestamp, text = parse_line(line)
            except (ValueError, IndexError):
                timestamp, text = datetime.now(), strip_timestamp(line)
            line_offset += len(raw_line)
            record = _zone_context_record(raw_line, line_offset, changed_file, identity)
            if record is not None:
                self._remember_zone_context(changed_file, record)
            if record is not None or re.match(r'^Your\s+Location\s+is\s+', text, re.I):
                self._zone_active_path = changed_file
            app._signals["logreader"].new_line.emit((
                timestamp, text, char_name, server_name))
            self._events_delivered += 1
            self._last_delivered_at = time.time()
        if self._stopped:
            return
        if (lines or consumed) and state['last_read'] < end:
            self._queue_drain(changed_file)

        # QFileSystemWatcher can drop a path when an application replaces the
        # file.  Re-add only this exact known log path if necessary.
        if (os.path.isfile(changed_file) and
                changed_file not in self._watcher.files()):
            self._watcher.addPath(changed_file)
