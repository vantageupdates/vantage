import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import time
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers import spells as spells_module

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
app._take_quickbar_notices(discard=True)
announcements = []
rail._announce_accessibly = announcements.append

# Inspect the physical top-level pixels, not only QLabel metadata.  The rail
# lives inside ParserWindow's QGraphicsProxyWidget, where a nested graphics
# effect can leave visible Qt objects that paint no pixels on Windows.
empty_image = bar.grab().toImage()

empty = {
    'visible': rail.isVisible(),
    'text_visible': rail._label.isVisible(),
    'width': rail.width(),
    'bar_width': bar._design_size.width(),
}

app.show_overlay_notification(
    'Vantage · Spells', 'Clarity faded', msecs=1000)
app.audio_started(
    'Clarity faded', 'builtin:crystal-ping', 82, channel='spells',
    visual_registered=True)
app.processEvents()
sound_image = bar.grab().toImage()
painted_pixel_count = sum(
    empty_image.pixel(x, y) != sound_image.pixel(x, y)
    for y in range(max(0, sound_image.height() - 18), sound_image.height())
    for x in range(sound_image.width()))
sound = {
    'text': rail._label.text(),
    'scrolling': rail._scroll_timer.isActive(),
    'notice_id': rail._notice_id,
    'accessible': rail.accessibleName(),
    'announcements': list(announcements),
    'painted_pixel_count': painted_pixel_count,
    'graphics_effect': rail.graphicsEffect() is not None,
}

