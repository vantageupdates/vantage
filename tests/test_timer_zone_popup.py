"""Zone selection must escape the clipped/scaled timer overlay viewport."""

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
from pathlib import Path

from native_audit_fixture import isolate
isolate()

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState

config.data['general']['startup_window_state'] = 'normal'
config.data['timers']['auto_hide_menu'] = False
app = VantageApp([])
primary = app._parsers_dict['timers']
zones = ['East Commonlands', 'Lower Guk', 'Skyfire Mountains',
         'Temple Of Veeshan', 'The Burning Wood']
zones += [f'Zone {index:03d}' for index in range(80)]
for zone in zones:
    timer = SpawnTimerState(zone, 1800, zone=zone)
    primary._states[timer.timer_id] = timer
primary._refresh_zone_filter('East Commonlands')
secondary = primary.create_secondary_window()
results = []

for panel, width, rolled, edge in (
        (primary, 440, False, False),
        (primary, 440, True, False),
        (secondary, 520, False, True)):
    panel._set_collapsed(False)
    panel.resize(width, 185)
    panel._set_header_revealed(True)
    panel.show()
    QTest.qWait(60)
    panel._pack_header_controls()
    if rolled:
        panel._set_collapsed(True)
    screen = panel.screen().availableGeometry()
    panel.move(screen.right() - panel.width() - 4 if edge else screen.left() + 20,
               screen.bottom() - panel.height() - 4 if edge else screen.top() + 20)
    panel._refresh_zone_filter('East Commonlands')
    QTest.qWait(60)
    combo = panel.zone_filter
    assert combo.isVisibleTo(panel._surface)
    panel._scale_scene.setFocusItem(panel._scale_proxy)
    combo.setFocus(Qt.FocusReason.TabFocusReason)
    combo.showPopup()
    QTest.qWait(60)
    popup = combo.view().window()
    bounds = popup.frameGeometry()
    state = {
        'detached': popup.graphicsProxyWidget() is None,
        'native_popup': popup.isWindow() and popup.isVisible(),
        'screen_contains': screen.contains(bounds),
        'outside_panel': not panel.frameGeometry().contains(bounds),
        'window_size': [panel.width(), panel.height()],
        'popup_size': [bounds.width(), bounds.height()],
        'rows': combo.count(),
        'all_zones': set(zones).issubset({combo.itemData(i) for i in range(combo.count())}),
        'scrollable': combo.view().verticalScrollBar().maximum() > 0,
    }
    # The last row was inaccessible in the reported short-window regression.
    QTest.keyClick(combo.view(), Qt.Key.Key_End)
    QTest.keyClick(combo.view(), Qt.Key.Key_Return)
    app.processEvents()
    state['last_selected'] = panel._selected_zone == zones[-1]
    state['saved_zone'] = panel._view_settings()['view_zone'] == zones[-1]
    state['closed_on_commit'] = not popup.isVisible()
    combo.showPopup()
    QTest.qWait(30)
    selected_rect = combo.view().visualRect(combo.view().currentIndex())
    state['reopened_selection_visible'] = combo.view().viewport().rect().contains(selected_rect.center())
    QTest.keyClick(combo.view(), Qt.Key.Key_Home)
    QTest.keyClick(combo.view(), Qt.Key.Key_Escape)
    app.processEvents()
    state['escape_preserves'] = panel._selected_zone == zones[-1] and not popup.isVisible()
    # Click a row that starts outside the original overlay's content viewport.
    combo.showPopup()
    QTest.qWait(30)
    last = combo.model().index(combo.count() - 2, 0)
    combo.view().scrollTo(last)
    app.processEvents()
    rect = combo.view().visualRect(last)
    QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                     pos=rect.center())
    app.processEvents()
    state['mouse_selected'] = panel._selected_zone == zones[-2]
    state['closed_on_click'] = not popup.isVisible()
    capture = os.environ.get('VANTAGE_TIMER_POPUP_CAPTURE_DIR')
    if capture and not edge and not rolled:
        destination = Path(capture)
        destination.mkdir(parents=True, exist_ok=True)
        panel.grab().save(str(destination / 'timers-window.png'))
        combo.showPopup()
        QTest.qWait(30)
        popup.grab().save(str(destination / 'timer-zones-popup.png'))
        combo.hidePopup()
    results.append(state)

print(json.dumps(results))
app.quit()
'''


@pytest.mark.parametrize('dpi_scale', ('1', '1.5'))
def test_timer_zone_popup_escapes_overlay_and_keeps_all_zones_reachable(tmp_path, dpi_scale):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR=dpi_scale,
               VANTAGE_DATA_DIR=str(tmp_path / 'profile'),
               PYTHONPATH=os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src'))))
    completed = subprocess.run([sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
                               check=True, capture_output=True, text=True, timeout=45)
    results = json.loads(completed.stdout.strip().splitlines()[-1])
    for state in results:
        assert state['rows'] >= 86
        for key in ('detached', 'native_popup', 'screen_contains', 'outside_panel',
                    'last_selected', 'saved_zone', 'closed_on_commit',
                    'escape_preserves', 'mouse_selected', 'closed_on_click',
                    'all_zones', 'scrollable', 'reopened_selection_visible'):
            assert state[key], (dpi_scale, key, state)
    assert results[0]['window_size'][0] == 440
    assert results[1]['window_size'][1] <= 28
    assert results[2]['window_size'][0] == 520
