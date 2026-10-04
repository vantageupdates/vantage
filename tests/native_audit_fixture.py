"""Shared disposable native-UI fixture used only by audit/test subprocesses.

Call ``isolate`` before importing application modules. It always replaces an
inherited profile and disables game discovery, native audio, network replies,
log monitoring, indexing, updates, and background sharing services.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
from urllib.error import URLError
import urllib.request


def isolate():
    profile = Path(tempfile.mkdtemp(prefix="vantage-native-audit-"))
    os.environ["VANTAGE_DATA_DIR"] = str(profile)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    for name in ("VANTAGE_UPDATED_FROM", "VANTAGE_OPEN_UI_AFTER_UPDATE",
                 "VANTAGE_UPDATE_ERROR"):
        os.environ.pop(name, None)

    def no_python_network(*_args, **_kwargs):
        raise URLError("Python network disabled in the synthetic native audit")

    urllib.request.urlopen = no_python_network
    urllib.request.OpenerDirector.open = no_python_network
    socket.socket.connect = no_python_network
    socket.socket.connect_ex = no_python_network

    from PySide6.QtCore import QIODevice, QTimer
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply
    from PySide6.QtWidgets import QSystemTrayIcon

    class OfflineReply(QNetworkReply):
        def __init__(self, manager, request):
            super().__init__(manager)
            self.setRequest(request)
            self.setUrl(request.url())
            self.open(QIODevice.OpenModeFlag.ReadOnly)
            self.setError(
                QNetworkReply.NetworkError.ConnectionRefusedError,
                "External network disabled in the synthetic native audit")
            QTimer.singleShot(0, self._finish)

        def _finish(self):
            self.setFinished(True)
            self.errorOccurred.emit(self.error())
            self.finished.emit()

        def abort(self):
            pass

        def readData(self, _maximum):
            return b""

    def offline_request(manager, request, *_args, **_kwargs):
        return OfflineReply(manager, request)

    for method in ("get", "post", "put", "head", "deleteResource",
                   "sendCustomRequest"):
        setattr(QNetworkAccessManager, method, offline_request)
    QSystemTrayIcon.show = lambda self: None

    from vantage.helpers import audio, config, ui_skin_updater
    from vantage.helpers.game_capture import GameWindowCapture
    audio.prewarm_speech_engine = lambda *_args, **_kwargs: None
    audio._speech_engine = lambda: None
    audio.play_alert = lambda *_args, **_kwargs: False
    audio.speak_text = lambda *_args, **_kwargs: False
    audio.speech_voice_names = lambda: []
    ui_skin_updater.game_running = lambda: False
    GameWindowCapture._prepare_win32 = lambda self: False
    GameWindowCapture._find_window = lambda self: None
    GameWindowCapture.detect_running_executable = lambda self: ""
    GameWindowCapture.discover_executables = lambda self: []
    GameWindowCapture.is_game_foreground = lambda self: False
    GameWindowCapture.status = lambda self: self._status(
        False, "Synthetic audit: live game discovery and capture disabled")

    from vantage.parsers.log_searcher import LogSearcher
    from vantage.parsers.opendkp import OpenDKP
    from vantage.parsers.vantage_ui import VantageUI
    from vantage.parsers.vitals import Vitals

    Vitals.poll_now = lambda self: None
    LogSearcher.refresh_index = lambda self, **_kwargs: False
    OpenDKP._restore_active_guild = lambda self: None
    VantageUI._automatic_check = lambda self: None
    VantageUI._schedule_profile_sync = lambda self, *_args, **_kwargs: False
    VantageUI._try_pending_profile_sync = lambda self, *_args, **_kwargs: False
    VantageUI._request_profile_sync_elevation = lambda self, *_args: None
    VantageUI._poll_profile_sync_elevation = lambda self: None

    # Importing application verifies/reloads settings. Apply synthetic paths
    # AFTER that import, so startup cannot restore the installed EQ defaults.
    from vantage.helpers.application import VantageApp

    eq_root = profile / "synthetic-everquest"
    (eq_root / "Logs").mkdir(parents=True)
    (eq_root / "uifiles" / "default").mkdir(parents=True)
    (eq_root / "eqgame.exe").write_bytes(b"Synthetic audit marker; not executable")
    for character, server, skin in (
            ("AuditCleric", "p1999green", "default"),
            ("AuditWarrior", "p1999blue", "default"),
            ("AuditWizard", "p1999green", "MissingSyntheticSkin")):
        (eq_root / f"UI_{character}_{server}.ini").write_text(
            f"[Main]\nUISkin={skin}\n", encoding="ascii")

    general = config.data.setdefault("general", {})
    general.update({
        "eq_log_dir": str(eq_root / "Logs"),
        "audio_muted": True, "master_volume": 0,
        "reduce_motion": True, "update_check": False,
        "auto_install_updates": False, "log_archive_enabled": False,
    })
    config.data.setdefault("sharing", {})["enabled"] = False
    config.data.setdefault("device_sync", {}).update({
        "enabled": False, "device_name": "Synthetic audit PC",
    })
    config.data.setdefault("mobile", {})["auto_start"] = False
    config.data["mobile"]["game_enabled"] = False
    config.data.setdefault("vantage_ui", {}).update({
        "eq_dir": str(eq_root),
        "auto_update": False, "auto_apply_profiles": False,
        "pending_profile_sync": {},
    })

    VantageApp._toggle = lambda self: None
    VantageApp._schedule_update_check = lambda self, *_args: None
    VantageApp._log_health_check = lambda self: None
    VantageApp._ensure_location_sharing = lambda self: None
    VantageApp._auto_start_mobile_share = lambda self: None
    VantageApp._auto_start_device_sync = lambda self: None
    return profile
