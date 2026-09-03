import json
import math
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import math
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit, QScrollArea, QWidget)
from vantage.helpers.application import VantageApp
from vantage.helpers.overlay_editor import OverlayManagerDialog
from vantage.helpers.spawn_timer import SpawnTimerState


def click_scaled(window, child):
    logical = child.mapTo(window._surface, child.rect().center())
    scene = window._scale_proxy.mapToScene(QPointF(logical))
    viewport = window._scale_view.mapFromScene(scene)
    QTest.mouseClick(
        window._scale_view.viewport(), Qt.MouseButton.LeftButton,
        pos=viewport)


def drag_scaled(window, child):
    logical = child.mapTo(window._surface, child.rect().center())
    scene = window._scale_proxy.mapToScene(QPointF(logical))
    start = window._scale_view.mapFromScene(scene)
    end = start + window._scale_view.mapFromScene(QPointF(28, 18)) \
        - window._scale_view.mapFromScene(QPointF(0, 0))
    QTest.mousePress(
        window._scale_view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window._scale_view.viewport(), end, delay=20)
    QTest.mouseRelease(
        window._scale_view.viewport(), Qt.MouseButton.LeftButton, pos=end)


app = VantageApp([])
market = app._parsers_dict['market']
timers = app._parsers_dict['timers']
maps = app._parsers_dict['maps']
for window in app._parsers_dict.values():
    if window._collapsed:
        window._set_collapsed(False)

anchors = {
    'maps': maps._map,
    'spells': app._parsers_dict['spells']._scroll_area,
    'tick': app._parsers_dict['tick'].progress,
    'timers': timers.status,
    'combat': app._parsers_dict['combat'].tabs,
    'heals': app._parsers_dict['heals'].tabs,
    'market': market.search,
}
QTest.qWait(60)
replicas = {}
header_reveal = {}
for name, anchor in anchors.items():
    panel = app._parsers_dict[name]
    before = [anchor.x(), anchor.y(), anchor.width(), anchor.height()]
    panel.enterEvent(None)
    QTest.qWait(10)
    entered = [anchor.x(), anchor.y(), anchor.width(), anchor.height()]
    panel.leaveEvent(None)
    QTest.qWait(10)
    left = [anchor.x(), anchor.y(), anchor.width(), anchor.height()]
    header_reveal[name] = [before, entered, left]
    panel._set_replica_scale(.35)
    QTest.qWait(20)
    expected_scale = max(
        .35, panel.minimumWidth() / panel._design_size.width())
    replicas[name] = {
        'logical_before': before,
        'logical_after': [
            anchor.x(), anchor.y(), anchor.width(), anchor.height()],
        'window': [panel.width(), panel.height()],
        'expected': [
            round(panel._design_size.width() * expected_scale),
            round(panel._design_size.height() * expected_scale)],
    }

market.resize(490, 310)
market.toggle()
QTest.qWait(80)
market_layout_before = {
    'search': [market.search.x(), market.search.y(),
               market.search.width(), market.search.height()],
    'tabs': [market.tabs.x(), market.tabs.y(),
             market.tabs.width(), market.tabs.height()],
}
click_scaled(market, market.search)
QTest.keyClicks(market._scale_view.viewport(), 'manastone')
search_focus_after_click = market.search.hasFocus()
market.resize(245, 155)
QTest.qWait(80)
market_layout_after = {
    'search': [market.search.x(), market.search.y(),
               market.search.width(), market.search.height()],
    'tabs': [market.tabs.x(), market.tabs.y(),
             market.tabs.width(), market.tabs.height()],
}

timer = SpawnTimerState('Scaled test', 1800, kill_seconds=90)
timers._states[timer.timer_id] = timer
timers._add_row(timer)
row = timers._rows[timer.timer_id]
timers.resize(130, 90)
timers.show()
QTest.qWait(80)
click_scaled(timers, row.play_button)
QTest.qWait(30)
single_timer_size = [timers.width(), timers.height()]
single_timer_surface = [timers._surface.width(), timers._surface.height()]
single_timer_required = timers._required_timer_height
for index in range(6):
    extra = SpawnTimerState(f'No-scroll {index}', 1800, kill_seconds=90)
    timers._states[extra.timer_id] = extra
    timers._add_row(extra)
timers._sync_timer_canvas()
QTest.qWait(60)
timer_design_many = [timers._design_size.width(), timers._design_size.height()]
timer_rows_inside = all(
    timer_row.geometry().bottom() <= timers._timer_host.height()
    for timer_row in timers._rows.values())
last_timer_row = timers._rows[extra.timer_id]
last_timer_row.play_button.setFocus()
app.processEvents()
timer_focus_started_on_suffix = last_timer_row.play_button.hasFocus()

# Reproduce a 150%-scaled attempt to make the timer panel too short. Its
# dynamic resize floor must keep every saved row visible instead of silently
# hiding a suffix of the list.
timers.resize(780, 438)
QTest.qWait(80)
short_rows = [
    timer_row for timer_row in timers._rows.values()
    if not timer_row.isHidden()]
short_row_tops = [
    timer_row.mapTo(timers._surface, timer_row.rect().topLeft()).y()
    for timer_row in short_rows]
timer_short_rows_separate = all(
    next_top > row_top + row.height() - 1
    for row, row_top, next_top in zip(
        short_rows, short_row_tops, short_row_tops[1:]))
