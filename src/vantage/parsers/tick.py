"""Compact, log-safe player and target tick monitor for Project 1999."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QToolButton, QVBoxLayout)

from vantage.helpers import config
from vantage.helpers.combat import DOT
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow


TICK_SECONDS = 6.0
ZONE_RX = re.compile(r"^You have entered (?P<zone>.+)\.$", re.IGNORECASE)


@dataclass(frozen=True)
class TickSnapshot:
    synced: bool
    remaining: float
    phase: float
    progress: float
    cycle: int
    pulse: bool
    source: str
    confidence: str
    entity: str
    period: float


class ServerTickClock:
    """Monotonic six-second clock that can learn from repeated log anchors."""

    def __init__(self, period=TICK_SECONDS):
        self.default_period = max(5.5, min(6.5, float(period)))
        self.period = self.default_period
        self.anchor = None
        self.source = ""
        self.confidence = "unsynced"
        self.entity = ""
        self._calibration_key = ""
        self._last_event = None

    def clear(self, reset_period=True):
        self.anchor = None
        self.source = ""
        self.confidence = "unsynced"
        self.entity = ""
        self._calibration_key = ""
        self._last_event = None
        if reset_period:
            self.period = self.default_period

    def sync(self, now, source, confidence="manual", entity="",
             calibration_key=""):
        now = float(now)
        calibration_key = str(calibration_key or "")
        if (calibration_key and calibration_key == self._calibration_key
                and self._last_event is not None):
            gap = now - self._last_event
            steps = max(1, round(gap / max(0.001, self.period)))
            estimate = gap / steps
            if 5.70 <= estimate <= 6.30:
                self.period = self.period * 0.72 + estimate * 0.28
        elif calibration_key and calibration_key != self._calibration_key:
            self.period = self.default_period
        self.anchor = now
        self.source = str(source or "Synced")
        self.confidence = str(confidence or "manual").casefold()
        self.entity = str(entity or "")
        self._calibration_key = calibration_key
        self._last_event = now if calibration_key else None

    def snapshot(self, now):
        if self.anchor is None:
            return TickSnapshot(
                False, self.period, 0.0, 0.0, 0, False, "Not synced",
                "unsynced", "", self.period)
        elapsed = max(0.0, float(now) - self.anchor)
        phase = elapsed % self.period
        cycle = int(elapsed // self.period)
        pulse = phase < 0.28
        remaining = 0.0 if pulse else max(0.0, self.period - phase)
        return TickSnapshot(
            True, remaining, phase, phase / self.period, cycle, pulse,
            self.source, self.confidence, self.entity, self.period)


class ServerTick(ParserWindow):
    """Standalone tick overlay synchronized only from allowed EQ log data."""

    tray_state_changed = Signal(object, bool)

    def __init__(self):
        self.name = "tick"
        super().__init__()
        self.setWindowTitle("Server Tick")
        self._title.setText("Server Tick")
        self._clock = ServerTickClock()
        self._last_character = ""
        self._last_render_state = None
        self._setup_ui()
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._render)
        self._render_timer.start()
        self._render()

    def _setup_ui(self):
        self.header_tick = QFrame()
        self.header_tick.setObjectName("ServerTickHeader")
        self.header_tick.setAccessibleName("Compact server tick progress")
        self.header_tick.setToolTip(
            "Server Tick keeps counting while this panel is rolled up")
        header_layout = QVBoxLayout(self.header_tick)
        header_layout.setContentsMargins(2, 1, 2, 1)
        header_layout.setSpacing(1)
        self.header_countdown = QLabel("—")
        self.header_countdown.setObjectName("ServerTickHeaderCountdown")
        self.header_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_countdown.setAccessibleName(
            "Time until the next server tick")
        header_layout.addWidget(self.header_countdown)
        self.header_progress = QProgressBar()
        self.header_progress.setObjectName("ServerTickHeaderProgress")
        self.header_progress.setRange(0, 1000)
        self.header_progress.setTextVisible(False)
        self.header_progress.setAccessibleName("Compact server tick phase")
        header_layout.addWidget(self.header_progress)
        self.header_tick.hide()
        self.menu_area.addWidget(self.header_tick, 0)

        panel = QFrame()
        panel.setObjectName("ServerTickPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 5)
        layout.setSpacing(3)

        readout = QHBoxLayout()
        readout.setContentsMargins(0, 0, 0, 0)
        self.countdown = QLabel("—")
        self.countdown.setObjectName("ServerTickCountdown")
        self.countdown.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.countdown.setAccessibleName("Time until the next server tick")
        self.countdown.setToolTip(
            "Estimated time until the next tick for the selected mode")
        readout.addWidget(self.countdown, 1)
        self.confidence = QLabel("UNSYNCED")
        self.confidence.setObjectName("ServerTickConfidence")
        self.confidence.setProperty("Confidence", "unsynced")
        self.confidence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.confidence.setToolTip(
            "ESTIMATE uses zoning; MANUAL uses Sync now; LOCKED uses a live log event")
        readout.addWidget(self.confidence, 0)
        layout.addLayout(readout)

        self.progress = QProgressBar()
        self.progress.setObjectName("ServerTickProgress")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Server tick phase")
        self.progress.setToolTip(
            "Fills toward the next tick and flashes when the tick arrives")
        layout.addWidget(self.progress)

        self.source = QLabel(
            "Click Sync now when you see your HP or mana regenerate")
        self.source.setObjectName("ServerTickSource")
        self.source.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.source.setToolTip(
            "The current synchronization source; log-only anchors can drift and are refreshed often")
        layout.addWidget(self.source)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        self.mode = QComboBox()
        self.mode.addItem("Player tick", "player")
        self.mode.addItem("Target DoT", "target")
        saved_mode = config.data["tick"].get("mode", "player")
        self.mode.setCurrentIndex(max(0, self.mode.findData(saved_mode)))
        self.mode.setAccessibleName("Server tick mode")
        self.mode.setToolTip(
            "Player: med/regen tick. Target DoT: the latest mob receiving your DoT damage")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        controls.addWidget(self.mode, 1)

        self.auto = QToolButton()
        self.auto.setObjectName("ServerTickAuto")
        self.auto.setIcon(game_icon("follow"))
        self.auto.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.auto.setCheckable(True)
        self.auto.setChecked(config.data["tick"].get("auto_sync", True))
        self.auto.setAccessibleName("Automatically synchronize from the EQ log")
        self.auto.setToolTip(
            "Use zoning and your own spell fades for Player mode, or DoT damage for Target mode")
        self.auto.toggled.connect(self._auto_changed)
        controls.addWidget(self.auto, 0)

        self.sync_button = QPushButton("Sync")
        self.sync_button.setIcon(game_icon("refresh"))
        self.sync_button.setToolTip(
            "Set tick zero now; press when HP or mana visibly regenerates")
        self.sync_button.setAccessibleName("Synchronize the server tick now")
        self.sync_button.clicked.connect(self.sync_now)
        controls.addWidget(self.sync_button, 0)

        self.clear_button = QPushButton()
        self.clear_button.setIcon(game_icon("stop"))
        self.clear_button.setAccessibleName("Clear server tick synchronization")
        self.clear_button.setToolTip("Clear the current tick anchor")
        self.clear_button.clicked.connect(self.clear_sync)
        controls.addWidget(self.clear_button, 0)
        layout.addLayout(controls)
        self.content.addWidget(panel, 1)

    def resizeEvent(self, event):
        """Never expose a clipped half-control state in this fixed dashboard."""
        super().resizeEvent(event)
        if (self._collapsed or self.maximumHeight() <= 30 or
                not hasattr(self, '_design_size')):
            return
        base_minimum = max(48, round(
            self._design_size.height() * self._effective_minimum_scale()))
        # Keep the stored minimum independent from the previous width. This
        # lets a later horizontal drag shrink the complete replica instead of
        # inheriting a stale, taller minimum from its former size.
        if self.minimumHeight() != base_minimum:
            self.setMinimumHeight(base_minimum)
        scale = max(
            self._effective_minimum_scale(),
            self.width() / max(1, self._design_size.width()))
        required = max(48, round(self._design_size.height() * scale))
        if self.height() < required:
            QTimer.singleShot(0, lambda: self._enforce_complete_height(required))

    def _enforce_complete_height(self, required):
        if (not self._collapsed and self.maximumHeight() > 30 and
                self.height() < int(required)):
            self.resize(self.width(), int(required))

    def _mode_changed(self):
        config.data["tick"]["mode"] = self.mode.currentData()
        config.save()
        self._clock.clear()
        self._render(force=True)

    def _set_collapsed(self, collapsed):
        # Make the compact readout part of the header before ParserWindow
        # measures the rolled width, then publish the new tray state.
        if hasattr(self, "header_tick"):
            self.header_tick.setVisible(bool(collapsed))
        super()._set_collapsed(collapsed)
        self._render(force=True)

    def _minimize_to_tray(self):
        super()._minimize_to_tray()
        self._render(force=True)

    def _auto_changed(self, enabled):
        config.data["tick"]["auto_sync"] = bool(enabled)
        config.save()

    def sync_now(self):
        entity = "Player" if self.mode.currentData() == "player" else "Target"
        self._clock.sync(
            time.monotonic(), "Manual sync", "manual", entity)
        self._render(force=True)

    def clear_sync(self):
        self._clock.clear()
        self._render(force=True)

    def spell_faded(self, target, spell_name):
        if (not self.auto.isChecked() or self.mode.currentData() != "player"
                or str(target) != "__you__"):
            return
        spell_name = str(spell_name or "Spell")
        self._clock.sync(
            time.monotonic(), f"Self fade · {spell_name}", "locked",
            "Player", f"self:{spell_name.casefold()}")
        self._render(force=True)

    def parse(self, _timestamp, text):
        character = str(getattr(self, "_active_character", "") or "")
        if character and self._last_character and character != self._last_character:
            self._clock.clear()
        if character:
            self._last_character = character

        zone = ZONE_RX.match(str(text or ""))
        if zone:
            self._clock.clear()
            if self.auto.isChecked() and self.mode.currentData() == "player":
                self._clock.sync(
                    time.monotonic(), f"Zone entry · {zone.group('zone')}",
                    "estimate", "Player")
            self._render(force=True)
            return

        if not self.auto.isChecked() or self.mode.currentData() != "target":
            return
        dot = DOT.match(str(text or ""))
        if not dot:
            return
        target = dot.group("target").strip()
        spell = dot.group("spell").strip()
        self._clock.sync(
            time.monotonic(), f"DoT · {spell}", "locked", target,
            f"dot:{target.casefold()}:{spell.casefold()}")
        self._render(force=True)

    def _render(self, force=False):
        snapshot = self._clock.snapshot(time.monotonic())
        compact = bool(self._collapsed or not self.isVisible())
        state = (
            snapshot.synced, round(snapshot.remaining, 1), snapshot.pulse,
            snapshot.source, snapshot.confidence, snapshot.entity,
            round(snapshot.period, 3), compact)
        if not force and state == self._last_render_state:
            return
        self._last_render_state = state
        if not snapshot.synced:
            self.countdown.setText("—")
            self.progress.setValue(0)
            self.header_countdown.setText("—")
            self.header_progress.setValue(0)
            self.source.setText(
                "Click Sync now when you see your HP or mana regenerate")
        else:
            countdown_text = (
                "TICK" if snapshot.pulse else f"{snapshot.remaining:.1f}s")
            progress_value = (
                1000 if snapshot.pulse else round(snapshot.progress * 1000))
            self.countdown.setText(countdown_text)
            self.progress.setValue(progress_value)
            self.header_countdown.setText(countdown_text)
            self.header_progress.setValue(progress_value)
            subject = f" · {snapshot.entity}" if snapshot.entity else ""
            self.source.setText(
                f"{snapshot.source}{subject} · cycle {snapshot.period:.3f}s")
        for progress in (self.progress, self.header_progress):
            progress.setProperty("Pulse", snapshot.pulse)
            progress.setProperty("Synced", snapshot.synced)
            progress.setStyle(progress.style())
        confidence = snapshot.confidence if snapshot.synced else "unsynced"
        self.confidence.setText(confidence.upper())
        self.confidence.setProperty("Confidence", confidence)
        self.confidence.setStyle(self.confidence.style())
        self.countdown.setAccessibleDescription(
            "Tick now" if snapshot.pulse and snapshot.synced else
            f"{snapshot.remaining:.1f} seconds remaining" if snapshot.synced else
            "Not synchronized")
        self.header_countdown.setAccessibleDescription(
            self.countdown.accessibleDescription())
        self.tray_state_changed.emit(snapshot, compact)
