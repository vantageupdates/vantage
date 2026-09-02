import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
    QFileDialog, QLineEdit, QWidget)
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.settings import TriggerMatchLogDialog
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
spells = app._parsers_dict['spells']
spells._active_character = 'Mindflux'
spells._current_zone = 'Velketor'
valid = CustomTrigger(
    name='Charm {S}', text='{S} has been charmed.', category='Enchanter',
    alert_text='CHARM {S}', tts_text='Charm on {S}', clipboard_text='{S}',
    source='Imported package', enabled=False)
invalid = CustomTrigger(
    name='Broken regex', text='(', category='Testing', regex=True,
    source='Manual', enabled=False)
config.data['spells']['custom_timers'] = [valid.to_list(), invalid.to_list()]
spells.clear_trigger_history()
spells.load_custom_timers()
spells.load_custom_timers()
compile_errors = [
    entry for entry in spells.trigger_history()
    if entry.get('status') == 'Error']

app.clipboard().setText('unchanged')
count = spells.test_trigger_line(
    '[Sun Aug 30 12:00:00 2026] A crystalline watcher has been charmed.',
    'Charm {S}')
history = spells.trigger_history()
test_entry = next(entry for entry in history if entry.get('status') == 'Test')
clipboard_after_dry_run = app.clipboard().text()
overlay_side_effect = any(
    entry.get('title', '').startswith('Charm')
    for overlay in app._notification_overlay.overlays.values()
    for entry in overlay._entries)

dialog = TriggerMatchLogDialog()
dialog.show()
app.processEvents()
all_rows = dialog.table.rowCount()
status_index = dialog.status_filter.findData('Test')
dialog.status_filter.setCurrentIndex(status_index)
dialog.search.setText('watcher')
app.processEvents()
filtered_rows = dialog.table.rowCount()
dialog._copy_rows()
copied = app.clipboard().text()

dialog.search.clear()
dialog.status_filter.setCurrentIndex(0)
dialog.profile_filter.setCurrentIndex(0)
dialog.category_filter.setCurrentIndex(0)
app.processEvents()
export_path = Path(r'__EXPORT_PATH__')
QFileDialog.getSaveFileName = staticmethod(
    lambda *_args, **_kwargs: (str(export_path), 'CSV table (*.csv)'))
dialog._export_csv()

dialog.test_line.setText('A frosty guardian has been charmed.')
dialog.test_trigger.setCurrentIndex(
    dialog.test_trigger.findData('Charm {S}'))
dialog._dry_run()

interactive = (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QLineEdit)
missing = [type(widget).__name__ for widget in dialog.findChildren(QWidget)
           if isinstance(widget, interactive) and widget.isVisible()
           and not widget.toolTip()]

print(json.dumps({
    'dry_run_count': count,
    'compile_errors': len(compile_errors),
    'profile': test_entry.get('profile'),
    'zone': test_entry.get('zone'),
    'match_us_positive': test_entry.get('match_us', 0) > 0,
    'resolved': test_entry.get('output'),
    'raw_line': test_entry.get('line'),
    'clipboard_unchanged_after_test': clipboard_after_dry_run == 'unchanged',
    'copy_contains_headers': 'Status' in copied and 'Resolved output' in copied,
    'overlay_side_effect': overlay_side_effect,
    'all_rows': all_rows,
    'filtered_rows': filtered_rows,
    'columns': dialog.table.columnCount(),
    'header_tooltips': [
        bool(dialog.table.horizontalHeaderItem(i).toolTip())
        for i in range(dialog.table.columnCount())],
    'csv_exists': export_path.is_file(),
    'csv_lines': len(export_path.read_text(encoding='utf-8-sig').splitlines()),
    'history_after_dialog_test': len(spells.trigger_history()),
    'missing_tooltips': missing,
}))
dialog.close()
app.quit()
"""


def test_trigger_match_log_search_dry_run_export_and_tooltips(tmp_path):
    export_path = tmp_path / "trigger-match-log.csv"
    script = SCRIPT.replace("__EXPORT_PATH__", str(export_path).replace("\\", "\\\\"))
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["dry_run_count"] == 1
    assert result["compile_errors"] == 1
    assert result["profile"] == "Mindflux"
    assert result["zone"] == "Velketor"
    assert result["match_us_positive"] is True
    assert "A crystalline watcher" in result["resolved"]
    assert result["raw_line"].startswith("[Sun Aug 30")
    assert result["clipboard_unchanged_after_test"] is True
    assert result["copy_contains_headers"] is True
    assert result["overlay_side_effect"] is False
    assert result["all_rows"] == 2
    assert result["filtered_rows"] == 1
    assert result["columns"] == 10
    assert all(result["header_tooltips"])
    assert result["csv_exists"] is True
    assert result["csv_lines"] == 3
    assert result["history_after_dialog_test"] == 3
    assert result["missing_tooltips"] == []
