"""Rendered-font and message-lane contracts for the compact Quick Bar."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from vantage.parsers.quickbar import QuickBarNotificationRail

app = QApplication([])
for filename in ('NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(str(Path('data/fonts') / filename))
app.setFont(QFont('Noto Sans'))
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))
rail = QuickBarNotificationRail()
rail.resize(755, 19)
rail.show()
app.processEvents()
announcements = []
rail._announce_accessibly = announcements.append
message = 'Charm warning · Alexandria the Enchanter'
rail.present(1, message, reduce_motion=True, channel='timers')
app.processEvents()

def snapshot():
    viewport = rail._message_viewport
    return {
        'rail_size': [rail.width(), rail.height()],
        'channel_fits': rail._channel.width() >= (
            rail._channel.fontMetrics().horizontalAdvance(
                rail._channel.text()) + 8),
        'text': rail._label.text(),
        'font_px': rail._label.font().pixelSize(),
        'font_height': rail._label.fontMetrics().height(),
        'label_height': rail._label.height(),
        'label_width': rail._label.width(),
        'viewport_width': viewport.width(),
        'lane_after_channel': viewport.x() > rail._channel.geometry().right(),
        'lane_before_history': viewport.geometry().right() < (
            rail.history_button.x()),
        'label_parent_is_viewport': rail._label.parentWidget() is viewport,
        'tooltip_complete': message in rail.toolTip(),
        'accessible_complete': message in rail.accessibleName(),
        'scrolling': rail._scroll_timer.isActive(),
        'expiry_interval': rail._clear_timer.interval(),
    }

wide = snapshot()
rail.resize(240, 19)
app.processEvents()
narrow = snapshot()
rail.resize(755, 19)
app.processEvents()
expanded = snapshot()
rail._clear()
long_message = 'Charm fading on Alexandria the Enchanter · ' * 24
rail.present(2, long_message, channel='spells')
app.processEvents()
marquee = snapshot()
marquee['full_text'] = rail._label.text() == long_message.strip()
marquee['natural_width'] = rail._label.width() >= (
    rail._label.fontMetrics().horizontalAdvance(rail._label.text()))
marquee['starts_at_lane_edge'] = rail._label.x() == (
    rail._message_viewport.width())
for _ in range(4):
    rail._advance()
marquee['moves_by_eight'] = rail._label.x() == (
    rail._message_viewport.width() - 8)
print(json.dumps({
    'wide': wide, 'narrow': narrow, 'expanded': expanded,
    'marquee': marquee, 'announcement_count': len(announcements)}))
rail.close()
"""


def test_quickbar_rail_keeps_readable_fonts_and_bounded_message_lanes(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    for name in ('wide', 'narrow', 'expanded', 'marquee'):
        sample = result[name]
        assert sample['rail_size'][1] == 19
        assert sample['font_px'] == 12
        assert sample['font_height'] <= sample['label_height']
        assert sample['channel_fits'] is True
        assert sample['lane_after_channel'] is True
        assert sample['lane_before_history'] is True
        assert sample['label_parent_is_viewport'] is True

    assert result['wide']['text'] == 'Charm warning · Alexandria the Enchanter'
    assert result['narrow']['text'].endswith('…')
    assert result['narrow']['label_width'] == result['narrow']['viewport_width']
    assert result['expanded']['text'] == result['wide']['text']
    for name in ('wide', 'narrow', 'expanded'):
        assert result[name]['tooltip_complete'] is True
        assert result[name]['accessible_complete'] is True
        assert result[name]['scrolling'] is False
        assert result[name]['expiry_interval'] == 5000

    marquee = result['marquee']
    assert marquee['full_text'] is True
    assert marquee['natural_width'] is True
    assert marquee['label_width'] > marquee['viewport_width']
    assert marquee['starts_at_lane_edge'] is True
    assert marquee['moves_by_eight'] is True
    assert marquee['scrolling'] is True
    assert result['announcement_count'] == 2
