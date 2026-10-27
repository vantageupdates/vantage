from datetime import datetime
from glob import glob
import os
import re

from PySide6.QtCore import QFileSystemWatcher, Signal, QObject, QTimer
from PySide6.QtWidgets import QApplication

from vantage.helpers import parse_line, strip_timestamp

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
        self._files = glob(os.path.join(eq_directory, 'eqlog_*_*.txt'))
        self._watcher = QFileSystemWatcher(self._files, self)
        self._watcher.fileChanged.connect(self._file_changed_safe_wrap)
        self._dir_watcher = QFileSystemWatcher([eq_directory], self)
        self._dir_watcher.directoryChanged.connect(self._dir_changed)

        # Every character log owns an independent byte cursor.  A single
        # global cursor silently drops lines when two EQ clients write at the
        # same time.
        self._stats = {}
        for path in self._files:
            try:
                stat = os.stat(path)
                self._stats[path] = {
                    'last_read': stat.st_size,
                    'identity': (stat.st_dev, stat.st_ino)}
            except OSError:
                self._stats[path] = {'last_read': 0, 'identity': None}
        self._context_seen = set()
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
            self._recover_context(max(candidates)[1])

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
        lines = payload.splitlines()
        if start:
            lines = lines[1:]
        for raw in reversed(lines):
            text = strip_timestamp(raw.decode('utf-8', errors='replace'))
            if text.startswith('LOADING, PLEASE WAIT'):
                break
            if re.match(r'^(You have entered |There (?:is|are) (?:no|\d+) players? in )', text, re.I):
                character, server = self._identity(path)
                QApplication.instance()._signals['logreader'].zone_context.emit(
                    (text, character, server))
                break

    def _poll(self):
        # Filesystem notifications are hints, not the only source of truth.
        # This also repairs dropped watches after rotation or a missing folder.
        if self._stopped:
            return
        discovered = self._dir_changed(self._eq_directory)
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
        missing_watches = set(self._files) - set(self._watcher.files())
        if missing_watches:
            existing = [path for path in missing_watches if os.path.isfile(path)]
            if existing:
                self._watcher.addPaths(existing)

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
        try:
            self._file_changed(changed_file)
        except OSError:
            # Sharing violations during an EQ write/rotation are temporary;
            # retain the cursor and retry on the next poll.
            return

    def _file_changed(self, changed_file):
        char_name, server_name = self._identity(changed_file)
        app = QApplication.instance()
        state = self._stats.setdefault(
            changed_file, {'last_read': 0, 'identity': None})
        stat = os.stat(changed_file)
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
        state['identity'] = identity
        with open(changed_file, 'rb') as log:
            log.seek(0, os.SEEK_END)
            end = log.tell()
            if end < state['last_read']:
                state['last_read'] = 0
                state.pop('discard_long_line', None)
                self._context_seen.discard(changed_file)
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
            lines = completed.splitlines()
        if lines:
            self._recover_context(changed_file)
            if server_name != self.server_name:
                self.server_name = server_name
                app._signals['logreader'].server_updated.emit(server_name)
            if char_name != self.character_name:
                self.character_name = char_name
                app._signals['logreader'].character_updated.emit(char_name)
            state['last_read'] += len(completed)
        for raw_line in lines:
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
            try:
                timestamp, text = parse_line(line)
            except (ValueError, IndexError):
                timestamp, text = datetime.now(), strip_timestamp(line)
            app._signals["logreader"].new_line.emit((
                timestamp, text, char_name, server_name))
        if (lines or consumed) and state['last_read'] < end:
            self._drain_paths.add(changed_file)
            if not self._drain_timer.isActive():
                self._drain_timer.start()

        # QFileSystemWatcher can drop a path when an application replaces the
        # file.  Re-add only this exact known log path if necessary.
        if (os.path.isfile(changed_file) and
                changed_file not in self._watcher.files()):
            self._watcher.addPath(changed_file)
