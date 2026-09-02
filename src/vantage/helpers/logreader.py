from datetime import datetime
from glob import glob
import os

from PySide6.QtCore import QFileSystemWatcher, Signal, QObject
from PySide6.QtWidgets import QApplication

from vantage.helpers import parse_line, strip_timestamp

class LogReaderSignals(QObject):
    new_line = Signal(object)
    character_updated = Signal(str)
    server_updated = Signal(str)
    def __init__(self):
        super().__init__()

class LogReader(QFileSystemWatcher):
    character_name = None
    server_name = None

    def __init__(self, eq_directory):
        super().__init__()

        self._eq_directory = eq_directory
        self._files = glob(os.path.join(eq_directory, 'eqlog_*_*.txt'))
        self._watcher = QFileSystemWatcher(self._files)
        self._watcher.fileChanged.connect(self._file_changed_safe_wrap)
        self._dir_watcher = QFileSystemWatcher([eq_directory])
        self._dir_watcher.directoryChanged.connect(self._dir_changed)

        # Every character log owns an independent byte cursor.  A single
        # global cursor silently drops lines when two EQ clients write at the
        # same time.
        self._stats = {}
        for path in self._files:
            try:
                self._stats[path] = {'last_read': os.path.getsize(path)}
            except OSError:
                self._stats[path] = {'last_read': 0}

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
        print("Directory '%s' updated, refreshing file list..." % changed_dir)
        new_files = glob(os.path.join(self._eq_directory, 'eqlog_*_*.txt'))
        if new_files != self._files:
            files_to_remove = set(self._files) - set(new_files)
            if files_to_remove:
                self._watcher.removePaths(files_to_remove)
            updated_files = set(new_files) - set(self._files)
            self._watcher.addPaths(updated_files)
            for path in updated_files:
                self._stats[path] = {'last_read': 0}
            for path in files_to_remove:
                self._stats.pop(path, None)
            self._files = new_files

    def _file_changed_safe_wrap(self, changed_file):
        try:
            self._file_changed(changed_file)
        except FileNotFoundError:
            print("File not found: %s; did it move?")

    def _file_changed(self, changed_file):
        char_name, server_name = self._identity(changed_file)
        app = QApplication.instance()
        if server_name != self.server_name:
            self.server_name = server_name
            app._signals["logreader"].server_updated.emit(server_name)
        if char_name != self.character_name:
            self.character_name = char_name
            app._signals["logreader"].character_updated.emit(char_name)

        state = self._stats.setdefault(changed_file, {'last_read': 0})
        with open(changed_file, 'rb') as log:
            log.seek(0, os.SEEK_END)
            end = log.tell()
            if end < state['last_read']:
                state['last_read'] = 0
            log.seek(state['last_read'], os.SEEK_SET)
            lines = log.readlines()
            state['last_read'] = log.tell()
        for raw_line in lines:
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
            try:
                timestamp, text = parse_line(line)
            except (ValueError, IndexError):
                timestamp, text = datetime.now(), strip_timestamp(line)
            app._signals["logreader"].new_line.emit((
                timestamp, text, char_name, server_name))

        # QFileSystemWatcher can drop a path when an application replaces the
        # file.  Re-add only this exact known log path if necessary.
        if (os.path.isfile(changed_file) and
                changed_file not in self._watcher.files()):
            self._watcher.addPath(changed_file)
