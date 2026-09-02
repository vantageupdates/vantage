import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
    QLineEdit, QTableWidget, QTreeWidget, QWidget)

from vantage.helpers.application import VantageApp
from vantage.helpers.log_monitor import LogMonitorDialog
from vantage.helpers.settings import (
    CustomTriggerSettings, GinaImportPreviewDialog, TriggerMatchLogDialog)
from vantage.parsers.market import WikiEntityCard, WikiItemCard
from vantage.parsers.spells import CustomTrigger


def rect(widget):
    value = widget.geometry()
    return [value.x(), value.y(), value.width(), value.height()]


def scale_down(dialog, anchor):
    dialog.show()
    app.processEvents()
    before = rect(anchor)
    design = dialog._dialog_design_size
    dialog.resize(design.width() // 2, design.height() // 2)
    app.processEvents()
    return {
        'scale': round(dialog.uniform_scale, 3),
        'surface': [dialog.scaled_surface.width(), dialog.scaled_surface.height()],
        'design': [design.width(), design.height()],
        'logical_unchanged': rect(anchor) == before,
    }


def click_scaled(dialog, child):
    logical = child.mapTo(dialog.scaled_surface, child.rect().center())
    scene = dialog._dialog_proxy.mapToScene(QPointF(logical))
    viewport = dialog._dialog_view.mapFromScene(scene)
    QTest.mouseClick(
        dialog._dialog_view.viewport(), Qt.MouseButton.LeftButton,
        pos=viewport)


app = VantageApp([])
class Reader:
    def profiles(self):
        return [{
            'character': 'Mindflux', 'server': 'Green', 'status': 'ACTIVE',
            'last_write': '09:14:32',
            'file': r'C:\EverQuest\Logs\eqlog_Mindflux_green.txt',
            'size': 1245120}]

app._log_reader = Reader()
trigger = CustomTrigger(
    'Invisibility warning', 'You feel yourself starting to appear.',
    '00:00:15', alert_text='Invisibility dropping', timer_type='countdown')
settings = app._settings
library = CustomTriggerSettings()
history = TriggerMatchLogDialog(library)
import_preview = GinaImportPreviewDialog([trigger])
item = WikiItemCard({
    'n': 'Fungus Covered Scale Tunic', 'a30': 900,
    'a60': 925, 'a90': 950})
entity = WikiEntityCard('Myconid Spore King', 'npc')
logs = LogMonitorDialog(app)
mobile = app._mobile_dialog
live = mobile._live_setup

dialogs = {
    'settings': (settings, settings._list_widget),
    'library': (library, library._trigger_name),
    'history': (history, history.search),
    'import': (import_preview, import_preview.table),
    'item': (item, item.stats),
    'entity': (entity, entity.summary),
    'logs': (logs, logs.table),
    'mobile': (mobile, mobile.link),
    'live': (live, live.game_path),
}

results = {
    name: scale_down(dialog, anchor)
    for name, (dialog, anchor) in dialogs.items()
}

history.raise_()
history.activateWindow()
app.processEvents()
click_scaled(history, history.search)
QTest.keyClicks(history._dialog_view.viewport(), 'quillmane')
app.processEvents()
results['history_text'] = history.search.text()
results['history_focus'] = history.search.hasFocus()
results['log_profile_rows'] = logs.table.rowCount()

interactive = (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QLineEdit)
missing = {}
header_missing = {}
for name, (dialog, _anchor) in dialogs.items():
    missing[name] = [
        widget.accessibleName() or widget.objectName() or type(widget).__name__
        for widget in dialog.scaled_surface.findChildren(QWidget)
        if isinstance(widget, interactive)
        and widget.isVisibleTo(dialog.scaled_surface)
        and not widget.toolTip().strip()
    ]
    headers = []
    for table in dialog.scaled_surface.findChildren(QTableWidget):
        headers.extend(
            f'{type(table).__name__}:{column}'
            for column in range(table.columnCount())
            if table.horizontalHeaderItem(column) is not None
            and not table.horizontalHeaderItem(column).toolTip().strip())
    for tree in dialog.scaled_surface.findChildren(QTreeWidget):
        headers.extend(
            f'{type(tree).__name__}:{column}'
            for column in range(tree.columnCount())
            if not tree.headerItem().toolTip(column).strip())
    header_missing[name] = headers

results['missing_tooltips'] = missing
results['missing_header_tooltips'] = header_missing
print(json.dumps(results))

for dialog, _anchor in reversed(tuple(dialogs.values())):
    dialog.close()
app.quit()
"""


def test_secondary_dialogs_scale_without_reflow_and_keep_tooltips(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['history_text'] == 'quillmane'
    assert result['history_focus'] is True
    assert result['log_profile_rows'] == 1
    for name in (
            'settings', 'library', 'history', 'import', 'item', 'entity',
            'logs', 'mobile', 'live'):
        assert result[name]['scale'] <= 0.51
        assert result[name]['surface'] == result[name]['design']
        assert result[name]['logical_unchanged'] is True
    assert result['missing_tooltips'] == {
        name: [] for name in (
            'settings', 'library', 'history', 'import', 'item', 'entity',
            'logs', 'mobile', 'live')}
    assert result['missing_header_tooltips'] == {
        name: [] for name in (
            'settings', 'library', 'history', 'import', 'item', 'entity',
            'logs', 'mobile', 'live')}
