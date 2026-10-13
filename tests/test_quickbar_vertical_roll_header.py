"""The vertical launcher rolls into a real-size logo, not a magnified block."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
import os
from native_audit_fixture import isolate
isolate()
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.quickbar import QuickBar

# Screen fitting has independent coverage. These exact rectangles are a
# presentation contract and must not depend on the synthetic screen height.
QuickBar._fit_to_available_screen = lambda self: None
config.data['general']['startup_window_state'] = 'normal'
config.data['quickbar'].update(
    orientation='vertical', geometry=[55, 70, 30, 310],
    show_header=True, show_notification_ticker=True)
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar._auto_hide_menu = False
bar._set_header_revealed(True)
QTest.qWait(30)

def geometry():
    return [bar.x(), bar.y(), bar.width(), bar.height()]

def state():
    pixmap = bar._title_icon.pixmap()
    icon_size = pixmap.deviceIndependentSize()
    return {
        'rect': geometry(),
        'orientation': bar._orientation,
        'scale': bar._scale_view.transform().m11(),
        'logical_width': bar._logical_surface_width,
        'body_hidden': bar.action_frame.isHidden(),
        'logo_hidden': bar._title_icon.isHidden(),
        'logo_art': [icon_size.width(), icon_size.height()],
        'logo_inside': bar._menu.rect().contains(bar._title_icon.geometry()),
        'logo_inset': (bar._title_icon.geometry().top() >= 2 and
                       bar._title_icon.geometry().bottom() <= bar._menu.height() - 3),
        'surface_matches_width': bar._surface.width() == bar.width(),
        'saved': list(config.data['quickbar']['geometry']),
        'action_sizes': [[b.width(), b.height()] for b in bar._buttons.values()],
    }

initial = state()
cycles = []
for _ in range(3):
    bar._set_collapsed(True)
    QTest.qWait(20)
    rolled = state()
    bar._set_collapsed(True)
    QTest.qWait(20)
    same_rolled = state()
    bar._set_collapsed(False)
    QTest.qWait(20)
    expanded = state()
    bar._set_collapsed(False)
    QTest.qWait(20)
    same_expanded = state()
    cycles.append([rolled, same_rolled, expanded, same_expanded])

# Orientation changes after a rolled column must still build the compact
# column from its actions, not reuse the old horizontal design width.
bar.toggle_orientation()
QTest.qWait(20)
horizontal = bar._orientation == 'horizontal'
bar._set_replica_scale(.5)
QTest.qWait(20)
horizontal_factor = bar._header_metric_factor
# Preserve the real double-click debounce: this is a second deliberate
# orientation change, not a rapid second release of the same gesture.
QTest.qWait(max(250, QApplication.doubleClickInterval()) + 30)
bar.toggle_orientation()
QTest.qWait(20)
vertical_again = state()
bar._set_collapsed(True)
QTest.qWait(20)
rolled_after_orientation = state()

print(json.dumps({
    'initial': initial, 'cycles': cycles, 'horizontal': horizontal,
    'horizontal_factor': horizontal_factor,
    'vertical_again': vertical_again,
    'rolled_after_orientation': rolled_after_orientation,
}))
app.quit()
'''


@pytest.mark.parametrize('dpi_scale', ['1', '1.5', '2'])
def test_vertical_roll_is_one_to_one_and_expansion_keeps_exact_rectangle(
        tmp_path, dpi_scale):
    env = os.environ.copy()
    env.update({
        'QT_QPA_PLATFORM': 'offscreen', 'QT_ACCESSIBILITY': '0',
        'QT_SCALE_FACTOR': dpi_scale,
        'PYTHONPATH': os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src'))),
        'VANTAGE_DATA_DIR': str(tmp_path / 'profile'),
    })
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    initial = result['initial']
    assert initial['rect'] == [55, 70, 30, 310]
    assert initial['orientation'] == 'vertical'
    assert initial['scale'] == 1
    assert initial['body_hidden'] is False
    assert all(size == [24, 24] for size in initial['action_sizes'])
    for rolled, same_rolled, expanded, same_expanded in result['cycles']:
        assert same_rolled == rolled
        assert same_expanded == expanded
        assert rolled['rect'][:3] == initial['rect'][:3]
        assert 18 <= rolled['rect'][3] <= 32
        assert rolled['logical_width'] == rolled['rect'][2] == 30
        assert rolled['scale'] == 1
        assert rolled['surface_matches_width'] is True
        assert rolled['body_hidden'] is True
        assert rolled['logo_hidden'] is False
        assert rolled['logo_inside'] is True
        assert rolled['logo_inset'] is True
        assert rolled['logo_art'] == initial['logo_art']
        assert rolled['saved'] == initial['saved']
        assert expanded['rect'] == initial['rect']
        assert expanded['orientation'] == 'vertical'
        assert expanded['scale'] == 1
        assert expanded['body_hidden'] is False
        assert expanded['action_sizes'] == initial['action_sizes']
        assert expanded['saved'] == initial['saved']
    assert result['horizontal'] is True
    assert result['horizontal_factor'] >= 1.9
    assert result['vertical_again']['orientation'] == 'vertical'
    assert result['vertical_again']['rect'][2] == 30
    assert result['rolled_after_orientation']['rect'][2] == 30
    assert result['rolled_after_orientation']['logical_width'] == 30
    assert result['rolled_after_orientation']['scale'] == 1


HORIZONTAL_SCRIPT = r'''
import json
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar._auto_hide_menu = False

def physical_rect(widget):
    logical = widget.mapTo(bar._surface, widget.rect().topLeft())
    scale = bar._scale_view.transform().m11()
    return QRectF(logical.x() * scale, logical.y() * scale,
                  widget.width() * scale, widget.height() * scale)

def inside(widget):
    return QRectF(bar.rect()).contains(physical_rect(widget))

cases = []
for scale in (.25, .35, .5, .75, 1):
    bar._set_replica_scale(scale)
    bar._set_header_revealed(True)
    QTest.qWait(40)
    factor = bar._scale_view.transform().m11()
    controls = [bar._button, bar._title_icon, bar._title,
                bar._header_overflow_button, bar._settings_button,
                bar._roll_button, bar._minimize_button]
    visible_controls = [w for w in controls if not w.isHidden()]
    action_rect = physical_rect(bar.action_frame)
    rail_rect = physical_rect(bar.notification_rail)
    artwork = bar._title_icon.pixmap().deviceIndependentSize()
    volume_accessible = (
        bar.master_mute_button.isVisibleTo(bar._surface) or
        (bar.volume_rocker in bar._header_overflowed and
         bar._overflow_master_mute_button is not None and
         bar._overflow_volume_slider is not None))
    expanded = [bar.x(), bar.y(), bar.width(), bar.height()]
    case = {
        'header_height': physical_rect(bar._menu).height(),
        'root_inside': all(inside(w) for w in visible_controls),
        'actions_inside': inside(bar.action_frame),
        'rail_inside': inside(bar.notification_rail),
        'lanes_separate': action_rect.bottom() <= rail_rect.top() + 1,
        'actions_below_header': (
            action_rect.top() + .5 >= physical_rect(bar._menu).bottom()),
        'logo_physical': artwork.width() * factor,
        'volume_accessible': volume_accessible,
        'window_height': bar.height(),
    }
    bar._set_collapsed(True)
    QTest.qWait(30)
    rolled = [bar.x(), bar.y(), bar.width(), bar.height()]
    case.update({
        'roll_same_width': rolled[:3] == expanded[:3],
        'roll_same_scale': bar._scale_view.transform().m11() == factor,
        'roll_header_height': physical_rect(bar._menu).height(),
        'rolled_volume': (
            bar.master_mute_button.isVisibleTo(bar._surface) or
            (bar.volume_rocker in bar._header_overflowed and
             bar._overflow_master_mute_button is not None and
             bar._overflow_volume_slider is not None)),
    })
    bar._set_collapsed(True)
    QTest.qWait(10)
    case['roll_idempotent'] = [bar.x(), bar.y(), bar.width(), bar.height()] == rolled
    bar._set_collapsed(False)
    QTest.qWait(30)
    case['expand_exact'] = [bar.x(), bar.y(), bar.width(), bar.height()] == expanded
    cases.append(case)

# Resizing/repacking while the native More menu is open must not destroy the
# editor under a user's pointer or keyboard focus.
bar._set_replica_scale(.25)
QTest.qWait(40)
menu = bar._header_overflow_menu
menu.popup(bar._header_overflow_button.mapToGlobal(
    bar._header_overflow_button.rect().bottomLeft()))
QTest.qWait(30)
mute = bar._overflow_master_mute_button
slider = bar._overflow_volume_slider
bar._rebuild_header_overflow_menu()
bar._pack_header_controls()
QTest.qWait(20)
popup_editors_retained = (
    menu.isVisible() and mute is bar._overflow_master_mute_button and
    slider is bar._overflow_volume_slider)
menu.hide()
print(json.dumps({'cases': cases, 'popup_editors_retained': popup_editors_retained}))
app.quit()
'''


def test_tiny_horizontal_quickbar_keeps_full_header_and_scaled_command_lanes(tmp_path):
    env = os.environ.copy()
    env.update({
        'QT_QPA_PLATFORM': 'offscreen', 'QT_ACCESSIBILITY': '0',
        'PYTHONPATH': os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src'))),
        'VANTAGE_DATA_DIR': str(tmp_path / 'profile'),
    })
    completed = subprocess.run(
        [sys.executable, '-c', HORIZONTAL_SCRIPT], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    for case in result['cases']:
        assert 29 <= case['header_height'] <= 33
        assert case['root_inside'] is True
        assert case['actions_inside'] is True
        assert case['rail_inside'] is True
        assert case['lanes_separate'] is True
        assert case['actions_below_header'] is True
        assert abs(case['logo_physical'] - 18) <= 1
        assert case['volume_accessible'] is True
        assert case['roll_same_width'] is True
        assert case['roll_same_scale'] is True
        assert 29 <= case['roll_header_height'] <= 33
        assert case['rolled_volume'] is True
        assert case['roll_idempotent'] is True
        assert case['expand_exact'] is True
    assert result['popup_editors_retained'] is True
