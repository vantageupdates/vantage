import copy

import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.device_sync import (
    DeviceSyncDialog, DeviceSyncError, apply_sync_settings, build_pair_code,
    decode_pair_code, export_sync_settings, sign_snapshot, verify_snapshot)
from vantage.helpers.timer_sync import (
    merge_timer_state, record_explicit_timer_removals,
    record_local_timer_state, timer_identity)


DEVICE_ID = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
GROUP_ID = "0123456789abcdef01234567"
GROUP_KEY = "abcdefghijklmnopqrstuvwxyzABCDEFGH_12345678"


def _buff(name, deadline, target="__you__", character="Spiritflux",
          server="P1999 Green", runtime_key=""):
    return {
        "deadline": float(deadline),
        "target": target,
        "target_created_order": 1,
        "target_marker": "",
        "character": character,
        "server": server,
        "spell": {
            "name": name,
            "runtime_key": runtime_key or name.casefold(),
        },
    }


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


def test_timer_sync_option_excludes_smart_and_spell_runtime_timers():
    source = {
        "spells": {
            "level": 60,
            "active_timer_state": [_buff("Focus of Spirit", 5000)],
            "active_timer_sync": {
                "schema": 1, "versions": {"row": 12.0},
                "tombstones": {"old": 11.0}},
        },
        "timers": {"items": [{"id": "frenzy"}]},
    }

    portable = export_sync_settings(source, include_timers=False)

    assert portable["spells"] == {"level": 60}
    assert "timers" not in portable


def test_concurrent_spiritflux_snapshots_keep_every_unexpired_buff():
    legion_rows = [
        _buff("Focus of Spirit", 5200),
        _buff("Regrowth", 5300),
        _buff("Shroud of the Spirits", 5400),
        _buff("Focus of Spirit", 5500, target="Jonarn"),
        _buff("Shroud of the Spirits", 5600, target="Jonarn"),
        _buff("Riotous Health", 5700, target="Jonarn"),
    ]
    chuwi_rows = [
        _buff("Riotous Health", 5700, target="Jonarn"),
        _buff("Grim Aura", 5800),
    ]
    legion_rows, legion_meta = record_local_timer_state(
        [], legion_rows, {}, now=100.0)
    chuwi_rows, chuwi_meta = record_local_timer_state(
        [], chuwi_rows, {}, now=101.0)

    merged, metadata = merge_timer_state(
        legion_rows, legion_meta, chuwi_rows, chuwi_meta,
        incoming_revision=102.0)

    assert {(row["spell"]["name"], row["target"]) for row in merged} == {
        ("Focus of Spirit", "__you__"),
        ("Regrowth", "__you__"),
        ("Shroud of the Spirits", "__you__"),
        ("Focus of Spirit", "Jonarn"),
        ("Shroud of the Spirits", "Jonarn"),
        ("Riotous Health", "Jonarn"),
        ("Grim Aura", "__you__"),
    }
    assert len(metadata["versions"]) == 7


def test_apply_sync_settings_unions_runtime_rows_instead_of_replacing_list():
    focus = _buff("Focus of Spirit", 5200)
    regrowth = _buff("Regrowth", 5300)
    left_rows, left_meta = record_local_timer_state(
        [], [focus], {}, now=100.0)
    right_rows, right_meta = record_local_timer_state(
        [], [regrowth], {}, now=101.0)
    current = {"spells": {
        "active_timer_state": left_rows,
        "active_timer_sync": left_meta,
    }}

    apply_sync_settings(current, {"spells": {
        "active_timer_state": right_rows,
        "active_timer_sync": right_meta,
    }}, timer_revision=102.0)

    assert {row["spell"]["name"] for row in
            current["spells"]["active_timer_state"]} == {
                "Focus of Spirit", "Regrowth"}


def test_unchanged_restored_timer_preserves_remote_clock():
    focus = _buff("Focus of Spirit", 5200)
    rows, metadata = record_local_timer_state([], [focus], {}, now=100.0)
    restored = copy.deepcopy(rows)
    restored[0]["deadline"] += 0.2

    _rows, after = record_local_timer_state(
        rows, restored, metadata, now=300.0)

    assert after == metadata


