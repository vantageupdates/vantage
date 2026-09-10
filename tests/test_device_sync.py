import copy

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from vantage.helpers.device_sync import (
    DeviceSyncDialog, DeviceSyncError, apply_sync_settings, build_pair_code,
    decode_pair_code, export_sync_settings, sign_snapshot, verify_snapshot)


DEVICE_ID = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
GROUP_ID = "0123456789abcdef01234567"
GROUP_KEY = "abcdefghijklmnopqrstuvwxyzABCDEFGH_12345678"


class _FakeController(QObject):
    status_changed = Signal(str)
    state_changed = Signal()
    progress_changed = Signal(int)
    installation_finished = Signal(bool)

    installed = False
    installing = False
    operation_busy = False
    running = False

    def start(self):
        return False

    def pair_code(self):
        raise DeviceSyncError("not ready")

    def pending(self):
        return list(getattr(self, "pending_rows", []))

    def peers(self):
        return list(getattr(self, "peer_rows", []))

    def install(self):
        pass

    def join(self, _code):
        pass

    def approve(self, *_args):
        pass

    def remove(self, *_args):
        pass


def test_pair_code_is_account_free_copy_paste_invitation():
    code = build_pair_code(DEVICE_ID, "Gaming Laptop", GROUP_ID, GROUP_KEY)

    assert code.startswith("VANTAGE-SYNC-1.")
    assert decode_pair_code("  " + code + "\n") == {
        "device": DEVICE_ID,
        "name": "Gaming Laptop",
        "group": GROUP_ID,
        "key": GROUP_KEY,
    }


@pytest.mark.parametrize("code", ("", "VANTAGE-SYNC-1.bad", "other"))
def test_pair_code_rejects_incomplete_or_damaged_values(code):
    with pytest.raises(DeviceSyncError):
        decode_pair_code(code)


def test_portable_profile_excludes_paths_connections_and_secrets():
    source = {
        "general": {
            "eq_log_dir": r"C:\EQ\Logs",
            "audio_muted": True,
            "auto_install_updates": True,
            "geometry": [1, 2, 3, 4],
        },
        "market": {"live_watch_items": ["Manastone"], "api_token": "no"},
        "sharing": {"url": "https://private.invalid", "group_key": "no"},
        "mobile": {"eq_executable": r"C:\EQ\eqgame.exe"},
        "vantage_ui": {
            "eq_dir": r"D:\EQ", "auto_update": True,
            "pending_profile_sync": {
                "eq_root": r"D:\EQ", "skin_folder": "VantageUI-v1.2.3"}},
        "device_sync": {"group_secret": "no"},
    }

    portable = export_sync_settings(source)

    assert portable["general"] == {
        "audio_muted": True, "auto_install_updates": True,
        "geometry": [1, 2, 3, 4]}
    assert portable["market"] == {"live_watch_items": ["Manastone"]}
    assert portable["vantage_ui"] == {"auto_update": True}
    assert "sharing" not in portable
    assert "mobile" not in portable
    assert "device_sync" not in portable


def test_layout_can_be_disabled_without_losing_settings():
    portable = export_sync_settings({
        "quickbar": {"geometry": [1, 2, 3, 4], "opacity": 90,
                     "show_server_tick": False},
        "zones": {"column_widths": {"items": [20, 30]}, "last_zone": "velks"},
    }, include_layout=False)

    assert portable == {
        "quickbar": {"show_server_tick": False},
        "zones": {"last_zone": "velks"},
    }


def test_smart_timers_are_an_explicit_portable_sync_category():
    source = {
        "timers": {
            "items": [{"id": "frenzy", "zone": "gukbottom",
                       "phase": "respawn", "ends_at": 12345.0}],
            "view_zone": "gukbottom",
        },
        "market": {"live_watch_items": ["Manastone"]},
    }

    assert export_sync_settings(source)["timers"] == source["timers"]
    assert "timers" not in export_sync_settings(
        source, include_timers=False)
    current = {"timers": {"items": [{"id": "local"}]}, "market": {}}
    apply_sync_settings(current, source, include_timers=False)
    assert current["timers"] == {"items": [{"id": "local"}]}


def test_apply_preserves_machine_local_values():
    current = {
        "general": {"eq_log_dir": r"C:\Local\Logs", "audio_muted": False},
        "vantage_ui": {"eq_dir": r"C:\Local\EQ", "auto_update": False},
        "device_sync": {"group_secret": "local"},
    }
    incoming = {
        "general": {"eq_log_dir": r"D:\Remote\Logs", "audio_muted": True},
        "vantage_ui": {"eq_dir": r"D:\Remote\EQ", "auto_update": True},
        "device_sync": {"group_secret": "remote"},
    }

    result = apply_sync_settings(copy.deepcopy(current), incoming)

    assert result["general"]["eq_log_dir"] == r"C:\Local\Logs"
    assert result["general"]["audio_muted"] is True
    assert result["vantage_ui"]["eq_dir"] == r"C:\Local\EQ"
    assert result["vantage_ui"]["auto_update"] is True
    assert result["device_sync"]["group_secret"] == "local"


def test_snapshot_signature_detects_changes():
    payload = {"schema": 1, "device": DEVICE_ID, "settings": {"x": 1}}
    signed = sign_snapshot(payload, GROUP_KEY)

    assert verify_snapshot(signed, GROUP_KEY)
    signed["settings"]["x"] = 2
    assert not verify_snapshot(signed, GROUP_KEY)


def test_dialog_uses_scaled_surface_and_announces_changed_status():
    app = QApplication.instance() or QApplication([])
    controller = _FakeController()
    dialog = DeviceSyncDialog(controller)

    assert dialog.scaled_surface.layout() is not None
    controller.status_changed.emit("Waiting for approval")
    app.processEvents()
    assert dialog.status.text() == "Waiting for approval"
    assert dialog.status.accessibleDescription() == "Waiting for approval"
    dialog.close()


def test_dialog_preserves_peer_selection_during_status_refresh():
    app = QApplication.instance() or QApplication([])
    controller = _FakeController()
    controller.peer_rows = [
        {"id": DEVICE_ID, "name": "Gaming Laptop", "connected": True}]
    dialog = DeviceSyncDialog(controller)
    dialog.refresh()
    dialog.peers.setCurrentRow(0)

    controller.state_changed.emit()
    app.processEvents()

    assert dialog.peers.currentItem().data(256)[1] == DEVICE_ID
    dialog.close()
