"""Exact EQTool-style camp completion state from authoritative EQ log lines."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal


CAMP_PREPARING_LINE = "It will take about 5 more seconds to prepare your camp."
CAMP_ABANDONED_LINE = "You abandon your preparations to camp."
WELCOME_LINE = "Welcome to EverQuest!"
CAMP_COMPLETION_DELAY_MS = 6000


@dataclass(frozen=True)
class PendingCamp:
    timestamp: object
    character: str
    server: str


class CampSessionController(QObject):
    """Keep an independent delayed camp state for every tailed log profile."""

    camp_completed = Signal(object, str, str)
    state_changed = Signal(str, str, str)

    def __init__(self, parent=None, delay_ms=CAMP_COMPLETION_DELAY_MS):
        super().__init__(parent)
        self.delay_ms = max(1, int(delay_ms))
        self._pending = {}

    @staticmethod
    def _key(character, server):
        return (
            str(server or "").strip().casefold(),
            str(character or "").strip().casefold(),
        )

    @property
    def pending_count(self):
        return len(self._pending)

    def ingest(self, line, timestamp, character="", server=""):
        text = str(line or "")
        character = str(character or "").strip()
        server = str(server or "").strip()
        key = self._key(character, server)

        if text == CAMP_PREPARING_LINE:
            self._cancel(key)
            timer = QTimer(self)
            timer.setSingleShot(True)
            pending = PendingCamp(timestamp, character, server)
            self._pending[key] = (timer, pending)
            timer.timeout.connect(lambda key=key: self._finish(key))
            timer.start(self.delay_ms)
            self.state_changed.emit("preparing", character, server)
            return "preparing"

        if text == CAMP_ABANDONED_LINE:
            self._cancel(key)
            self.state_changed.emit("abandoned", character, server)
            return "abandoned"

        if text == WELCOME_LINE:
            self._cancel(key)
            self.state_changed.emit("welcome", character, server)
            return "welcome"

        return ""

    def _cancel(self, key):
        entry = self._pending.pop(key, None)
        if not entry:
            return False
        timer, _pending = entry
        timer.stop()
        timer.deleteLater()
        return True

    def _finish(self, key):
        entry = self._pending.pop(key, None)
        if not entry:
            return
        timer, pending = entry
        timer.deleteLater()
        self.state_changed.emit(
            "camped", pending.character, pending.server)
        self.camp_completed.emit(
            pending.timestamp, pending.character, pending.server)
