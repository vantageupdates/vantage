"""All-window header state regressions in a disposable native application."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = {
    "quickbar", "maps", "spells", "boats", "vitals", "tick", "timers",
    "combat", "random_parser", "heals", "market", "opendkp", "zones",
    "quests", "items_notes", "log_searcher", "vantage_ui"}

SCRIPT = r'''
import json
import sys
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
exceptions = []
sys.excepthook = lambda kind, value, trace: exceptions.append(f'{kind.__name__}: {value}')

def drain(panel):
    app.processEvents()
    QTest.qWait(8)
    panel._pack_header_controls()
    app.processEvents()

def size(panel):
    return [panel.width(), panel.height()]

def header(panel):
    widgets = [panel._button, panel._title_icon, panel._title,
               panel._parser_menu_area, panel._header_overflow_button,
               panel._settings_button, panel._roll_button,
               panel._minimize_button]
    bounds = QRectF(0, 0, panel.width(), panel.height())
    rectangles = []
    clipped = []
    for widget in widgets:
        if not widget.isVisibleTo(panel._surface):
            continue
        point = widget.mapTo(panel._surface, widget.rect().topLeft())
        rect = panel._scale_view.transform().mapRect(QRectF(
            point.x(), point.y(), widget.width(), widget.height()))
        name = widget.accessibleName() or widget.objectName()
        rectangles.append((name, rect))
        if not bounds.adjusted(-.5, -.5, .5, .5).contains(rect):
            clipped.append([name, rect.x(), rect.y(), rect.width(), rect.height()])
    overlaps = []
    for index, (first_name, first) in enumerate(rectangles):
        for second_name, second in rectangles[index + 1:]:
            intersection = first.intersected(second)
            if intersection.width() > .75 and intersection.height() > .75:
                overlaps.append([first_name, second_name])
    painted = QLabel.text(panel._title)
    return {
        'clipped': clipped, 'overlaps': overlaps,
        'painted_fits': panel._title.fontMetrics().horizontalAdvance(painted)
                        <= max(0, panel._title.contentsRect().width() - 4),
        'caption_accessible': panel._title.text() in panel._title.accessibleName(),
        'title': panel._title.text(),
    }

results = {}
for name, panel in app._parsers_dict.items():
    panel._set_collapsed(False)
    panel.resize(panel._design_size)
    panel._set_header_revealed(True)
    panel.show()
    drain(panel)
    original_title = panel._title.text()
    hidden_probe = QLabel('Intentionally hidden feature content')
    hidden_probe.setObjectName('HeaderRecoveryHiddenContentProbe')
    panel.content.addWidget(hidden_probe)
    hidden_probe.hide()
    cases = []
    for scale in (1., .75, .5, .35, .25):
        panel._set_collapsed(False)
        panel._title.setText(original_title)
        panel._set_replica_scale(scale)
        panel._set_header_revealed(True)
        drain(panel)
        expected = size(panel)
        panel._save_geometry()
        expected_saved = list(config.data[name]['geometry'])
        original_visibility = {
            widget.objectName() or f'body-{index}': widget.isHidden()
            for index in range(1, panel.content.count())
            if (widget := panel.content.itemAt(index).widget()) is not None}
        title_cases = []
        restored_sizes = []
        hidden_content = []
        saved_geometry = []
        for cycle in range(2):
            panel._set_collapsed(True)
            drain(panel)
            rolled_size = size(panel)
            panel._set_collapsed(True)
            drain(panel)
            repeated_rolled_size = size(panel)
            panel._title.setText(
                original_title + ' · Castle Mistmoore · ACTIVE · 12 · '
                'A complete title update with a much longer server and zone')
            drain(panel)
            title_cases.append({
                **header(panel), 'rolled_size': rolled_size,
                'repeated_rolled_size': repeated_rolled_size})
            panel._title.setText(original_title)
            drain(panel)
            panel._set_collapsed(False)
            panel._set_header_revealed(True)
            drain(panel)
            restored_sizes.append(size(panel))
            panel._set_collapsed(False)
            drain(panel)
            restored_sizes.append(size(panel))
            hidden_content.append({
                widget.objectName() or f'body-{index}': widget.isHidden()
                for index in range(1, panel.content.count())
                if (widget := panel.content.itemAt(index).widget()) is not None})
            saved_geometry.append(list(config.data[name]['geometry']))
            panel._minimize_to_tray()
            panel.toggle()
            panel._set_header_revealed(True)
            drain(panel)
            restored_sizes.append(size(panel))
        cases.append({
            'scale': scale, 'expected': expected, 'expected_saved': expected_saved,
            'title_cases': title_cases, 'restored_sizes': restored_sizes,
            'original_visibility': original_visibility,
            'hidden_content': hidden_content, 'saved_geometry': saved_geometry,
        })
    # A restored/synced profile describes the expanded rectangle even while
    # the panel is rolled. Changing it must replace the old saved body size.
    panel._set_collapsed(False)
    panel._set_replica_scale(.5)
    drain(panel)
    incoming_geometry = [panel.x(), panel.y(), panel.width(), panel.height()]
    incoming_expected = size(panel)
    panel._set_replica_scale(.35)
    drain(panel)
    panel._set_collapsed(True)
    drain(panel)
    config.data[name].update(
        geometry=incoming_geometry, collapsed=True, toggled=True)
    panel.apply_saved_presentation()
    drain(panel)
    incoming_rolled = size(panel)
    panel._set_collapsed(False)
    drain(panel)
    cases[-1]['incoming'] = {
        'expected': incoming_expected, 'rolled': incoming_rolled,
        'expanded': size(panel), 'saved': config.data[name]['geometry'][2:]}
    results[name] = cases
    panel.hide()
print(json.dumps({'windows': results, 'exceptions': exceptions}))
app.quit()
'''


@pytest.fixture(scope="module", params=("1", "1.5"))
def recovery_result(request, tmp_path_factory):
    profile = tmp_path_factory.mktemp(f"header-state-{request.param}")
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen", QT_ACCESSIBILITY="0",
        QT_SCALE_FACTOR=request.param, PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src"))),
        VANTAGE_DATA_DIR=str(profile / "profile"))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, (
        f"Disposable header app exited {completed.returncode}\n"
        f"STDERR:\n{completed.stderr[-6000:]}\nSTDOUT:\n{completed.stdout[-6000:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["exceptions"] == []
    assert set(result["windows"]) == WINDOWS
    return result["windows"]


def test_dynamic_rolled_titles_never_cover_or_clip_header_controls(recovery_result):
    for name, cases in recovery_result.items():
        for case in cases:
            for cycle, header in enumerate(case["title_cases"]):
                context = (name, case["scale"], cycle)
                assert header["clipped"] == [], (context, header["clipped"])
                assert header["overlaps"] == [], (context, header["overlaps"])
                assert header["painted_fits"], context
                assert header["caption_accessible"], context


def test_same_state_roll_calls_preserve_expanded_size_and_saved_geometry(recovery_result):
    for name, cases in recovery_result.items():
        for case in cases:
            context = (name, case["scale"])
            assert all(header["rolled_size"][0] == case["expected"][0]
                       for header in case["title_cases"]), context
            assert all(header["rolled_size"] == header["repeated_rolled_size"]
                       for header in case["title_cases"]), context
            assert all(restored == case["expected"]
                       for restored in case["restored_sizes"]), (
                           context, case["expected"], case["restored_sizes"])
            assert all(saved == case["expected_saved"]
                       for saved in case["saved_geometry"]), (
                           context, case["expected_saved"], case["saved_geometry"])


def test_rollup_does_not_reveal_intentionally_hidden_feature_content(recovery_result):
    for name, cases in recovery_result.items():
        for case in cases:
            context = (name, case["scale"])
            assert case["original_visibility"]["HeaderRecoveryHiddenContentProbe"] is True
            assert all(visibility == case["original_visibility"]
                       for visibility in case["hidden_content"]), (
                           context, case["original_visibility"], case["hidden_content"])


def test_incoming_saved_geometry_replaces_the_old_rolled_rectangle(recovery_result):
    for name, cases in recovery_result.items():
        incoming = cases[-1]['incoming']
        assert incoming['rolled'][0] == incoming['expected'][0], (name, incoming)
        assert incoming['expanded'] == incoming['expected'], (name, incoming)
        assert incoming['saved'] == incoming['expected'], (name, incoming)