timer_short_controls_inside = all(
    row.controls.geometry().bottom() < row.height()
    and all(
        row.controls.rect().contains(
            row.controls.layout().itemAt(index).widget().geometry())
        for index in range(row.controls.layout().count()))
    for row in short_rows)
timer_short_keeps_all_rows = len(short_rows) == len(timers._rows)
timer_resize_was_clamped = timers.height() >= timers.minimumHeight() > 438
timer_required_physical_height = math.ceil(
    timers._required_timer_height *
    (timers.width() / timers._design_size.width()))
timer_screen_height = timers.screen().availableGeometry().height()
short_focus = app.focusWidget()
timer_short_focus_visible = bool(
    short_focus and short_focus.isVisibleTo(timers._surface))

maps.resize(100, 100)
maps.show()
QTest.qWait(60)
drag_scaled(maps, maps._map)
QTest.qWait(30)

interactive = (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit)
missing = [
    type(widget).__name__
    for widget in timers._surface.findChildren(QWidget)
    if isinstance(widget, interactive) and not widget.toolTip()
]
missing_by_panel = {}
for panel_name, panel in app._parsers_dict.items():
    missing_by_panel[panel_name] = [
        type(widget).__name__
        for widget in panel._surface.findChildren(QWidget)
        if isinstance(widget, interactive) and widget.isEnabled()
        and not widget.toolTip()
    ]
overlay_editor = OverlayManagerDialog(app._notification_overlay)
missing_by_panel['overlay_editor'] = [
    type(widget).__name__
    for widget in overlay_editor.findChildren(QWidget)
    if isinstance(widget, interactive) and widget.isEnabled()
    and not widget.toolTip()
]
print(json.dumps({
    'search': market.search.text(),
    'search_focus': search_focus_after_click,
    'market_size': [market.width(), market.height()],
    'market_layout_before': market_layout_before,
    'market_layout_after': market_layout_after,
    'timer_running': timer.running,
    'timer_size': single_timer_size,
    'timer_surface': single_timer_surface,
    'timer_required_single': single_timer_required,
    'timer_design_many': timer_design_many,
    'timer_rows_inside': timer_rows_inside,
    'timer_short_rows_separate': timer_short_rows_separate,
    'timer_short_controls_inside': timer_short_controls_inside,
    'timer_short_keeps_all_rows': timer_short_keeps_all_rows,
    'timer_resize_was_clamped': timer_resize_was_clamped,
    'timer_required_physical_height': timer_required_physical_height,
    'timer_screen_height': timer_screen_height,
    'timer_focus_started_on_suffix': timer_focus_started_on_suffix,
    'timer_short_focus_visible': timer_short_focus_visible,
    'timer_scroll_areas': len(timers._surface.findChildren(QScrollArea)),
    'missing_timer_tooltips': missing,
    'map_manual_pan': maps._map._manual_view,
    'minimum_sizes': {
        name: [panel.minimumWidth(), panel.minimumHeight()]
        for name, panel in app._parsers_dict.items()
    },
    'missing_by_panel': missing_by_panel,
    'replicas': replicas,
    'header_reveal': header_reveal,
}))
overlay_editor.close()
app.quit()
"""


def test_scaled_panels_keep_keyboard_pointer_and_tooltips(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["search"] == "manastone"
    assert result["search_focus"] is True
    assert result["market_layout_after"] == result["market_layout_before"]
    assert result["timer_running"] is True
    assert result["timer_surface"][0] == 520
    assert result["timer_surface"][1] >= result["timer_required_single"]
    assert result["timer_scroll_areas"] == 0
    assert result["timer_design_many"][0] == 520
    assert result["timer_design_many"][1] > 360
    assert result["timer_rows_inside"] is True
    assert result["timer_short_rows_separate"] is True
    assert result["timer_short_controls_inside"] is True
    assert result["timer_short_keeps_all_rows"] is True
    assert result["timer_resize_was_clamped"] is True
    assert result["timer_focus_started_on_suffix"] is True
    assert result["timer_short_focus_visible"] is True
    assert result["timer_size"][0] == 300
    assert result["timer_size"][1] >= math.ceil(
        result["timer_required_single"] * 300 / 520)
    assert result["missing_timer_tooltips"] == []
    assert result["map_manual_pan"] is True
    assert result["minimum_sizes"] == {
        "quickbar": [217, 18],
        "maps": [100, 100], "spells": [210, 111],
        "tick": [88, 48],
        "timers": [300, min(
            result["timer_required_physical_height"],
            result["timer_screen_height"])],
        "combat": [130, 75],
        "heals": [130, 55], "market": [245, 155]}
    assert result["minimum_sizes"]["timers"] == [
        300, min(
            result["timer_required_physical_height"],
            result["timer_screen_height"])]
    assert result["missing_by_panel"] == {
        "quickbar": [], "maps": [], "spells": [], "tick": [],
        "timers": [], "combat": [],
        "heals": [], "market": [], "overlay_editor": []}
    assert all(
        replica['logical_before'][:3] == replica['logical_after'][:3]
        and replica['window'] == replica['expected']
        for replica in result['replicas'].values())
    assert all(
        states[0] == states[1] == states[2]
        for states in result['header_reveal'].values())
