import math
import os
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontDatabase, QIcon, QPainter, QPalette,
    QPen, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon)
import semver

from vantage.helpers import config, logreader, resource_path
from vantage.helpers.audio import (
    audio_muted, play_alert, set_audio_muted, sound_display_name, speak_text)
from vantage.helpers.camp_session import CampSessionController
from vantage.helpers.character_context import CharacterContextTracker
from vantage.helpers.icons import WINDOW_ICONS, game_icon
from vantage.helpers.interaction import ButtonPolishFilter
from vantage.helpers.log_archive import LogArchiveService
from vantage.helpers.logreader import LogReaderSignals
from vantage.helpers.notification_overlay import NotificationOverlayManager
from vantage.helpers.portable import data_dir
from vantage.helpers.splash import StartupSplash
from vantage.helpers.updater import UpdateController
from vantage.helpers.update_toast import QuickUpdateToast
from vantage.parsers.combat import Combat
from vantage.parsers.heals import HealChain
from vantage.parsers.maps import Maps
from vantage.parsers.maps.window import MapsSignals
from vantage.parsers.market import GreenMarket
from vantage.parsers.quickbar import QuickBar
from vantage.parsers.spells import Spells
from vantage.parsers.tick import ServerTick
from vantage.parsers.timers import SpawnTimers

_config_dir = data_dir()
config.load(str(_config_dir / 'vantage.config.json'))
# validate settings file
config.verify_settings()

CURRENT_VERSION = semver.VersionInfo(
    major=1,
    minor=44,
    patch=28,
    build=""
)


class SettingsSignals(QObject):
    config_updated = Signal()
    spell_triggers_updated = Signal()


class LocationSharingSignals(QObject):
    textMessageReceived = Signal(str)


