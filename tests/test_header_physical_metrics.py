"""Readable physical header controls, native menus, and safe overflow editors."""

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
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDoubleSpinBox, QLabel, QMenu, QSpinBox,
    QToolButton, QWidgetAction)
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from shiboken6 import isValid

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
exceptions = []
sys.excepthook = lambda kind, value, trace: exceptions.append(f'{kind.__name__}: {value}')

def drain(panel):
    app.processEvents()
    QTest.qWait(8)
    panel._pack_header_controls()
    app.processEvents()

def rectangle(panel, widget):
    point = widget.mapTo(panel._surface, widget.rect().topLeft())
    return panel._scale_view.transform().mapRect(QRectF(
        point.x(), point.y(), widget.width(), widget.height()))

panels = {}
for name, panel in app._parsers_dict.items():
    panel._set_collapsed(False)
    panel.resize(panel._design_size)
    panel._set_header_revealed(True)
    panel.show()
    drain(panel)
    body_label = QLabel('A native body font must keep its authored size')
    body_label.setObjectName('HeaderPhysicalBodyProbe')
    panel.content.addWidget(body_label)
    drain(panel)
    body_pixels = body_label.fontInfo().pixelSize()
    combo_popups = {}
    for combo in panel._parser_menu_area.findChildren(QComboBox):
        combo.view().ensurePolished()
        combo_popups[combo] = combo.view().fontInfo().pixelSize()
    cases = []
    for requested in (.25, .35, .5, .75, 1., 1.5):
        if requested <= 1.:
            panel._set_replica_scale(requested)
        else:
            panel.resize(round(panel._design_size.width() * requested),
                         round(panel._design_size.height() * requested))
        panel._set_header_revealed(True)
        drain(panel)
        scale = float(panel._scale_view.transform().m11())
        bounds = QRectF(0, 0, panel.width(), panel.height()).adjusted(-.5, -.5, .5, .5)
        buttons = []
        for button in panel._menu.findChildren(QAbstractButton):
            if not button.isVisibleTo(panel._surface):
                continue
            rect = rectangle(panel, button)
            hit = panel.childAt(rect.center().toPoint())
            buttons.append({
                'name': button.accessibleName() or button.objectName(),
                'width': rect.width(), 'height': rect.height(),
                'inside': bounds.contains(rect),
                'hit': hit.objectName() if hit is not None else None,
                'enabled': button.isEnabled(),
                'font': button.fontInfo().pixelSize() * scale,
                'icon': [button.iconSize().width() * scale,
                         button.iconSize().height() * scale] if not button.icon().isNull() else None,
                'text_action': bool(button.property('HeaderTextAction')),
                'text': button.text(),
                'text_required': (button.fontMetrics().horizontalAdvance(button.text()) * scale +
                                  (button.iconSize().width() * scale + 4
                                   if not button.icon().isNull() and button.text() else 0)),
                'contents_width': button.contentsRect().width() * scale,
            })
        menus = []
        for menu in panel._menu.findChildren(QMenu):
            menu.ensurePolished()
            menus.append(menu.fontInfo().pixelSize())
        cases.append({
            'requested': requested, 'scale': scale,
            'font': panel._title.fontInfo().pixelSize() * scale,
            'height': panel._menu.height() * scale,
            'buttons': buttons,
            'body_pixels': body_label.fontInfo().pixelSize(),
            'body_baseline': body_pixels,
            'menus': menus,
            'combo_popups': [
                {'font': combo.view().fontInfo().pixelSize(), 'baseline': baseline}
                for combo, baseline in combo_popups.items()],
        })
    panels[name] = cases
    body_label.hide()
    panel.hide()

# Synthetic inputs use the actual production overflow builder, with no game
# actions connected. Clones must edit the source and preserve Qt ownership.
panel = app._parsers_dict['boats']
panel._set_replica_scale(1.)
panel._set_header_revealed(True)
panel.show()
combo = QComboBox(panel._parser_menu_area)
combo.setAccessibleName('Synthetic header selector')
combo.addItem('Green', 'green')
combo.addItem('Blue', 'blue')
combo.setEditable(True)
spin = QSpinBox(panel._parser_menu_area)
spin.setAccessibleName('Synthetic header integer')
spin.setRange(1, 60)
spin.setSingleStep(2)
spin.setSuffix('s')
spin.setValue(7)
decimal = QDoubleSpinBox(panel._parser_menu_area)
decimal.setAccessibleName('Synthetic header decimal')
decimal.setDecimals(2)
decimal.setRange(.25, 10.)
decimal.setSingleStep(.25)
decimal.setValue(1.25)
probe_button = QToolButton(panel._parser_menu_area)
probe_button.setAccessibleName('Synthetic native popup')
probe_menu = QMenu(probe_button)
probe_menu.addAction('Native menu action')
probe_button.setMenu(probe_menu)
probe_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
for control in (combo, spin, decimal, probe_button):
    panel.menu_area.addWidget(control)
source_parents = [control.parentWidget() for control in (combo, spin, decimal)]
panel._set_replica_scale(.25)
drain(panel)
probe_menu.ensurePolished()
panel._header_overflow_menu.popup(panel.mapToGlobal(QPoint(10, 30)))
app.processEvents()
QTest.qWait(8)
editors = {}
for action in panel._header_overflow_menu.actions():
    if isinstance(action, QWidgetAction):
        host = action.defaultWidget()
        for kind in (QComboBox, QSpinBox, QDoubleSpinBox):
            for editor in host.findChildren(kind):
                editors[editor.accessibleName()] = editor