# New events wait their turn instead of replacing the current marquee.
app._queue_quickbar_notice('Fetter resisted')
app._queue_quickbar_notice('Manastone for sale · Trader')
app.processEvents()
queued = {
    'current': rail._label.text(),
    'pending': [notice[1] for notice in rail._pending],
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

# Events accepted before a Quick Bar refresh remain in the application queue;
# restoring the surface drains every event in original order.
rail.discard_all()
detached_bar = app._parsers_dict.pop('quickbar')
app._queue_quickbar_notice('Burst first', channel='chat')
app._queue_quickbar_notice('Burst second', channel='market')
burst_held = [notice[1] for notice in app._quickbar_notice_queue]
app._parsers_dict['quickbar'] = detached_bar
bar.refresh_state()
app.processEvents()
burst = {
    'held': burst_held,
    'current': rail._label.text(),
    'channel': rail._channel.text(),
    'pending': [notice[1] for notice in rail._pending],
}
rail.discard_all()

# A written audio counterpart remains available even after a long hide.
before_stale = len(announcements)
rail.hide()
rail.present(
    rail._notice_id + 1, 'Expired notice', available=True,
    created_at=time.monotonic() - 60)
app._quickbar_notice_id = rail._notice_id
stale_pending_before_show = len(rail._pending)
rail.show()
app.processEvents()
stale = {
    'pending_before_show': stale_pending_before_show,
    'visible': rail._label.isVisible(),
    'announcement_delta': len(announcements) - before_stale,
}
rail._clear()

config.data['general']['reduce_motion'] = True
app.show_overlay_notification(
    'For sale · Manastone',
    'Manastone for sale · Trader · WTS Manastone 55k', msecs=1000)
app.audio_started(
    'For sale · Manastone', 'builtin:crystal-ping', 72, channel='market',
    visual_registered=True)
app.processEvents()
reduced = {
    'text': rail._label.text(),
    'scrolling': rail._scroll_timer.isActive(),
    'clear_pending': rail._clear_timer.isActive(),
}

# Long combat summaries get a bounded dwell and then clear instead of
# occupying the Quick Bar for the duration of an entire marquee pass.  The
# proxy-hosted rail intentionally uses no opacity effect.
rail._clear()
config.data['general']['reduce_motion'] = False
app._queue_quickbar_notice(
    'Combat parse · 12,345 DPS · a deliberately long encounter summary',
    channel='combat')
app.processEvents()
combat_before_fade = {
    'channel': rail._channel.text(),
    'visible': rail._label.isVisible(),
    'expiry_pending': rail._clear_timer.isActive(),
    'effect_present': rail.graphicsEffect() is not None,
}
rail._expire_current()
QTest.qWait(80)
app.processEvents()
combat_after_expiry = {
    'visible': rail._label.isVisible(),
    'scrolling': rail._scroll_timer.isActive(),
}

rail._clear()
# A direct audio path which did not register a visual event is attributed in
# writing by its semantic source, not by an opaque WAV filename.
app.audio_started(
    'Custom trigger · Enraged', 'builtin:crystal-ping', 82,
    channel='spells')
app.processEvents()
direct_audio = {
    'text': rail._label.text(),
    'channel': rail._channel.text(),
    'accessible': rail.accessibleName(),
}
rail._clear()

# Bard summaries use the Spells lane whether the visual is the manual written
# counterpart or the normal overlay registration.
spells = app._parsers_dict['spells']
summary = SimpleNamespace(
    text='6 Total | 5 Hits | 1 Resist', timestamp='')
spells._bard_group.add_summary = lambda _summary: None
original_speak = spells_module.speak_text
spells_module.speak_text = lambda *_args, **_kwargs: True
config.data['spells']['bard_count_audio'] = True
config.data['spells']['bard_count_overlay'] = False
spells._handle_bard_summaries([summary])
app.processEvents()
bard_overlay_off = {
    'text': rail._label.text(),
    'channel': rail._channel.text(),
    'accessible': rail.accessibleName(),
}
rail._clear()
config.data['spells']['bard_count_overlay'] = True
spells._handle_bard_summaries([summary])
app.processEvents()
bard_overlay_on = {
    'text': rail._label.text(),
    'channel': rail._channel.text(),
    'accessible': rail.accessibleName(),
}
spells_module.speak_text = original_speak
rail._clear()
# A temporary rail hide during layout keeps accepted notices in order and
# announces each only when it is actually presented.
before_temporary = len(announcements)
rail.hide()
app._queue_quickbar_notice('Layout-hidden first', channel='spells')
app._queue_quickbar_notice('Layout-hidden second', channel='spells')
temporary_pending = [notice[1] for notice in rail._pending]
rail.show()
app.processEvents()
temporary_visible = {
    'current': rail._label.text(),
    'pending': [notice[1] for notice in rail._pending],
    'new_announcements': announcements[before_temporary:],
}
rail._clear()

# Hiding the Quick Bar does not disable its independently enabled ticker.
# Hold live events and present them when the bar becomes visible again.
bar._toggled = False
config.data['quickbar']['toggled'] = False
bar.hide()
before_hidden = len(announcements)
app._queue_quickbar_notice('Must not replay')
app.processEvents()
hidden_consumed = {
    'text_visible': rail._label.isVisible(),
    'scrolling': rail._scroll_timer.isActive(),
    'clear_pending': rail._clear_timer.isActive(),
    'announcement_delta': len(announcements) - before_hidden,
}
bar._toggled = True
config.data['quickbar']['toggled'] = True
bar.show()
bar.refresh_state()
app.processEvents()
hidden_replayed = rail._label.isVisible()

# Exercise the real ParserWindow toggle ordering.  Reopening must drain the
# application queue during showEvent without a later manual refresh call.
rail.discard_all()
app._take_quickbar_notices(discard=True)
bar.toggle()
app._queue_quickbar_notice('Held longer than thirty seconds', channel='spells')
held = app._quickbar_notice_queue.pop()
app._quickbar_notice_queue.append(
    (held[0], held[1], held[2], time.monotonic() - 60))
bar.toggle()
app.processEvents()
real_reopen = {
    'visible': rail._label.isVisible(),
    'text': rail._label.text(),
    'queued_in_app': len(app._quickbar_notice_queue),
}

# A realistic burst must not disappear at the former 40/20 deque caps.
rail.discard_all()
bar.toggle()
for index in range(75):
    app._queue_quickbar_notice(f'Burst event {index + 1}', channel='timers')
burst_count_hidden = len(app._quickbar_notice_queue)
bar.toggle()
app.processEvents()
large_burst = {
    'held': burst_count_hidden,
    'current': rail._label.text(),
    'pending': len(rail._pending),
    'history': len(app.quickbar_notice_history()),
}
rail.discard_all()

# History is a separate, bounded session record. Opening it from the Quick Bar
# never replays audio, and a live refresh preserves the user's selected row.
app._quickbar_notice_history.clear()
app._queue_quickbar_notice('Manastone for sale · Trader', channel='market')
app._queue_quickbar_notice('Nagafen spawn soon', channel='timers')
app.audio_started(
    'Spawn warning · Nagafen', 'builtin:crystal-ping', 82,
    channel='timers', visual_registered=True)
audio_before_history = app._last_audio_event
bar.notification_rail.history_button.setFocus()
QTest.keyClick(
    bar.notification_rail.history_button, Qt.Key.Key_Space)
app.processEvents()
history_dialog = app._notification_history_dialog
# Native/offscreen top-level activation is asynchronous. Assert actual
# readiness, not a fixed 20ms scheduling assumption, before testing Tab order.
# A launcher that never activates still fails, as do all six traversal checks.
assert QTest.qWaitForWindowActive(history_dialog, 1000)
app.processEvents()
history_dialog.table.selectRow(1)
history_dialog.search.setFocus()
QTest.keyClick(history_dialog.search, Qt.Key.Key_Tab)
tab_search_to_table = QApplication.focusWidget() is history_dialog.table
QTest.keyClick(history_dialog.table, Qt.Key.Key_Tab)
tab_table_to_copy = QApplication.focusWidget() is history_dialog.copy_button
QTest.keyClick(history_dialog.copy_button, Qt.Key.Key_Tab)
tab_copy_to_close = QApplication.focusWidget() is history_dialog.close_button
history_dialog.close_button.setFocus()
QTest.keyClick(history_dialog.close_button, Qt.Key.Key_Backtab)
backtab_close_to_copy = QApplication.focusWidget() is history_dialog.copy_button
QTest.keyClick(history_dialog.copy_button, Qt.Key.Key_Backtab)
backtab_copy_to_table = QApplication.focusWidget() is history_dialog.table
QTest.keyClick(history_dialog.table, Qt.Key.Key_Backtab)
backtab_table_to_search = QApplication.focusWidget() is history_dialog.search
history_dialog.table.selectRow(1)
selected_before = history_dialog.table.item(
    history_dialog.table.currentRow(), 2).text()
app._queue_quickbar_notice('Fetter faded', channel='spells')
app.processEvents()
selected_after = history_dialog.table.item(
    history_dialog.table.currentRow(), 2).text()
history_dialog.search.setText('manastone')
app.processEvents()
history_dialog.table.selectRow(0)
history_status_before_copy = history_dialog.status.text()
history_dialog.copy_button.click()
history = {
    'visible': history_dialog.isVisible(),
    'accessible': history_dialog.accessibleName(),
    'button_accessible': (
        bar.notification_rail.history_button.accessibleName()),
    'filtered_rows': history_dialog.table.rowCount(),
    'message': history_dialog.table.item(0, 2).text(),
    'latest_audio': history_dialog.latest_audio.text(),
    'status': history_status_before_copy,
    'copied': QApplication.clipboard().text(),
    'selection_preserved': selected_before == selected_after,
    'audio_unchanged': app._last_audio_event == audio_before_history,
    'keyboard_flow': [
        tab_search_to_table, tab_table_to_copy, tab_copy_to_close,
        backtab_close_to_copy, backtab_copy_to_table,
        backtab_table_to_search,
    ],
}

# Equal-second bursts retain exact timestamp order, and filtering/eviction
# cannot leave Copy selected pointing at a replacement row.
history_dialog.close()
app._quickbar_notice_history.clear()
same_second = time.time()
display_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(same_second))
for index in range(251):
    app._quickbar_notice_history.append({
        'occurred_at': same_second + index / 1000,
        'display_time': display_time,
        'channel': 'spells',
        'category': 'BUFFS / SPELLS',
        'message': f'Burst history {index}',
    })
