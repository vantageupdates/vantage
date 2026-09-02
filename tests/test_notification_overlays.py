import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from vantage.helpers import config
from vantage.helpers.notification_overlay import NotificationOverlayManager
from vantage.helpers.overlay_editor import OverlayManagerDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_old_default_faded_opacity_migrates_once_but_user_choice_is_kept():
    migrated = config.normalize_notification_overlays({
        "alerts": {"type": "text", "faded_background_opacity": 35}})
    customized = config.normalize_notification_overlays({
        "alerts": {"type": "text", "faded_background_opacity": 35,
                   "contrast_opacity_version": 1}})

    assert migrated["alerts"]["faded_background_opacity"] == 65
    assert migrated["alerts"]["contrast_opacity_version"] == 1
    assert customized["alerts"]["faded_background_opacity"] == 35


def test_alert_and_timer_overlays_move_resize_lock_and_route(monkeypatch):
    app = _app()
    previous = config.data
    config.data = {"general": {"notification_overlays": (
        config.normalize_notification_overlays({}))}}
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        alerts = manager.overlays["alerts"]
        timers = manager.overlays["timers"]

        alerts.begin_edit()
        alerts.setGeometry(41, 52, 333, 121)
        app.processEvents()
        assert alerts._editing is True
        assert alerts._size_grip.isVisible()
        assert not (
            alerts.windowFlags() &
            Qt.WindowType.WindowTransparentForInput)

        alerts.finish_edit()
        assert config.data["general"]["notification_overlays"]["alerts"][
            "geometry"] == [41, 52, 333, 121]
        assert (
            alerts.windowFlags() &
            Qt.WindowType.WindowTransparentForInput)

        manager.notify("Spawn", "Frenzy soon", overlay_id="timers")
        manager.notify("Charm", "Charm ending", overlay_id="timers")
        app.processEvents()
        assert timers.isVisible()
        assert timers.title.text() == "Charm"
        assert len(timers._rows) == 2
        assert alerts.isHidden()

        config.data["general"]["notification_overlays"]["timers"][
            "group_titles"] = True
        manager.notify("Charm", "Charm broke", overlay_id="timers")
        app.processEvents()
        assert len(timers._rows) == 2
        assert timers.title.text() == "Charm"
        assert timers.message.text() == "Charm broke"

        manager.notify(
            "Root", "Root timer", overlay_id="timers",
            countdown_seconds=60, timer_key="root")
        manager.notify(
            "Root", "Root restarted", overlay_id="timers",
            countdown_seconds=90, timer_key="root")
        app.processEvents()
        keyed = [entry for entry in timers._entries if entry.get("key") == "root"]
        assert len(keyed) == 1
        assert keyed[0]["duration"] == 90
        assert any(row.progress.isVisible() for row in timers._rows)

        manager.dismiss_timer("root")
        assert not any(
            entry.get("key") == "root" for entry in timers._entries)

        manager.notify(
            "LIVE · Bat", "Alice 10 DPS", overlay_id="timers",
            msecs=2500, timer_key="combat-live")
        manager.notify(
            "LIVE · Bat", "Alice 20 DPS", overlay_id="timers",
            msecs=2500, timer_key="combat-live")
        live = [
            entry for entry in timers._entries
            if entry.get("key") == "combat-live"]
        assert len(live) == 1
        assert live[0]["message"] == "Alice 20 DPS"
        assert live[0]["duration"] == 0

        manager.notify(
            "Pull", "Elapsed combat time", overlay_id="timers",
            timer_key="pull", timer_mode="stopwatch")
        app.processEvents()
        stopwatch = next(
            entry for entry in timers._entries if entry.get("key") == "pull")
        assert stopwatch["expires"] is None
        assert stopwatch["timer_mode"] == "stopwatch"
        timers._expire_entries()
        assert any(row.remaining.isVisible() for row in timers._rows)
        manager.dismiss_timer("pull")

        manager.notify(
            "Styled", "Inherited trigger color", overlay_id="alerts",
            text_color="#CC6655")
        app.processEvents()
        styled_row = next(
            row for row in alerts._rows if row.title.text() == "Styled")
        assert "#CC6655" in styled_row.title.styleSheet()
        assert "#CC6655" in styled_row.message.styleSheet()
    finally:
        manager.close()
        config.data = previous


