import copy
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from vantage.helpers import config
from vantage.helpers.device_sync import (
    apply_sync_settings, export_sync_settings)
from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.parsers.timers import TimerWatchDialog


ROOT = Path(__file__).resolve().parents[1]


def _app():
    if "timers" not in config.data:
        config.verify_settings()
    return QApplication.instance() or QApplication([])


def _item_for(dialog, timer_id):
    return next(
        dialog.timer_list.item(row)
        for row in range(dialog.timer_list.count())
        if dialog.timer_list.item(row).data(
            Qt.ItemDataRole.UserRole) == timer_id)


def test_watch_dialog_filters_all_zones_and_applies_keyboard_checks():
    app = _app()
    timers = [
        SpawnTimerState(
            "Crystal Fang", 1_970, zone="Velketor's Labyrinth",
            timer_id="velks"),
        SpawnTimerState(
            "Arena cycle", 1_800, zone="Kael Drakkel",
            timer_id="kael"),
        SpawnTimerState(
            "Potion cooldown", 300, timer_id="unassigned",
            timer_mode="cooldown"),
    ]
    dialog = TimerWatchDialog(
        timers, "Velketor's Labyrinth", ["kael", "stale"])
    dialog.show()
    app.processEvents()

    assert dialog.search.hasFocus()
    assert dialog.search.accessibleName() == "Search all saved timers"
    assert "Space" in dialog.timer_list.accessibleDescription()
    local = _item_for(dialog, "velks")
    assert local.checkState() == Qt.CheckState.Checked
    assert bool(local.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert bool(local.flags() & Qt.ItemFlag.ItemIsSelectable)
    assert not bool(local.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert "Included by selected zone" in local.text()
    external = _item_for(dialog, "kael")
    assert external.checkState() == Qt.CheckState.Checked
    assert bool(external.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert "origin zone Kael Drakkel" in external.data(
        Qt.ItemDataRole.AccessibleDescriptionRole)

    dialog.timer_list.setCurrentItem(external)
    dialog.timer_list.setFocus()
    QTest.keyClick(dialog.timer_list, Qt.Key.Key_Down)
    app.processEvents()
    assert dialog.timer_list.currentItem() is local
    QTest.keyClick(dialog.timer_list, Qt.Key.Key_Space)
    app.processEvents()
    assert local.checkState() == Qt.CheckState.Checked
    assert dialog.selected_timer_ids() == ["kael"]

    dialog.search.setText("kael")
    app.processEvents()
    assert dialog.timer_list.count() == 1
    external = dialog.timer_list.item(0)
    dialog.timer_list.setCurrentItem(external)
    dialog.timer_list.setFocus()
    QTest.keyClick(dialog.timer_list, Qt.Key.Key_Space)
    app.processEvents()
    assert external.checkState() == Qt.CheckState.Unchecked

    dialog.search.clear()
    app.processEvents()
    unassigned = _item_for(dialog, "unassigned")
    dialog.timer_list.setCurrentItem(unassigned)
    dialog.timer_list.setFocus()
    QTest.keyClick(dialog.timer_list, Qt.Key.Key_Space)
    app.processEvents()
    assert dialog.selected_timer_ids() == ["unassigned"]
    assert "1 timer explicitly watched" in dialog.status.text()

    button_box = dialog.scaled_surface.findChild(QDialogButtonBox)
    assert button_box is not None
    surface_rect = dialog.scaled_surface.rect()
    for widget in (
            dialog.search, dialog.timer_list, dialog.status, button_box):
        assert surface_rect.contains(widget.geometry())
    assert dialog.search.geometry().bottom() < dialog.timer_list.geometry().top()
    assert dialog.timer_list.geometry().bottom() < dialog.status.geometry().top()
    assert dialog.status.geometry().bottom() < button_box.geometry().top()
    dialog.close()


CREATE_SCRIPT = r"""
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
primary = app._parsers_dict['timers']
timers = (
    SpawnTimerState('Velks timer', 100, zone="Velketor's Labyrinth",
                    timer_id='velks'),
    SpawnTimerState('Kael timer', 100, zone='Kael Drakkel',
                    timer_id='kael'),
    SpawnTimerState('General timer', 100, timer_id='general',
                    timer_mode='countdown'),
)
for timer in timers:
    primary._register_timer(timer)
primary._refresh_zone_filter("Velketor's Labyrinth")
primary._view_settings()['watch_timer_ids'] = ['kael', 'stale']
primary._apply_zone_filter()

secondary = primary.create_secondary_window()
secondary._refresh_zone_filter('Kael Drakkel')
secondary._view_settings()['watch_timer_ids'] = ['general']
secondary._apply_zone_filter()
secondary._view_settings()['toggled'] = True
primary.state_changed(layout_changed=True)
config.save()

visible = lambda view: [
    timer.name for timer_id, timer in view._states.items()
    if not view._rows[timer_id].isHidden()]
print(json.dumps({
    'primary_visible': visible(primary),
    'secondary_visible': visible(secondary),
    'primary_watches': primary._view_settings()['watch_timer_ids'],
    'secondary_watches': secondary._view_settings()['watch_timer_ids'],
    'secondary_id': secondary.instance_id,
    'watch_name': primary.watch_button.accessibleName(),
    'watch_description': primary.watch_button.accessibleDescription(),
}))
app.quit()
"""


RESTORE_SCRIPT = r"""
import json

from vantage.helpers.application import VantageApp
from vantage.helpers.timer_share import decode_timer_share_code
import vantage.parsers.timers as timers_module

captured = []
timers_module.set_eq_clipboard = lambda text: captured.append(text) or True
app = VantageApp([])
primary = app._parsers_dict['timers']
secondary = primary.secondary_windows[0]
visible = lambda view: [
    timer.name for timer_id, timer in view._states.items()
    if not view._rows[timer_id].isHidden()]

before = {
    'primary_visible': visible(primary),
    'secondary_visible': visible(secondary),
    'primary_watches': list(primary._view_settings()['watch_timer_ids']),
    'secondary_watches': list(secondary._view_settings()['watch_timer_ids']),
    'mobile': [row['name'] for row in primary.mobile_snapshot()['timers']],
    'primary_watched_label': primary._rows['kael'].name_label.text(),
    'secondary_watched_label': secondary._rows['general'].name_label.text(),
}
primary.share_visible_timers()
before['shared'] = [
    record.name
    for code in captured[-1].splitlines()
    for record in decode_timer_share_code(code).timers]
primary._refresh_zone_filter('Kael Drakkel')
before['after_zone_change'] = visible(primary)
primary._refresh_zone_filter('')
before['all_saved'] = visible(primary)
primary._refresh_zone_filter("Velketor's Labyrinth")

primary._remove_timer('kael')
primary.state_changed(layout_changed=True)
after = {
    'primary_visible': visible(primary),
    'secondary_visible': visible(secondary),
    'primary_watches': list(primary._view_settings()['watch_timer_ids']),
    'secondary_watches': list(secondary._view_settings()['watch_timer_ids']),
}
print(json.dumps({'before': before, 'after': after}))
app.quit()
"""


def _run(script, profile):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(profile)
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_each_timer_window_restores_independent_cross_zone_watches(tmp_path):
    profile = tmp_path / "profile"
    created = _run(CREATE_SCRIPT, profile)
    assert created["primary_visible"] == ["Velks timer", "Kael timer"]
    assert created["secondary_visible"] == ["Kael timer", "General timer"]
    assert created["primary_watches"] == ["kael"]
    assert created["secondary_watches"] == ["general"]
    assert created["watch_name"] == \
        "Watch timers from other zones in this window"
    assert "every saved timer" in created["watch_description"]

    restored = _run(RESTORE_SCRIPT, profile)
    before = restored["before"]
    assert before["primary_visible"] == ["Velks timer", "Kael timer"]
    assert before["secondary_visible"] == ["Kael timer", "General timer"]
    assert before["primary_watches"] == ["kael"]
    assert before["secondary_watches"] == ["general"]
    assert before["mobile"] == before["primary_visible"]
    assert before["shared"] == before["primary_visible"]
    assert before["primary_watched_label"] == "Kael timer · Kael Drakkel"
    assert before["secondary_watched_label"] == "General timer · Unassigned"
    assert before["after_zone_change"] == ["Kael timer"]
    assert before["all_saved"] == [
        "Velks timer", "Kael timer", "General timer"]

    after = restored["after"]
    assert after["primary_visible"] == ["Velks timer"]
    assert after["secondary_visible"] == ["General timer"]
    assert after["primary_watches"] == []
    assert after["secondary_watches"] == ["general"]


def test_config_bounds_primary_and_secondary_watch_lists():
    original = copy.deepcopy(config.data)
    try:
        config.data.clear()
        config.data.update({
            "timers": {
                "watch_timer_ids": [
                    "same", "same", "", *[
                        f"timer-{index}" for index in range(90)]],
                "instances": [{"id": "abcdef"}],
            },
            "timer_view_abcdef": {
                "watch_timer_ids": ["external", "external", "second"],
            },
        })
        config.verify_settings()

        assert config.data["timers"]["watch_timer_ids"][:2] == [
            "same", "timer-0"]
        assert len(config.data["timers"]["watch_timer_ids"]) == 64
        assert config.data["timer_view_abcdef"]["watch_timer_ids"] == [
            "external", "second"]
    finally:
        config.data.clear()
        config.data.update(original)


def test_device_sync_keeps_per_window_watch_preferences_as_settings():
    source = {
        "timers": {
            "items": [{"timer_id": "kael"}],
            "watch_timer_ids": ["kael"],
        },
        "timer_view_abcdef": {
            "view_zone": "Kael Drakkel",
            "watch_timer_ids": ["general"],
        },
    }

    portable = export_sync_settings(source, include_timers=True)
    current = {"timers": {}, "timer_view_abcdef": {}}
    apply_sync_settings(current, portable, include_timers=True)

    assert current["timers"]["watch_timer_ids"] == ["kael"]
    assert current["timer_view_abcdef"]["watch_timer_ids"] == ["general"]