def test_timer_identity_separates_profiles_targets_and_instances():
    base = _buff("Focus of Spirit", 5200)
    another_character = _buff(
        "Focus of Spirit", 5200, character="Mindflux")
    target_a = _buff("Focus of Spirit", 5200, target="a goblin")
    target_a["target_marker"] = "A"
    target_b = copy.deepcopy(target_a)
    target_b["target_marker"] = "B"

    identities = {
        timer_identity(row)
        for row in (base, another_character, target_a, target_b)}

    assert len(identities) == 4


def test_partial_snapshot_absence_never_deletes_or_tombstones_live_buff():
    focus = _buff("Focus of Spirit", 5200)
    regrowth = _buff("Regrowth", 5300)
    rows, metadata = record_local_timer_state(
        [], [focus, regrowth], {}, now=100.0)

    rows, metadata = record_local_timer_state(
        rows, [focus], metadata, now=200.0)

    assert {row["spell"]["name"] for row in rows} == {
        "Focus of Spirit", "Regrowth"}
    assert metadata["tombstones"] == {}


def test_explicit_worn_off_propagates_and_newer_recast_can_return():
    focus = _buff("Focus of Spirit", 5200)
    rows, metadata = record_local_timer_state([], [focus], {}, now=100.0)
    stale_rows, stale_metadata = copy.deepcopy(rows), copy.deepcopy(metadata)
    rows, metadata = record_explicit_timer_removals(
        rows, [focus], metadata, now=200.0)

    merged, merged_metadata = merge_timer_state(
        rows, metadata, stale_rows, stale_metadata,
        incoming_revision=210.0)

    assert merged == []
    identity = timer_identity(focus)
    assert merged_metadata["tombstones"][identity] == 200.0

    refreshed = _buff("Focus of Spirit", 6200)
    refreshed_rows, refreshed_meta = record_local_timer_state(
        stale_rows, [refreshed], stale_metadata, now=300.0)
    merged, _metadata = merge_timer_state(
        merged, merged_metadata, refreshed_rows, refreshed_meta,
        incoming_revision=310.0)

    assert len(merged) == 1
    assert merged[0]["deadline"] == 6200.0


def test_schema_one_tombstone_cannot_erase_an_active_row():
    focus = _buff("Focus of Spirit", 5200)
    rows, metadata = record_local_timer_state([], [focus], {}, now=100.0)
    identity = timer_identity(focus)

    merged, merged_metadata = merge_timer_state(
        rows, metadata, [], {
            "schema": 1,
            "versions": {identity: 900.0},
            "tombstones": {identity: 1000.0},
        }, incoming_revision=1100.0)

    assert [row["spell"]["name"] for row in merged] == ["Focus of Spirit"]
    assert merged_metadata["schema"] == 2
    assert identity not in merged_metadata["tombstones"]


def test_legacy_snapshot_absence_cannot_delete_and_shorter_copy_cannot_regress():
    focus = _buff("Focus of Spirit", 6200)
    regrowth = _buff("Regrowth", 6100)
    local_rows, local_meta = record_local_timer_state(
        [], [focus, regrowth], {}, now=100.0)
    stale_focus = _buff("Focus of Spirit", 5100)

    merged, _metadata = merge_timer_state(
        local_rows, local_meta, [stale_focus], {}, incoming_revision=200.0)

    assert {row["spell"]["name"] for row in merged} == {
        "Focus of Spirit", "Regrowth"}
    assert next(row for row in merged
                if row["spell"]["name"] == "Focus of Spirit")[
                    "deadline"] == 6200.0


def test_config_bounds_timer_sync_clocks_and_migrates_invalid_metadata():
    original = config.data
    try:
        config.data = {"spells": {"active_timer_sync": {
            "schema": 2,
            "versions": {
                f"timer-{index}": float(index + 1)
                for index in range(1200)},
            "tombstones": {"bad": "not-a-clock", "valid": 50.0},
        }}}

        config.verify_settings()

        metadata = config.data["spells"]["active_timer_sync"]
        assert metadata["schema"] == 2
        assert len(metadata["versions"]) == 1024
        assert metadata["tombstones"] == {"valid": 50.0}
    finally:
        config.data = original


def test_config_invalidates_flawed_schema_one_timer_clocks():
    original = config.data
    try:
        config.data = {"spells": {"active_timer_sync": {
            "schema": 1,
            "versions": {"live": 100.0},
            "tombstones": {"live": 200.0},
        }}}

        config.verify_settings()

        assert config.data["spells"]["active_timer_sync"] == {
            "schema": 2, "versions": {}, "tombstones": {}}
    finally:
        config.data = original


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