class VantageApp(QApplication):
    """Application Control."""

    def __init__(self, *args):
        super().__init__(*args)
        # Keep the tray application alive even when every parser is hidden.
        self.setQuitOnLastWindowClosed(False)

        self._button_polish = ButtonPolishFilter(self)
        self.installEventFilter(self._button_polish)

        # Theme and bundled fonts must exist before any parser window is built.
        QFontDatabase.addApplicationFont(resource_path('data/fonts/NotoSans-Regular.ttf'))
        QFontDatabase.addApplicationFont(resource_path('data/fonts/NotoSans-Bold.ttf'))
        interface_font = QFont("Noto Sans")
        interface_font.setHintingPreference(
            QFont.HintingPreference.PreferFullHinting)
        interface_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.setFont(interface_font)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor('#C7AE76'))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor('#9D895E'))
        self.setPalette(palette)
        self._apply_theme()
        self.setWindowIcon(QIcon(resource_path('data/ui/icon.png')))
        self._splash = StartupSplash()
        self._splash.show_centered()
        self._splash.step("Loading preferences and profiles…", 12)

        # Updates
        self._toggled = False
        self._log_reader = None
        self._log_status = "NO LOGS"
        self._last_log_activity = None
        self._last_audio = "None yet"
        self._last_audio_event = None
        self._last_audio_blocked = "None yet"
        set_audio_muted(config.data['general'].get('audio_muted', False))

        # Load Signals
        self._signals = {}
        self._signals["logreader"] = LogReaderSignals()
        self._signals["settings"] = SettingsSignals()
        self._signals["maps"] = MapsSignals()
        self._signals["locationsharing"] = LocationSharingSignals()

        # Exact local-log character, group and pet context.  The bounded
        # profiles persist only compact derived state, never duplicate logs.
        self._character_context = CharacterContextTracker(
            config.data['general'].get('character_profiles', {}))
        self._camp_sessions = CampSessionController(self)
        self._camp_sessions.camp_completed.connect(self._camp_completed)
        self._camp_sessions.state_changed.connect(self._camp_state_changed)

        # Independent game overlay: no Windows balloon, no focus stealing.
        self._notification_overlay = NotificationOverlayManager()
        self.aboutToQuit.connect(self._notification_overlay.close)

        # Load Services
        self._services = {}
        self._services["locationsharing"] = None
        self._signals["settings"].config_updated.connect(
            self._sharing_config_updated)
        if config.data.get("sharing", {}).get("enabled", False):
            self._ensure_location_sharing()

        # Load Parsers
        self._load_parsers()
        self._splash.step("Preparing lightweight on-demand tools…", 82)
        self._settings_instance = None
        self._update_dialog_instance = None
        self._log_monitor_dialog_instance = None
        self._update_controller = UpdateController(CURRENT_VERSION, self)
        self._update_controller.check_finished.connect(
            self._update_check_finished)
        self._update_controller.update_available.connect(
            self._update_available)
        self._update_toast = QuickUpdateToast(
            self._update_controller, self)
        self._mobile_share_instance = None
        self._mobile_dialog_instance = None
        self._spell_library_dialog = None
        self._about_dialog_instance = None
        self._splash.step("Finishing tray and log monitoring…", 91)

        # Tray Icon
        self._system_tray = QSystemTrayIcon()
        self._base_tray_icon = QIcon(resource_path('data/ui/icon.png'))
        self._tick_tray_icon_cache = {}
        self._tick_tray_icon_key = None
        self._tray_tick_text = ""
        self._system_tray.setIcon(self._base_tray_icon)
        self._system_tray.setToolTip("Vantage · P99 Companion")
        # self._system_tray.setContextMenu(self._create_menu())
        self._system_tray.activated.connect(self._menu)
        self._system_tray.show()
        tick = self._parsers_dict["tick"]
        tick.tray_state_changed.connect(self._server_tick_tray_update)
        tick._render(force=True)
        self._log_archive_service = LogArchiveService(self)
        self._log_archive_service.completed.connect(
            self._log_archive_completed)
        self._signals["logreader"].new_line.connect(self._log_activity)
        self._signals["logreader"].new_line.connect(self._parse)
        self._log_health_timer = QTimer(self)
        self._log_health_timer.setInterval(15000)
        self._log_health_timer.timeout.connect(self._log_health_check)
        self._log_health_timer.start()

        # Turn On
        self._toggle()
        self._splash.complete()

        updated_from = os.environ.pop("VANTAGE_UPDATED_FROM", "").strip()
        update_error = os.environ.pop("VANTAGE_UPDATE_ERROR", "").strip()
        if updated_from:
            self._update_toast.show_success(updated_from, CURRENT_VERSION)
            self.show_overlay_notification(
                "Vantage updated",
                f"Updated from {updated_from} to {CURRENT_VERSION}.",
                msecs=6500, overlay_id="alerts")
        elif update_error:
            self.show_overlay_notification(
                "Vantage update",
                update_error, msecs=8500, overlay_id="alerts",
                text_color="#E08372")
        QTimer.singleShot(15000, self._maybe_check_updates)

    def _log_archive_completed(self, report):
        if report.moved:
            count = len(report.moved)
            self.show_overlay_notification(
                "Vantage · Log archive",
                f"Archived {count} oversized EQ log" +
                ("s" if count != 1 else "") +
                ". The files remain recoverable in Logs\\archive.",
                msecs=6500, overlay_id="alerts")
        elif report.errors:
            self.show_overlay_notification(
                "Vantage · Log archive",
                "Archive check could not move an EQ log. The original file "
                "was left in place.",
                msecs=6500, overlay_id="alerts", text_color="#E08372")

    def _load_parsers(self):
        self._splash.step("Loading maps and game data…", 24)
        maps = Maps()
        self._splash.step("Indexing buffs, icons, and triggers…", 42)
        spells = Spells()
        self._splash.step("Restoring Smart Timers and Server Tick…", 58)
        tick = ServerTick()
        spells.spell_faded.connect(tick.spell_faded)
        timers = SpawnTimers()
        self._splash.step("Preparing combat and Market…", 70)
        combat = Combat()
        heals = HealChain()
        market = GreenMarket()
        self._parsers_dict = {
            "maps": maps,
            "spells": spells,
            "tick": tick,
            "timers": timers,
            "combat": combat,
            "heals": heals,
            "market": market,
        }
        quickbar = QuickBar(self, self._parsers_dict)
        self._parsers_dict["quickbar"] = quickbar
        self._parsers = [
            self._parsers_dict["quickbar"],
            self._parsers_dict["maps"],
            self._parsers_dict["spells"],
            self._parsers_dict["tick"],
            self._parsers_dict["timers"],
            self._parsers_dict["combat"],
            self._parsers_dict["heals"],
            self._parsers_dict["market"],
        ]
        # Launcher-first startup: build every parser once, but expose only the
        # Quick Bar. This prevents taskbar/window flashes and leaves each tool
        # one click away with its saved geometry intact.
        for parser in self._parsers:
            parser.finish_startup(show_on_launch=parser is quickbar)

    @property
    def _settings(self):
        """Create the large settings surface only when it is first requested."""
        if self._settings_instance is None:
            from vantage.helpers.settings import SettingsWindow
            self._settings_instance = SettingsWindow()
        return self._settings_instance

    @property
    def _mobile_share(self):
        self._ensure_mobile_share()
        return self._mobile_share_instance

    @property
    def _mobile_dialog(self):
        self._ensure_mobile_share()
        return self._mobile_dialog_instance

    def _ensure_mobile_share(self):
        if self._mobile_share_instance is not None:
            return
        from vantage.helpers.mobile_share import (
            MobileShareController, MobileShareDialog)
        self._mobile_share_instance = MobileShareController(
            self._mobile_snapshot,
            timer_action_handler=self._parsers_dict["timers"].mobile_action,
            parent=self)
        self._mobile_dialog_instance = MobileShareDialog(
            self._mobile_share_instance)
        self.aboutToQuit.connect(self._mobile_share_instance.stop)

    def _ensure_location_sharing(self):
        if self._services.get("locationsharing") is not None:
            return self._services["locationsharing"]
        from vantage.helpers.location_service import LocationSharingService
        service = LocationSharingService()
        self._services["locationsharing"] = service
        return service

    def _sharing_config_updated(self):
        if config.data.get("sharing", {}).get("enabled", False):
            self._ensure_location_sharing()

    def _toggle(self):
        if not self._toggled:
            try:
                config.verify_paths()
            except ValueError as error:
                self._set_log_status(
                    "NO LOGS",
                    f"{error.args[1]}\n\nType /log on in EverQuest, then select "
                    "the EverQuest\\Logs folder in Vantage.",
                    notify=True)

            else:
                self._log_reader = logreader.LogReader(
                    os.path.abspath(config.data['general']['eq_log_dir']))
                self._toggled = True
                self._last_log_activity = None
                self._set_log_status(
                    "WAITING",
                    "Logs linked. Vantage is waiting for EverQuest events.",
                    notify=True)
        else:
            if self._log_reader:
                self._log_reader.deleteLater()
                self._log_reader = None
            self._toggled = False
            self._last_log_activity = None
            self._set_log_status("NO LOGS", "Log monitoring stopped.")

    def _set_log_status(self, status, message="", notify=False):
        changed = status != self._log_status
        self._log_status = status
        self._update_tray_tooltip()
        self._refresh_quickbar()
        if notify and (changed or status == "NO LOGS"):
            self.show_overlay_notification(
                f"Vantage · {status}", message, msecs=6500)

    def _update_tray_tooltip(self):
        parts = ["Vantage", self._log_status]
        if self._tray_tick_text:
            parts.append(self._tray_tick_text)
        parts.append("P99 Companion")
        self._system_tray.setToolTip(" · ".join(parts))

    def _server_tick_tray_update(self, snapshot, compact):
        """Mirror a compact Server Tick in the Windows notification area."""
        active = bool(compact and snapshot.synced)
        if active:
            self._tray_tick_text = (
                "Server Tick NOW" if snapshot.pulse else
                f"Server Tick {snapshot.remaining:.1f}s")
            text = "T" if snapshot.pulse else str(
                max(1, math.ceil(snapshot.remaining)))
            progress_bucket = max(
                0, min(24, round(snapshot.progress * 24)))
            key = (text, progress_bucket, bool(snapshot.pulse))
            if key not in self._tick_tray_icon_cache:
                self._tick_tray_icon_cache[key] = \
                    self._make_tick_tray_icon(
                        text, progress_bucket / 24, snapshot.pulse)
            icon = self._tick_tray_icon_cache[key]
        else:
            self._tray_tick_text = ""
            key = None
            icon = self._base_tray_icon
        if key != self._tick_tray_icon_key:
            self._system_tray.setIcon(icon)
            self._tick_tray_icon_key = key
        self._update_tray_tooltip()

    @staticmethod
    def _make_tick_tray_icon(text, progress, pulse=False):
        """Create a cached 64 px tick badge that remains legible at 16 px."""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#101419"))
        painter.drawRoundedRect(QRectF(3, 3, 58, 58), 15, 15)

        ring = QRectF(7, 7, 50, 50)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#3C434B"), 5))
        painter.drawArc(ring, 90 * 16, -360 * 16)
        color = QColor("#F0C765" if pulse else "#B89552")
        painter.setPen(QPen(color, 5))
        painter.drawArc(
            ring, 90 * 16,
            -round(max(0.0, min(1.0, float(progress))) * 360 * 16))

        font = QFont("Segoe UI Variable", 24, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#F5F1E8"))
        painter.drawText(
            QRectF(8, 7, 48, 49), Qt.AlignmentFlag.AlignCenter, str(text))
        painter.end()
        return QIcon(pixmap)

    def show_overlay_notification(
            self, title, message, msecs=None, position=None,
            overlay_id="alerts", countdown_seconds=0, timer_key=None,
            character="", color="", timer_mode="countdown",
            text_color=""):
        """Show an independent, click-through notice over the active screen."""
        return self._notification_overlay.notify(
            title, message, msecs=msecs, position=position,
            overlay_id=overlay_id, countdown_seconds=countdown_seconds,
            timer_key=timer_key, character=character, color=color,
            timer_mode=timer_mode, text_color=text_color)

    def dismiss_overlay_timer(self, timer_key):
        self._notification_overlay.dismiss_timer(timer_key)

    def arrange_notification_overlays(self):
        """Reveal all notification surfaces for direct placement and sizing."""
        self._notification_overlay.edit_all()

    def is_everquest_foreground(self):
        """Read focus state only; never activates or sends input to EQ."""
        controller = self._mobile_share_instance
        capture = getattr(controller, 'game_capture', None)
        return bool(capture and capture.is_game_foreground())

    def manage_notification_overlays(self, parent=None):
        """Open the user-defined overlay registry and behavior editor."""
        from vantage.helpers.overlay_editor import OverlayManagerDialog
        dialog = OverlayManagerDialog(self._notification_overlay, parent)
        return dialog.exec()

    def audio_playback_allowed(self, channel):
        """Apply the owning panel's background-audio preference."""
        channel = str(channel or "").strip().casefold()
        parser = getattr(self, "_parsers_dict", {}).get(channel)
        if parser is None or (parser.isVisible() and not parser.isMinimized()):
            return True
        return bool(config.data.get(channel, {}).get(
            "sounds_when_hidden", False))

    def audio_blocked(self, source, reason, channel=""):
        """Remember suppressed audio without creating another notification."""
        label = str(source or "Vantage alert")
        owner = str(channel or "").strip().title()
        self._last_audio_blocked = (
            f"{label} · {reason}" + (f" · {owner}" if owner else ""))
        self._refresh_quickbar()

    def audio_started(self, source, sound_path, volume, channel=""):
        """Make every audible event attributable instead of mysterious."""
        self._last_audio_event = (
            str(source or "Vantage alert"), str(sound_path or ""),
            max(0, min(100, int(volume))), str(channel or ""))
        self._last_audio = (
            f"{source} · {sound_display_name(sound_path)} · {volume}%")
        self.show_overlay_notification(
            "Vantage · sound identified", self._last_audio, msecs=4500)
        self._refresh_quickbar()

    def _refresh_quickbar(self):
        quickbar = getattr(self, "_parsers_dict", {}).get("quickbar")
        if quickbar:
            quickbar.refresh_state()

    def _apply_theme(self):
        """Load the bundled theme and resolve portable icon paths."""
        with open(
                resource_path('data/ui/_.css'), encoding='utf-8') as stylesheet:
            theme = stylesheet.read()
        theme = theme.replace(
            '__VANTAGE_CHECK_ICON__',
            resource_path('data/ui/icons/check.svg').replace('\\', '/'))
        theme = theme.replace(
            '__VANTAGE_CHECK_PARTIAL_ICON__',
            resource_path('data/ui/icons/check-partial.svg').replace('\\', '/'))
        theme = theme.replace(
            '__VANTAGE_CHEVRON_TOP_ICON__',
            resource_path('data/ui/icons/chevron-top.svg').replace('\\', '/'))
        theme = theme.replace(
            '__VANTAGE_CHEVRON_BOTTOM_ICON__',
            resource_path('data/ui/icons/chevron-bottom.svg').replace('\\', '/'))
        self.setStyleSheet(theme)

    def reload_ui(self):
        """Re-polish every Vantage surface without touching EverQuest."""
        try:
            self._apply_theme()
            self._signals["settings"].config_updated.emit()
            for parser in self._parsers:
                refresh = getattr(parser, "refresh", None)
                if callable(refresh):
                    refresh()
                parser._surface.updateGeometry()
                parser._scale_scene.setSceneRect(
                    parser._scale_scene.itemsBoundingRect())
                parser._update_uniform_scale()
                parser._update_window_mask()
                parser._scale_view.viewport().update()
                parser.update()
            self._refresh_quickbar()
            if self._mobile_dialog_instance is not None:
                self._mobile_dialog_instance.refresh()
            self.show_overlay_notification(
                "Vantage UI reloaded",
                "Theme, layouts, visible data and saved window settings were reloaded.",
                msecs=4500, overlay_id="alerts")
            return True
        except (OSError, RuntimeError) as error:
            self.show_overlay_notification(
                "Vantage UI reload failed", str(error),
                msecs=6500, overlay_id="alerts", text_color="#E08372")
            return False

    def _log_activity(self, _line):
        self._last_log_activity = time.monotonic()
        if self._toggled and self._log_status != "ONLINE":
            self._set_log_status(
                "ONLINE", "Log activity detected.", notify=True)

    def _log_health_check(self):
        if not self._toggled or self._log_status != 'ONLINE':
            return
        if (self._last_log_activity is not None and
                time.monotonic() - self._last_log_activity > 90):
            self._set_log_status(
                'QUIET',
                'No new log events for 90 seconds. EverQuest may simply be idle; '
                'Vantage is still watching every linked log.',
                notify=True)

    def _show_log_help(self):
        box = QMessageBox()
        box.setWindowTitle("Vantage · Link Logs")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "<b>1.</b> Type <code>/log on</code> in EverQuest.<br>"
            "<b>2.</b> Open Vantage from the system tray icon.<br>"
            "<b>3.</b> Choose <b>Select Logs Folder</b>.<br>"
            "<b>4.</b> Select <code>EverQuest\\Logs</code>.<br><br>"
            "The status changes to <b>ONLINE</b> when the folder is valid."
        )
        box.exec()

    def show_log_help(self):
        self._show_log_help()

    def select_logs_folder(self):
        dir_path = str(QFileDialog.getExistingDirectory(
            None, 'Select Everquest Logs Directory'))
        if not dir_path:
            return False
        if self._toggled:
            self._toggle()
        config.data['general']['eq_log_dir'] = dir_path
        config.save()
        self._toggle()
        self._refresh_quickbar()
        return True

    def show_log_profiles(self):
        from vantage.helpers.log_monitor import LogMonitorDialog
        if self._log_monitor_dialog_instance is None:
            self._log_monitor_dialog_instance = LogMonitorDialog(self)
        self._log_monitor_dialog_instance.refresh()
        self._log_monitor_dialog_instance.show()
        self._log_monitor_dialog_instance.raise_()
        self._log_monitor_dialog_instance.activateWindow()
        return self._log_monitor_dialog_instance

    def toggle_audio_muted(self):
        muted = not audio_muted()
        set_audio_muted(muted)
        config.data['general']['audio_muted'] = muted
        config.save()
        self.show_overlay_notification(
            "Vantage · audio",
            "All sounds are muted." if muted else
            "Vantage sounds are active.",
            msecs=3500)
        self._refresh_quickbar()
        return muted

    def show_last_sound(self):
        """Replay the last attributable sound instead of only naming it."""
        event = self._last_audio_event
        if event is None:
            self.show_overlay_notification(
                "Vantage · last sound", "No Vantage sound has played yet.",
                msecs=5000)
            return False
        if audio_muted():
            self.show_overlay_notification(
                "Vantage · last sound",
                "Sounds are muted. Unmute Vantage to replay the last sound.",
                msecs=5000)
            return False
        source, sound_path, volume, _channel = event
        previous_label = self._last_audio
        if sound_path.startswith("tts:"):
            played = speak_text(
                sound_path[4:], volume, source=f"Replay · {source}",
                allow_hidden=True)
        else:
            played = play_alert(
                sound_path, volume, source=f"Replay · {source}",
                allow_hidden=True)
        # Playback attribution is useful on screen, but the replay itself must
        # not replace the original event or accumulate "Replay · Replay".
        self._last_audio_event = event
        self._last_audio = previous_label
        self._refresh_quickbar()
        if not played:
            self.show_overlay_notification(
                "Vantage · last sound",
                "The last sound could not be replayed.", msecs=5000)
        return played

    def show_settings(self, section=None):
        self._settings._set_values()
        if section:
            self._settings.select_section(section)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()
        return self._settings

    def quit_vantage(self, confirm=True, parent=None):
        """Close Vantage after a safe-by-default manual confirmation.

        Internal update/restart paths intentionally call ``quit()`` directly
        after checkpointing state, so this prompt is reserved for a person's
        Quit action in the Quick Bar or system tray.
        """
        if confirm:
            answer = QMessageBox.question(
                parent, "Quit Vantage?",
                "Quit Vantage?\n\n"
                "Log monitoring, alerts, overlays, and phone sync will stop "
                "until Vantage is opened again. Active spell and spawn timers "
                "are saved and keep counting while the app is closed.\n\n"
                "EverQuest and WinEQ will remain open.",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        if self._toggled:
            self._toggle()
        self._system_tray.setVisible(False)
        config.APP_EXIT = True
        self.quit()
        return True

    def _camp_completed(self, _timestamp, character, server):
        """Persist and clear the exact player-scoped state EQTool clears."""
        spells = self._parsers_dict['spells']
        saved = spells.snapshot_you_spells(character, server)
        _context, changed = self._character_context.store_you_spells_if_empty(
            character, server, saved)
        spells.clear_you_spells(character, server)
        self._parsers_dict['maps'].clear_player_location()
        if changed:
            config.data['general']['character_profiles'] = \
                self._character_context.snapshot()
            config.save()

    def _camp_state_changed(self, state, character, server):
        spells = self._parsers_dict.get('spells')
        if not spells:
            return
        if state == 'welcome':
            _context, saved, changed = \
                self._character_context.take_saved_you_spells(
                    character, server)
            spells.restore_you_spells(saved, character, server)
            spells.set_camp_status('', character)
            if changed:
                config.data['general']['character_profiles'] = \
                    self._character_context.snapshot()
                config.save()
        elif state == 'abandoned':
            spells.set_camp_status('', character)
        else:
            spells.set_camp_status(state, character)

    def _parse(self, new_line):
        if new_line:
            timestamp, text = new_line[:2]
            character = new_line[2] if len(new_line) > 2 else ""
            server = new_line[3] if len(new_line) > 3 else ""
            character_context, context_changed = \
                self._character_context.ingest(character, server, text)
            self._camp_sessions.ingest(
                text, timestamp, character, server)
            # Visibility and parsing are independent. Every parser is
            # event-driven and must keep receiving the log while its window is
            # hidden, just like a dedicated combat/trigger parser.
            for parser in self._parsers:
                parser._active_character = character
                parser._active_server = server
                parser._character_context = character_context
                if text.startswith('toggle_clickthrough_%s' % parser.name):
                    parser._clickthrough = bool(
                        parser._allow_clickthrough and
                        not parser._clickthrough)
                    config.data[parser.name]['clickthrough'] = \
                        parser._clickthrough
                    config.save()
                    parser._set_flags()
                elif text.startswith('toggle_%s' % parser.name):
                    parser.toggle()
                else:
                    parser.parse(timestamp, text)
            if context_changed:
                config.data['general']['character_profiles'] = \
                    self._character_context.snapshot()
                config.save()

    def update_character_level(self, character, server, level):
        """Persist an explicit level edit for the active log profile."""
        if not character:
            return
        _context, changed = self._character_context.set_level(
            character, server, level)
        if changed:
            config.data['general']['character_profiles'] = \
                self._character_context.snapshot()
            config.save()

    def _menu(self, event):
        """Returns a new QMenu for system tray."""
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.setToolTipsVisible(True)
        version_action = menu.addAction(f"Version: {CURRENT_VERSION}")
        version_action.setEnabled(False)
        latest = self._update_controller.latest_info
        update_action = menu.addAction(
            f"Update Available · {latest.version}…"
            if self.new_version_available() else "Check for Updates…")
        update_action.setIcon(game_icon("ph-download"))
        update_action.setToolTip(
            "Check the official vantageupdates/vantage GitHub Release, then "
            "download and verify Vantage.exe")
        menu.addSeparator()
        log_status_action = menu.addAction(f"LOGS · {self._log_status}")
        log_status_action.setEnabled(False)
        log_status_action.setToolTip(
            "Type /log on in EverQuest and link the EverQuest\\Logs folder")
        get_eq_dir_action = menu.addAction('Select Logs Folder')
        get_eq_dir_action.setIcon(game_icon('ph-folder-open'))
        get_eq_dir_action.setToolTip(
            "First type /log on in EverQuest, then select the EverQuest\\Logs folder")
        log_help_action = menu.addAction('How Do I Link Logs?')
        log_help_action.setIcon(game_icon('ph-file-search'))
        log_help_action.setToolTip(
            "Show how to enable /log on and select the correct folder")
        log_profiles_action = menu.addAction('Log Profiles…')
        log_profiles_action.setIcon(game_icon('ph-stack'))
        log_profiles_action.setToolTip(
            'Show ACTIVE, QUIET, or STALE state for every character log')
        menu.addSeparator()
        last_audio_action = menu.addAction(
            f"LAST SOUND · {self._last_audio}")
        last_audio_action.setEnabled(False)
        last_audio_action.setToolTip(
            "Shows exactly which alert produced the most recent sound")
        blocked_audio_action = menu.addAction(
            f"BLOCKED AUDIO · {self._last_audio_blocked}")
        blocked_audio_action.setEnabled(False)
        blocked_audio_action.setToolTip(
            "Shows the most recent sound Vantage prevented because mute was "
            "active or its owning window was hidden")
        mute_audio_action = menu.addAction('Mute All Sounds')
        mute_audio_action.setIcon(game_icon('ph-mute'))
        mute_audio_action.setCheckable(True)
        mute_audio_action.setChecked(audio_muted())
        mute_audio_action.setToolTip(
            "Stop current audio and keep all Vantage sounds muted")
        menu.addSeparator()

        parser_toggles = {}
        for parser in self._parsers:
            label = {
                "quickbar": "Quick Bar",
                "spells": "Buffs & Triggers",
                "tick": "Server Tick",
                "timers": "Smart Timers",
                "heals": "Heal Chain",
                "market": "Market",
            }.get(parser.name, parser.name.title())
            toggle = menu.addAction(label)
            toggle.setIcon(game_icon(WINDOW_ICONS.get(parser.name, 'timer')))
            toggle.setCheckable(True)
            toggle.setChecked(parser.isVisible())
            parser_toggles[toggle] = parser

        spell_library_action = menu.addAction('Spell Library…')
        spell_library_action.setIcon(game_icon('ph-spellbook'))
        spell_library_action.setToolTip(
            'Search P99 spells by class and level, including Wiki acquisition and prices')

        menu.addSeparator()
        settings_action = menu.addAction('Settings')
        settings_action.setIcon(game_icon('ph-settings'))
        mobile_action = menu.addAction('Vantage on Your Phone')
        mobile_action.setIcon(game_icon('ph-mobile'))
        reload_ui_action = menu.addAction('Reload Vantage UI')
        reload_ui_action.setIcon(game_icon('ph-reload'))
        reload_ui_action.setToolTip(
            'Reload the theme, layouts and visible data without closing EverQuest')
        support_action = menu.addAction('Buy me a coffee')
        support_action.setIcon(game_icon('ph-coffee'))
        support_action.setToolTip(
            'Open Vantage Buy Me a Coffee in your default browser')
        support_font = support_action.font()
        support_font.setBold(True)
        support_action.setFont(support_font)
        about_action = menu.addAction('About Vantage…')
        about_action.setIcon(game_icon('ph-info'))
        about_action.setToolTip(
            'View the Vantage version, source code, and open-source licenses')
        menu.addSeparator()
        quit_action = menu.addAction('Quit')
        quit_action.setIcon(game_icon('ph-power'))

        action = menu.exec(QCursor.pos())

        if action == get_eq_dir_action:
            self.select_logs_folder()

        elif action == log_help_action:
            self.show_log_help()

        elif action == log_profiles_action:
            self.show_log_profiles()

        elif action == update_action:
            self.show_update_dialog()

        elif action == mute_audio_action:
            self.toggle_audio_muted()

        elif action == settings_action:
            self.show_settings()

        elif action == mobile_action:
            self.show_mobile_share()

        elif action == reload_ui_action:
            self.reload_ui()

        elif action == support_action:
            self.show_support()

        elif action == about_action:
            self.show_about()

        elif action == spell_library_action:
            self.show_spell_library()

        elif action == quit_action:
            self.quit_vantage(confirm=True)

        elif action in parser_toggles:
            parser_toggles[action].toggle()

    def _maybe_check_updates(self):
        if not config.data['general'].get('update_check', True):
            return
        last_check = float(
            config.data['general'].get('last_update_check', 0.0) or 0.0)
        if time.time() - last_check >= 24 * 60 * 60:
            self._update_controller.check()

    def _update_check_finished(self, _info, _message):
        config.data['general']['last_update_check'] = time.time()
        config.save()
        self._refresh_quickbar()

    def _update_available(self, info):
        self._refresh_quickbar()
        dialog = self._update_dialog_instance
        if dialog is not None and dialog.isVisible():
            return
        self._update_toast.show_for(info)

    def install_quick_update(self, info, staged_path, toast=None):
        """Finish an explicitly clicked one-step update."""
        try:
            self._update_controller.launch_installer(info, staged_path)
        except (OSError, RuntimeError, ValueError) as error:
            if toast:
                toast._failed(f"Update could not start: {error}")
            return False
        self._system_tray.setVisible(False)
        self.quit()
        return True

    def checkpoint_for_update(self):
        """Persist live countdown state before the updater starts another EXE."""
        spells = self._parsers_dict.get('spells')
        timers = self._parsers_dict.get('timers')
        if spells is not None:
            spells.checkpoint_runtime_state()
        if timers is not None:
            timers.checkpoint_runtime_state()
        config.save()
        return True

    def show_update_dialog(self):
        if self._update_dialog_instance is None:
            from vantage.helpers.updater import UpdateDialog
            self._update_dialog_instance = UpdateDialog(
                self._update_controller)
        self._update_dialog_instance.open_and_check()

    def new_version_available(self):
        latest = getattr(self, '_update_controller', None)
        info = latest.latest_info if latest else None
        return bool(info and info.version > CURRENT_VERSION)

    def show_mobile_share(self):
        dialog = self._mobile_dialog
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_support(self):
        """Open voluntary support externally; Vantage never handles payment data."""
        from vantage.helpers.about import SUPPORT_URL, open_external_url
        return open_external_url(SUPPORT_URL)

    def show_about(self):
        if self._about_dialog_instance is None:
            from vantage.helpers.about import AboutDialog
            self._about_dialog_instance = AboutDialog(
                str(CURRENT_VERSION))
        self._about_dialog_instance.show()
        self._about_dialog_instance.raise_()
        self._about_dialog_instance.activateWindow()

    def show_spell_library(self):
        """Open the lazy local/Wiki spell catalog without startup overhead."""
        if self._spell_library_dialog is None:
            from vantage.helpers.spell_library import SpellLibraryDialog
            self._spell_library_dialog = SpellLibraryDialog(
                self._parsers_dict.get("market"),
                self._parsers_dict.get("spells"))
        self._spell_library_dialog.show()
        self._spell_library_dialog.raise_()
        self._spell_library_dialog.activateWindow()

    def _mobile_snapshot(self):
        snapshot = self._parsers_dict["timers"].mobile_snapshot()
        snapshot["market"] = self._parsers_dict["market"].mobile_snapshot()
        return snapshot
