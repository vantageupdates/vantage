import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QLineEdit, QTableWidget, QWidget)
from vantage.helpers.application import VantageApp
import vantage.parsers.combat as combat_module

output = Path(os.environ['VANTAGE_TEST_OUTPUT'])
output.mkdir(parents=True, exist_ok=True)
app = VantageApp([])
combat = app._parsers_dict['combat']
combat.show()
combat.tabs.setCurrentIndex(combat.TABS.index('Chat'))
combat._active_character = 'Mindflux'
combat._active_server = 'Green'

now = datetime.datetime.now()
events = (
    (now - datetime.timedelta(hours=2), "Oldtimer tells the guild, 'Old guild line'"),
    (now - datetime.timedelta(minutes=10), "Trader auctions, 'WTS FBSS 12k'"),
    (now - datetime.timedelta(minutes=9), "Bob tells you, 'Guide https://example.com/raid'"),
    (now - datetime.timedelta(minutes=8), "Cara tells General:1, 'Port available'"),
    (now - datetime.timedelta(minutes=7), "Raider tells the raid, 'Assist now'"),
    (now - datetime.timedelta(minutes=6), "You told Alice, 'Camp is clear'"),
)
for stamp, line in events:
    combat.parse(stamp, line)
combat._activity_signature = None
combat._refresh_activity()
app.processEvents()

all_rows = combat.tables['Chat'].rowCount()
channel_labels = [
    combat.chat_channels.item(row, 1).text()
    for row in range(combat.chat_channels.rowCount())]

def select_channel(key):
    combat.chat_channels.clearSelection()
    for row in range(combat.chat_channels.rowCount()):
        item = combat.chat_channels.item(row, 1)
        if item.data(combat_module.Qt.ItemDataRole.UserRole) == key:
            combat.chat_channels.selectRow(row)
            break
    combat._refresh_chat_view()

select_channel('Guild')
guild_rows = combat.tables['Chat'].rowCount()
select_channel('*')
combat.chat_search.setText('FBSS')
search_rows = combat.tables['Chat'].rowCount()
combat.chat_search.clear()
combat.chat_time.setCurrentIndex(combat.chat_time.findData(15 * 60))
recent_rows = combat.tables['Chat'].rowCount()

combat.chat_search.setText('https://')
combat._copy_chat_link()
copied_link = app.clipboard().text()
combat.chat_search.clear()

combat._clear_chat_view()
cleared_rows = combat.tables['Chat'].rowCount()
history_after_clear = len(combat._tracker.chat)
combat.parse(
    now + datetime.timedelta(seconds=1),
    "Newcomer tells the group, 'New after clear'")
combat._activity_signature = None
combat._refresh_activity()
new_rows = combat.tables['Chat'].rowCount()

combat.chat_time.setCurrentIndex(combat.chat_time.findData('all'))
select_channel('*')
combat.tables['Chat'].clearSelection()
combat._copy_chat_rows()
copied_all = app.clipboard().text()
save_path = output / 'chat-results.txt'
combat_module.QFileDialog.getSaveFileName = staticmethod(
    lambda *args, **kwargs: (str(save_path), 'Text file (*.txt)'))
combat._save_chat_results()

host = combat.tabs.widget(combat.TABS.index('Chat'))
missing_tooltips = []
for widget in host.findChildren(QWidget):
    if (isinstance(widget, (QAbstractButton, QComboBox, QLineEdit, QTableWidget))
            and widget.isVisibleTo(combat) and not widget.toolTip().strip()):
        missing_tooltips.append(
            widget.accessibleName() or widget.objectName() or type(widget).__name__)
headers = []
for table in (combat.chat_channels, combat.tables['Chat']):
    headers.append(all(
        table.horizontalHeaderItem(column).toolTip().strip()
        for column in range(table.columnCount())))

print(json.dumps({
    'all_rows': all_rows,
    'channel_labels': channel_labels,
    'guild_rows': guild_rows,
    'search_rows': search_rows,
    'recent_rows': recent_rows,
    'copied_link': copied_link,
    'cleared_rows': cleared_rows,
    'history_after_clear': history_after_clear,
    'new_rows': new_rows,
    'copy_has_new': 'New after clear' in copied_all,
    'copy_has_old': 'Old guild line' in copied_all,
    'saved_lines': len(save_path.read_text(encoding='utf-8-sig').splitlines()),
    'profiles': combat.chat_profile.count(),
    'archived': combat._chat_archive_total,
    'missing_tooltips': missing_tooltips,
    'header_tooltips': headers,
}))
combat.close()
app.quit()
"""


def test_chat_channel_browser_filters_clear_copy_save_and_tooltips(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['VANTAGE_TEST_OUTPUT'] = str(tmp_path / 'exports')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['all_rows'] == 6
    assert result['channel_labels'] == [
        'All chat', 'All tells', 'Guild', 'Raid', 'Tell · Alice',
        'Tell · Bob', 'Auction', 'General:1']
    assert result['guild_rows'] == 1
    assert result['search_rows'] == 1
    assert result['recent_rows'] == 5
    assert result['copied_link'] == 'https://example.com/raid'
    assert result['cleared_rows'] == 0
    assert result['history_after_clear'] == 6
    assert result['new_rows'] == 1
    assert result['copy_has_new'] is True
    assert result['copy_has_old'] is True
    assert result['saved_lines'] == 8
    assert result['profiles'] == 2
    assert result['archived'] == 7
    assert result['missing_tooltips'] == []
    assert result['header_tooltips'] == [True, True]