history_dialog.search.clear()
history_dialog.show()
history_dialog.refresh()
newest_same_second = history_dialog.table.item(0, 2).text()

def select_history_message(message):
    for row in range(history_dialog.table.rowCount()):
        if history_dialog.table.item(row, 2).text() == message:
            history_dialog.table.selectRow(row)
            return True
    return False

assert select_history_message('Burst history 100')
history_dialog.search.setText('Burst history 250')
app.processEvents()
filter_cleared_selection = (
    history_dialog.table.currentRow() == -1 and
    not history_dialog.copy_button.isEnabled())
history_dialog.search.clear()
app.processEvents()
assert select_history_message('Burst history 1')
app._quickbar_notice_history.append({
    'occurred_at': same_second + 1,
    'display_time': display_time,
    'channel': 'timers',
    'category': 'COMBAT / TIMERS',
    'message': 'Burst history 251',
})
history_dialog.refresh()
eviction_cleared_selection = (
    history_dialog.table.currentRow() == -1 and
    not history_dialog.copy_button.isEnabled())
history_safety = {
    'rows': history_dialog.table.rowCount(),
    'newest_same_second': newest_same_second,
    'filter_cleared_selection': filter_cleared_selection,
    'eviction_cleared_selection': eviction_cleared_selection,
}

config.data['quickbar']['orientation'] = 'vertical'
app._signals['settings'].config_updated.emit()
app.processEvents()
rail.discard_all()
config.data['general']['audio_muted'] = True
app._queue_quickbar_notice('Muted but visible', channel='timers')
app.processEvents()
vertical = {
    'rail_visible': rail.isVisible(),
    'design_width': bar._design_size.width(),
    'text': rail._label.text(),
}
config.data['quickbar']['show_notification_ticker'] = False
app._signals['settings'].config_updated.emit()
app.processEvents()
ticker_off = {
    'rail_visible': rail.isVisible(),
    'text_visible': rail._label.isVisible(),
}

