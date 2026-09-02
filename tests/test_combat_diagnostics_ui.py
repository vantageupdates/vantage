import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QLineEdit, QWidget)
from vantage.helpers.application import VantageApp

app = VantageApp([])
combat = app._parsers_dict['combat']
combat._open_parser_diagnostics()
dialog = combat._diagnostics_dialog
app.processEvents()

initial = len(combat._tracker.diagnostics)
dialog.capture.setChecked(True)
stamp = datetime.datetime(2026, 1, 1, 12, 0, 0)
for offset, line in enumerate((
        'You slash a bat for 12 points of damage.',
        'a bat dodges You\'s attack!',
        'You begin casting Ignite.',
        'a bat was hit by non-melee for 40 points of damage.',
        'a bat has taken 7 damage from your Flame Lick.',
        'You healed Bob for 25 hit points.',
        "Trader tells you, 'that spell hit hard'")):
    combat.parse(stamp + datetime.timedelta(seconds=offset), line)
dialog.refresh(force=True)
app.processEvents()

tabs = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
all_table = dialog.tables['All']
sources = [all_table.item(row, all_table.columnCount() - 1).text()
           for row in range(all_table.rowCount())]
interactive = (QAbstractButton, QAbstractItemView, QLineEdit)
missing = [type(widget).__name__ for widget in dialog.findChildren(QWidget)
           if isinstance(widget, interactive) and widget.isVisible()
           and not widget.toolTip()]
header_missing = [
    category for category, table in dialog.tables.items()
    for column in range(table.columnCount())
    if not table.horizontalHeaderItem(column).toolTip()]

print(json.dumps({
    'initial': initial,
    'capture': combat._tracker.diagnostics_enabled,
    'rows': all_table.rowCount(),
    'tabs': tabs,
    'chat_retained': any('Trader tells you' in value for value in sources),
    'missing_tooltips': missing,
    'header_missing': header_missing,
    'limit': combat._tracker.diagnostics.maxlen,
}))
dialog.close()
combat.hide()
app.quit()
"""


def test_parser_diagnostics_dialog_is_opt_in_filtered_and_explained(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["initial"] == 0
    assert result["capture"] is True
    assert result["rows"] == 6
    assert result["tabs"] == [
        "All (6)", "Melee (1)", "Defense (1)", "Direct Damage (1)",
        "DoT (1)", "Healing (1)", "Spells (1)", "Unmatched (0)"]
    assert result["chat_retained"] is False
    assert result["missing_tooltips"] == []
    assert result["header_missing"] == []
    assert result["limit"] == 5000
