"""Shared native Qt chrome stays inset without changing replica geometry."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import json
from PySide6.QtCore import QRect, QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from native_audit_fixture import isolate
isolate()
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.parser import _HeaderTitleLabel

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])

def audit(panel):
    roots = [panel._button, panel._title_icon, panel._title,
             panel._parser_menu_area, panel._header_overflow_button,
             panel._settings_button, panel._roll_button,
             panel._minimize_button]
    visible = [widget for widget in roots
               if widget.isVisibleTo(panel._surface)]
    rectangles = [QRect(widget.mapTo(panel._menu, widget.rect().topLeft()),
                        widget.size()) for widget in visible]
    return {
        'size': [panel.width(), panel.height()],
        'height': panel._menu.height(),
        'font': panel._title.fontInfo().pixelSize(),
        'inset': all(rect.left() >= 4 and
                     rect.right() < panel._menu.width() - 4 and
                     rect.top() >= 2 and
                     rect.bottom() < panel._menu.height() - 2
                     for widget, rect in zip(visible, rectangles)
                     if widget is not panel._title and
                     widget is not panel._title_icon and
                     widget is not panel._parser_menu_area),
        'separate': all(not first.intersects(second)
                        for index, first in enumerate(rectangles)
                        for second in rectangles[index + 1:]),
        'caption_complete': panel._title.text() in
                            panel._title.accessibleName(),
        'painted_caption_fits': panel._title.fontMetrics().horizontalAdvance(
            QLabel.text(panel._title)) <=
            max(0, panel._title.contentsRect().width() - 4),
        'overflow': [action.text()
                     for action in panel._header_overflow_menu.actions()],
    }

result = {}
for name, panel in app._parsers_dict.items():
    panel._set_collapsed(False)
    panel.resize(panel._design_size)
    panel._set_header_revealed(True)
    panel.show()
    QTest.qWait(20)
    panel._pack_header_controls()
    app.processEvents()
    normal = audit(panel)
    panel._set_replica_scale(.5)
    QTest.qWait(20)
    compact = audit(panel)
    panel._set_collapsed(True)
    QTest.qWait(20)
    rolled = audit(panel)
    panel._set_collapsed(False)
    QTest.qWait(20)
    result[name] = {'normal': normal, 'compact': compact, 'rolled': rolled,
                    'restored': [panel.width(), panel.height()],
                    'design': [panel._design_size.width(),
                               panel._design_size.height()]}

# Long captions use an ellipsis, never a silently clipped zone/server name.
label = _HeaderTitleLabel()
label.setObjectName('ParserWindowTitle')
caption = 'Map · A very long zone name with a complete accessible caption'
label.setText(caption)
label.setToolTip('Drag this bar to move the window')
label.resize(90, 28)
label.show()
app.processEvents()
small = QLabel.text(label)
small_help = label.toolTip()
label.resize(700, 28)
app.processEvents()
result['caption'] = {
    'full': label.text(), 'small': small, 'expanded': QLabel.text(label),
    'accessible': label.accessibleName(), 'small_help': small_help,
    'expanded_help': label.toolTip(),
}

# Readouts stay visible even when both tool actions and secondary chrome need
# the shared overflow. Hidden chrome remains callable and preserves state.
heals = app._parsers_dict['heals']
heals._set_collapsed(False)
heals._set_design_size(QSize(300, heals._design_size.height()), False)
heals.resize(300, heals._design_size.height())
heals._set_header_revealed(True)
heals.show()
QTest.qWait(20)
heals._pack_header_controls()
app.processEvents()
result['constrained'] = {
    **audit(heals),
    'countdown': heals.header_countdown.isVisibleTo(heals._surface),
    'interval': heals.interval.isVisibleTo(heals._surface),
    'hidden_chrome': [widget.accessibleName() for widget in (
        heals._button, heals._settings_button, heals._roll_button,
        heals._minimize_button) if widget in heals._header_overflowed],
}
bar = app._parsers_dict['quickbar']
result['mute'] = [bar.master_mute_button.width(),
                  bar.master_mute_button.height()]
config.data['quickbar']['orientation'] = 'vertical'
config.data['quickbar']['show_notification_ticker'] = True
bar._apply_quickbar_settings(preserve_scale=False)
bar.show()
bar.notification_rail.discard_all()
app._queue_quickbar_notice('Synthetic readable notice', channel='spells')
QTest.qWait(20)
bar._pack_header_controls()
app.processEvents()
result['vertical'] = {
    'design_width': bar._design_size.width(),
    'area_hidden': bar._parser_menu_area.isHidden(),
    'widgets': len(bar._header_menu_widgets()),
    'required': bar._header_menu_required_width(
        bar._header_menu_widgets()),
    'overflow': bar._header_overflow_button.isVisibleTo(bar._surface),
    'rail_visible': bar.notification_rail.isVisible(),
}
print(json.dumps(result))
app.quit()
'''


@pytest.mark.parametrize('display_scale', ('1', '1.25', '1.5'))
def test_shared_headers_keep_readable_inset_chrome_and_geometry(
        tmp_path, display_scale):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen',
               QT_SCALE_FACTOR=display_scale,
               PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=os.pathsep.join((str(ROOT / 'tests'),
                                          str(ROOT / 'src'))),
               VANTAGE_DATA_DIR=str(tmp_path / 'profile'))
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    windows = set(result) - {'caption', 'constrained', 'mute', 'vertical'}
    assert len(windows) == 16
    for name in windows:
        panel = result[name]
        assert panel['normal']['size'] == panel['design'], name
        assert panel['restored'] == panel['compact']['size'], name
        for state_name in ('normal', 'compact', 'rolled'):
            state = panel[state_name]
            assert state['separate'], (name, state_name)
            assert state['caption_complete'], (name, state_name)
            assert state['painted_caption_fits'], (name, state_name)
            assert state['font'] >= 12, (name, state_name)
            if name != 'quickbar':
                assert state['height'] == 28, (name, state_name, state)
                assert state['inset'], (name, state_name, state)
    caption = result['caption']
    assert caption['small'].endswith('\u2026')
    assert caption['expanded'] == caption['full']
    assert caption['full'] in caption['accessible']
    assert caption['full'] in caption['small_help']
    assert caption['expanded_help'] == 'Drag this bar to move the window'
    constrained = result['constrained']
    assert constrained['separate'] and constrained['countdown']
    assert constrained['interval'] and constrained['hidden_chrome']
    assert all(label in constrained['overflow']
               for label in constrained['hidden_chrome'])
    assert result['mute'] == [24, 24]
    assert result['vertical'] == {
        'design_width': 30, 'area_hidden': True, 'widgets': 0,
        'required': 0, 'overflow': False, 'rail_visible': True}