print(json.dumps({
    'empty': empty,
    'sound': sound,
    'queued': queued,
    'seen_after_first': seen_after_first,
    'cleared': cleared,
    'not_replayed': not_replayed,
    'burst': burst,
    'stale': stale,
    'reduced': reduced,
    'combat_before_fade': combat_before_fade,
    'combat_after_expiry': combat_after_expiry,
    'direct_audio': direct_audio,
    'bard_overlay_off': bard_overlay_off,
    'bard_overlay_on': bard_overlay_on,
    'temporary_pending': temporary_pending,
    'temporary_visible': temporary_visible,
    'hidden_consumed': hidden_consumed,
    'hidden_replayed': hidden_replayed,
    'real_reopen': real_reopen,
    'large_burst': large_burst,
    'history': history,
    'history_safety': history_safety,
    'vertical': vertical,
    'ticker_off': ticker_off,
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
    assert result['sound']['announcements'] == [
        'BUFFS / SPELLS: Clarity faded']
    assert result['sound']['painted_pixel_count'] > 100
    assert result['sound']['graphics_effect'] is False
    assert result['duplicate_announcement_count'] == 1
    assert result['queued'] == {
        'current': 'Clarity faded',
        'pending': ['Fetter resisted', 'Manastone for sale · Trader'],
    }
    assert result['seen_after_first'] == 'Fetter resisted'

    assert result['cleared'] == {
        'text': '', 'visible': False, 'scrolling': False}
    assert result['not_replayed'] is False
    assert result['burst'] == {
        'held': ['Burst first', 'Burst second'],
        'current': 'Burst first',
        'channel': 'CHAT',
        'pending': ['Burst second'],
    }
    assert result['stale'] == {
        'pending_before_show': 1,
        'visible': True,
        'announcement_delta': 1,
    }
    assert result['reduced'] == {
        'text': 'Manastone for sale · Trader',
        'scrolling': False,
        'clear_pending': True,
    }
    assert result['combat_before_fade'] == {
        'channel': 'COMBAT',
        'visible': True,
        'expiry_pending': True,
        'effect_present': False,
    }
    assert result['combat_after_expiry'] == {
        'visible': False,
        'scrolling': False,
    }
    assert result['temporary_pending'] == [
        'Layout-hidden first', 'Layout-hidden second']
    assert result['temporary_visible'] == {
        'current': 'Layout-hidden first',
        'pending': ['Layout-hidden second'],
        'new_announcements': [
            'BUFFS / SPELLS: Layout-hidden first'],
    }
    assert result['hidden_consumed'] == {
        # Internal child state remains paused while the top-level Quick Bar
        # is hidden; no duplicate accessibility announcement is emitted.
        'text_visible': True,
        'scrolling': True,
        'clear_pending': False,
        'announcement_delta': 0,
    }
    assert result['direct_audio'] == {
        'text': 'Custom trigger · Enraged',
        'channel': 'BUFFS / SPELLS',
        'accessible': (
            'Latest Vantage notification: BUFFS / SPELLS: '
            'Custom trigger · Enraged'),
    }
    expected_bard = {
        'text': '6 Total | 5 Hits | 1 Resist',
        'channel': 'BUFFS / SPELLS',
        'accessible': (
            'Latest Vantage notification: BUFFS / SPELLS: '
            '6 Total | 5 Hits | 1 Resist'),
    }
    assert result['bard_overlay_off'] == expected_bard
    assert result['bard_overlay_on'] == expected_bard
    assert result['hidden_replayed'] is True
    assert result['real_reopen'] == {
        'visible': True,
        'text': 'Held longer than thirty seconds',
        'queued_in_app': 0,
    }
    assert result['large_burst'] == {
        'held': 75,
        'current': 'Burst event 71',
        'pending': 4,
        # Every exact event remains available even though the transient rail
        # prioritizes the latest part of a burst.
        'history': 90,
    }
    assert result['history']['visible'] is True
    assert result['history']['accessible'] == 'Notification History'
    assert result['history']['button_accessible'] == \
        'Open Notification History'
    assert result['history']['filtered_rows'] == 1
    assert result['history']['message'] == 'Manastone for sale · Trader'
    assert result['history']['latest_audio'].startswith(
        'Latest audio: Spawn warning · Nagafen')
    assert 'last 250' in result['history']['status']
    assert 'Manastone for sale · Trader' in result['history']['copied']
    assert result['history']['selection_preserved'] is True
    assert result['history']['audio_unchanged'] is True
    assert result['history']['keyboard_flow'] == [True] * 6
    assert result['history_safety'] == {
        'rows': 250,
        'newest_same_second': 'Burst history 250',
        'filter_cleared_selection': True,
        'eviction_cleared_selection': True,
    }
    assert result['vertical'] == {
        'rail_visible': True,
        'design_width': 30,
        'text': 'Muted but visible',
    }
    assert result['ticker_off'] == {
        'rail_visible': False,
        'text_visible': False,
    }