def test_overlay_rows_keep_natural_height_in_a_tall_surface(monkeypatch):
    app = _app()
    previous = config.data
    config.data = {
        "general": {
            "notification_overlays": config.normalize_notification_overlays({})
        },
        "spells": {"custom_timers": []},
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        overlay = manager.overlays["alerts"]
        overlay.resize(320, 300)
        manager.notify("First", "Useful detail", overlay_id="alerts")
        manager.notify("Second", "", overlay_id="alerts")
        app.processEvents()

        assert len(overlay._rows) == 2
        assert all(
            row.sizePolicy().verticalPolicy() ==
            row.sizePolicy().Policy.Fixed
            for row in overlay._rows)
        assert overlay._rows[0].height() <= overlay._rows[0].sizeHint().height()
        empty_row = next(
            row for row in overlay._rows if row.title.text() == "Second")
        assert empty_row.message.isHidden()
        first_bottom = overlay._rows[0].geometry().bottom()
        second_top = overlay._rows[1].geometry().top()
        assert second_top - first_bottom <= 1
    finally:
        manager.close()
        config.data = previous


def test_overlay_registry_create_duplicate_delete_and_reroute(monkeypatch):
    _app()
    previous = config.data
    config.data = {
        "general": {"notification_overlays": {}},
        "spells": {"custom_timers": []},
        "combat": {
            "live_overlay_id": "alerts",
            "secondary_overlay_id": "alerts",
            "tanking_overlay_id": "alerts",
        },
    }
    config.data["general"]["notification_overlays"] = (
        config.normalize_notification_overlays({}))
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        created = manager.create_overlay("timer", "Raid timers")
        assert created in manager.overlays
        assert manager.definitions()[created]["type"] == "timer"
        assert manager.definitions()[created]["label"] == "Raid timers"

        duplicate = manager.duplicate_overlay(created)
        assert duplicate in manager.overlays
        assert manager.definitions()[duplicate]["label"] == "Raid timers copy"

        trigger = [
            "Test", "match", "00:01:00", "", "", "", True, False,
            "Vantage", "Default", created, "restart", "", ""]
        config.data["spells"]["custom_timers"].append(trigger)
        stopwatch = [
            "Stopwatch", "match", "00:00:00", "", "", "", True, False,
            "Vantage", "Default", created, "restart", "", "", "",
            "stopwatch"]
        config.data["spells"]["custom_timers"].append(stopwatch)
        for key in (
                "live_overlay_id", "secondary_overlay_id",
                "tanking_overlay_id"):
            config.data["combat"][key] = created
        assert manager.delete_overlay(created) is True
        assert created not in manager.overlays
        assert trigger[10] != created
        assert trigger[10] in manager.overlays
        assert manager.definitions()[trigger[10]]["type"] == "timer"
        assert stopwatch[10] == trigger[10]
        assert all(
            config.data["combat"][key] in manager.overlays
            for key in (
                "live_overlay_id", "secondary_overlay_id",
                "tanking_overlay_id"))

        manager.notify(
            "Raid", "Incoming", overlay_id=duplicate,
            countdown_seconds=30, timer_key="raid")
        manager.notify(
            "Pull", "Elapsed", overlay_id="deleted-timer",
            timer_mode="stopwatch", timer_key="pull")
        _app().processEvents()
        assert manager.overlays[duplicate].isVisible()
        assert any(
            entry.get("key") == "pull"
            for overlay_id, overlay in manager.overlays.items()
            if manager.definitions()[overlay_id]["type"] == "timer"
            for entry in overlay._entries)
        assert not any(
            entry.get("key") == "pull"
            for overlay_id, overlay in manager.overlays.items()
            if manager.definitions()[overlay_id]["type"] == "text"
            for entry in overlay._entries)
    finally:
        manager.close()
        config.data = previous


def test_overlay_manager_exposes_complete_tooltips(monkeypatch):
    app = _app()
    previous = config.data
    config.data = {
        "general": {
            "notification_overlays": config.normalize_notification_overlays({})
        },
        "spells": {"custom_timers": []},
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    dialog = OverlayManagerDialog(manager)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.overlay_list.count() == 2
        assert dialog.overlay_list.toolTip()
        assert dialog.name.toolTip()
        assert dialog.overlay_type.toolTip()
        assert dialog.max_entries.toolTip()
        assert dialog.font_weight.toolTip()
        assert dialog.background_opacity.toolTip()

        dialog._add("timer")
        assert len(dialog._draft) == 3
        assert dialog._draft[dialog._current_id]["type"] == "timer"
    finally:
        dialog.close()
        manager.close()
        config.data = previous


def test_overlay_honors_twenty_rows_character_sections_and_font_weight(
        monkeypatch):
    app = _app()
    previous = config.data
    definitions = config.normalize_notification_overlays({})
    definitions["timers"].update({
        "max_entries": 20,
        "group_by_character": True,
        "font_weight": "bold",
    })
    config.data = {
        "general": {"notification_overlays": definitions},
        "spells": {"custom_timers": []},
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        for index in range(12):
            manager.notify(
                f"Timer {index}", f"Effect {index}", overlay_id="timers",
                countdown_seconds=60 + index, timer_key=f"timer-{index}",
                character="Alice" if index % 2 == 0 else "Bob")
        app.processEvents()
        overlay = manager.overlays["timers"]
        assert len(overlay._entries) == 12
        assert len(overlay._rows) == 12
        assert [header.text() for header in overlay._section_headers] == [
            "ALICE", "BOB"]
        characters = [
            entry["character"] for entry in overlay._sorted_entries()]
        assert characters == ["Alice"] * 6 + ["Bob"] * 6
        assert overlay._rows[0].title.font().weight() == QFont.Weight.Bold
        assert all(header.toolTip() for header in overlay._section_headers)
    finally:
        manager.close()
        config.data = previous


def test_editor_delete_reroutes_combat_and_trigger_references(monkeypatch):
    _app()
    previous = config.data
    definitions = config.normalize_notification_overlays({})
    definitions["raid_text"] = config.notification_overlay_defaults(
        "raid_text", "text")
    config.data = {
        "general": {"notification_overlays": definitions},
        "spells": {"custom_timers": [[
            "Alert", "match", "00:00:00", "", "", "", True, False,
            "Vantage", "Default", "raid_text", "restart", "", "", "",
            "none"]]},
        "combat": {
            "live_overlay_id": "raid_text",
            "secondary_overlay_id": "raid_text",
            "tanking_overlay_id": "raid_text",
        },
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    dialog = OverlayManagerDialog(manager)
    try:
        del dialog._draft["raid_text"]
        dialog._apply()
        routes = config.data["combat"]
        assert config.data["spells"]["custom_timers"][0][10] == "alerts"
        assert routes == {
            "live_overlay_id": "alerts",
            "secondary_overlay_id": "alerts",
            "tanking_overlay_id": "alerts",
        }
    finally:
        dialog.close()
        manager.close()
        config.data = previous


def test_overlay_resizes_from_every_edge_and_cancel_restores_snapshot(
        monkeypatch):
    app = _app()
    previous = config.data
    definitions = config.normalize_notification_overlays({})
    config.data = {
        "general": {"notification_overlays": definitions},
        "spells": {"custom_timers": []},
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        overlay = manager.overlays["alerts"]
        overlay.setGeometry(200, 160, 320, 150)
        original_geometry = overlay.geometry()
        original_opacity = overlay._settings()["background_opacity"]
        overlay.begin_edit()
        app.processEvents()

        assert set(overlay._resize_handles) == {
            "top", "bottom", "left", "right", "top_left", "top_right",
            "bottom_left", "bottom_right",
        }
        assert all(
            handle.isVisible() and handle.toolTip()
            for handle in overlay._resize_handles.values())
        assert overlay._cancel_button.toolTip()
        assert overlay._lock_button.text() == "Save"
        assert overlay._lock_button.toolTip()

        overlay._settings()["background_opacity"] = 40
        overlay._start_resize("top_left", QPoint(200, 160))
        overlay._drag_resize(QPoint(180, 130))
        resized = overlay.geometry()
        assert resized == original_geometry.adjusted(-20, -30, 0, 0)
        overlay._stop_resize()

        overlay.cancel_edit()
        assert overlay.geometry() == original_geometry
        assert overlay._settings()["background_opacity"] == original_opacity
        assert overlay.isHidden()
        assert (
            overlay.windowFlags() &
            Qt.WindowType.WindowTransparentForInput)

        overlay.begin_edit()
        overlay._start_resize("bottom_right", QPoint(520, 310))
        overlay._drag_resize(QPoint(565, 335))
        overlay._stop_resize()
        overlay.finish_edit()
        assert config.data["general"]["notification_overlays"]["alerts"][
            "geometry"] == [200, 160, 365, 175]
    finally:
        manager.close()
        config.data = previous


def test_arrangement_properties_can_delete_an_overlay(monkeypatch):
    _app()
    previous = config.data
    config.data = {
        "general": {
            "notification_overlays": config.normalize_notification_overlays({})
        },
        "spells": {"custom_timers": []},
    }
    monkeypatch.setattr(config, "save", lambda: None)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    manager = NotificationOverlayManager()
    try:
        created = manager.create_overlay("timer", "Raid timers")
        overlay = manager.overlays[created]
        overlay.begin_edit()
        overlay.deleteRequested.emit(created)
        assert created not in manager.overlays
        assert created not in manager.definitions()
    finally:
        manager.close()
        config.data = previous


def test_last_overlay_can_be_deleted_and_routes_are_cleared(monkeypatch):
    _app()
    previous = config.data
    only = {
        "alerts": config.notification_overlay_defaults("alerts", "text")}
    trigger = ["Only route", "Start", "00:00:00", "", "", "", "", "",
               "", "", "alerts", "", "", "", "", "auto"]
    config.data = {
        "general": {"notification_overlays": only},
        "spells": {"custom_timers": [trigger]},
        "combat": {
            "live_overlay_id": "alerts",
            "secondary_overlay_id": "alerts",
            "tanking_overlay_id": "alerts",
        },
    }
    monkeypatch.setattr(config, "save", lambda: None)
    manager = NotificationOverlayManager()
    try:
        assert manager.delete_overlay("alerts") is True
        assert manager.overlays == {}
        assert manager.definitions() == {}
        assert trigger[10] == ""
        assert config.data["combat"] == {
            "live_overlay_id": "",
            "secondary_overlay_id": "",
            "tanking_overlay_id": "",
        }
        config.verify_settings()
        assert config.data["general"]["notification_overlays"] == {}
        manager.notify("Silent", "No surface exists")
        assert manager.overlays == {}
        manager.reload()
        assert manager.overlays == {}
    finally:
        manager.close()
        config.data = previous
