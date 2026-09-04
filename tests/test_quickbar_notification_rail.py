import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
config.data['general']['reduce_motion'] = False
config.data['quickbar']['orientation'] = 'horizontal'
config.data['quickbar']['show_notification_ticker'] = True
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar.show()
app.processEvents()
rail = bar.notification_rail
rail._clear()
announcements = []
rail._announce_accessibly = announcements.append

empty = {
    'visible': rail.isVisible(),
    'text_visible': rail._label.isVisible(),
    'width': rail.width(),
    'bar_width': bar._design_size.width(),
}

app.show_overlay_notification(
    'Vantage · Spells', 'Clarity faded', msecs=1000)
app.audio_started(
    'Clarity faded', 'builtin:crystal-ping', 82, channel='spells')
app.processEvents()
sound = {
    'text': rail._label.text(),
    'scrolling': rail._scroll_timer.isActive(),
    'notice_id': rail._notice_id,
    'accessible': rail.accessibleName(),
    'announcements': list(announcements),
}

# New events wait their turn instead of replacing the current marquee.
app._queue_quickbar_notice('Fetter resisted')
app._queue_quickbar_notice('Manastone for sale · Trader')
app.processEvents()
queued = {
    'current': rail._label.text(),
    'pending': list(rail._pending),
}

# The same or older event ID is a refresh, not a new live announcement.
rail.present(rail._notice_id, 'Spells · Duplicate must not announce')
duplicate_announcement_count = len(announcements)

seen_after_first = ''
for _ in range(2000):
    rail._advance()
    if rail._label.text() != 'Clarity faded':
        seen_after_first = rail._label.text()
        break
for _ in range(4000):
    if not rail._label.isVisible():
        break
    rail._advance()
cleared = {
    'text': rail._label.text(),
    'visible': rail._label.isVisible(),
    'scrolling': rail._scroll_timer.isActive(),
}

# An unrelated Quick Bar refresh must not replay the consumed notification.
bar.refresh_state()
app.processEvents()
not_replayed = rail._label.isVisible()

config.data['general']['reduce_motion'] = True
app.show_overlay_notification(
    'For sale · Manastone',
    'Manastone for sale · Trader · WTS Manastone 55k', msecs=1000)
app.audio_started(
    'For sale · Manastone', 'builtin:crystal-ping', 72, channel='market')
app.processEvents()
reduced = {
    'text': rail._label.text(),
    'scrolling': rail._scroll_timer.isActive(),
    'clear_pending': rail._clear_timer.isActive(),
}

rail._clear()
bar.hide()
app._queue_quickbar_notice('Must not replay')
app.processEvents()
hidden_consumed = {
    'text_visible': rail._label.isVisible(),
    'scrolling': rail._scroll_timer.isActive(),
    'clear_pending': rail._clear_timer.isActive(),
    'announcement_count': len(announcements),
}
bar.show()
app.processEvents()
hidden_replayed = rail._label.isVisible()

config.data['quickbar']['orientation'] = 'vertical'
app._signals['settings'].config_updated.emit()
app.processEvents()
vertical = {
    'rail_visible': rail.isVisible(),
    'design_width': bar._design_size.width(),
}

print(json.dumps({
    'empty': empty,
    'sound': sound,
    'queued': queued,
    'seen_after_first': seen_after_first,
    'cleared': cleared,
    'not_replayed': not_replayed,
    'reduced': reduced,
    'hidden_consumed': hidden_consumed,
    'hidden_replayed': hidden_replayed,
    'vertical': vertical,
    'duplicate_announcement_count': duplicate_announcement_count,
}))
app.quit()
"""


def test_quickbar_notification_rail_shows_one_event_then_clears(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['empty']['visible'] is True
    assert result['empty']['text_visible'] is False
    assert result['empty']['width'] < result['empty']['bar_width']
    assert result['empty']['width'] >= result['empty']['bar_width'] - 26

    assert result['sound']['text'] == 'Clarity faded'
    assert 'Soft Notify' not in result['sound']['text']
    assert 'SOUND' not in result['sound']['text']
    assert result['sound']['scrolling'] is True
    assert result['sound']['notice_id'] > 0
    assert result['sound']['text'] in result['sound']['accessible']
    assert result['sound']['announcements'] == ['Clarity faded']
    assert result['duplicate_announcement_count'] == 1
    assert result['queued'] == {
        'current': 'Clarity faded',
        'pending': ['Fetter resisted', 'Manastone for sale · Trader'],
    }
    assert result['seen_after_first'] == 'Fetter resisted'

    assert result['cleared'] == {
        'text': '', 'visible': False, 'scrolling': False}
    assert result['not_replayed'] is False
    assert result['reduced'] == {
        'text': 'Manastone for sale · Trader',
        'scrolling': False,
        'clear_pending': True,
    }
    assert result['hidden_consumed'] == {
        'text_visible': False,
        'scrolling': False,
        'clear_pending': False,
        # All four visible notices announced; the hidden notice did not.
        'announcement_count': 4,
    }
    assert result['hidden_replayed'] is False
    assert result['vertical'] == {
        'rail_visible': False,
        'design_width': 30,
    }