clone_combo = editors.get('Synthetic header selector')
clone_spin = editors.get('Synthetic header integer')
clone_decimal = editors.get('Synthetic header decimal')
clones = {'found': [clone_combo is not None, clone_spin is not None, clone_decimal is not None],
          'parents_preserved': all(source.parentWidget() is parent
                                   for source, parent in zip((combo, spin, decimal), source_parents)),
          'native_popup_pixels': probe_menu.fontInfo().pixelSize(),
          'fonts': [editor.fontInfo().pixelSize() for editor in editors.values()]}
if all(clones['found']):
    clones['distinct'] = (clone_combo is not combo and clone_spin is not spin and clone_decimal is not decimal)
    clones['model_shared'] = clone_combo.model() is combo.model()
    clones['spin_settings'] = [clone_spin.minimum(), clone_spin.maximum(), clone_spin.singleStep(), clone_spin.suffix()]
    clones['decimal_settings'] = [clone_decimal.minimum(), clone_decimal.maximum(), clone_decimal.singleStep(), clone_decimal.decimals()]
    combo.currentIndexChanged.connect(lambda _index: panel._pack_header_controls())
    combo.editTextChanged.connect(lambda _text: panel._pack_header_controls())
    spin.valueChanged.connect(lambda _value: panel._pack_header_controls())
    decimal.valueChanged.connect(lambda _value: panel._pack_header_controls())
    clone_combo.setCurrentIndex(1)
    clones['combo_index'] = combo.currentIndex()
    clone_combo.lineEdit().setFocus()
    clone_combo.lineEdit().selectAll()
    QTest.keyClicks(clone_combo.lineEdit(), 'A custom selector entry')
    clones['combo_text'] = combo.currentText()
    clone_spin.setFocus()
    QTest.keyClick(clone_spin, Qt.Key.Key_Up)
    clones['spin_value'] = spin.value()
    clone_decimal.setValue(2.5)
    clones['decimal_value'] = decimal.value()
    app.processEvents()
    clones['menu_survived_edits'] = panel._header_overflow_menu.isVisible()
    clones['editors_survived_edits'] = all(isValid(editor)
                                          for editor in (clone_combo, clone_spin, clone_decimal))
    clones['parents_still_preserved'] = all(source.parentWidget() is parent
                                           for source, parent in zip((combo, spin, decimal), source_parents))
panel._header_overflow_menu.close()
print(json.dumps({'panels': panels, 'clones': clones, 'exceptions': exceptions}))
app.quit()
'''


@pytest.fixture(scope="module", params=("1", "1.5"))
def physical_result(request, tmp_path_factory):
    profile = tmp_path_factory.mktemp(f"header-physical-{request.param}")
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
        f"Disposable physical header app exited {completed.returncode}\n"
        f"STDERR:\n{completed.stderr[-6000:]}\nSTDOUT:\n{completed.stdout[-6000:]}")
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["exceptions"] == []
    assert set(result["panels"]) == WINDOWS
    return result


def test_all_window_headers_keep_readable_physical_fonts_and_height(physical_result):
    for name, cases in physical_result["panels"].items():
        for case in cases:
            context = (name, case["requested"], case["scale"])
            assert case["font"] == pytest.approx(12, abs=.75), context
            expected_height = 30 if name == "quickbar" else 28
            assert case["height"] == pytest.approx(expected_height, abs=1.0), context


def test_visible_header_buttons_have_real_click_targets_not_resize_handles(physical_result):
    for name, cases in physical_result["panels"].items():
        for case in cases:
            for button in case["buttons"]:
                context = (name, case["requested"], button)
                assert button["name"].strip(), context
                assert button["width"] >= 17.5 and button["height"] >= 17.5, context
                assert button["inside"], context
                assert button["hit"] is not None, context
                assert not button["hit"].startswith("ParserWindowResize_"), context
                if button["icon"] is not None:
                    assert button["icon"][0] <= button["width"] + .5, context
                    assert button["icon"][1] <= button["height"] + .5, context
                if button["text_action"]:
                    assert button["contents_width"] >= button["text_required"] - .5, context


def test_scaling_headers_does_not_scale_body_fonts_or_native_popup_fonts(physical_result):
    for name, cases in physical_result["panels"].items():
        for case in cases:
            context = (name, case["requested"])
            assert case["body_pixels"] == case["body_baseline"], context
            assert all(pixels == 12 for pixels in case["menus"]), (context, case["menus"])
            assert all(popup["font"] == popup["baseline"]
                       for popup in case["combo_popups"]), (context, case["combo_popups"])
    assert physical_result["clones"]["native_popup_pixels"] == 12


def test_accessible_overflow_input_clones_edit_sources_without_reparenting(physical_result):
    clones = physical_result["clones"]
    assert clones["found"] == [True, True, True]
    assert clones["distinct"] and clones["model_shared"]
    assert clones["parents_preserved"] and clones["parents_still_preserved"]
    assert clones["menu_survived_edits"] and clones["editors_survived_edits"]
    assert all(pixels == 12 for pixels in clones["fonts"]), clones["fonts"]
    assert clones["spin_settings"] == [1, 60, 2, "s"]
    assert clones["decimal_settings"] == [.25, 10., .25, 2]
    assert clones["combo_index"] == 1
    assert clones["combo_text"] == "A custom selector entry"
    assert clones["spin_value"] == 9
    assert clones["decimal_value"] == 2.5
