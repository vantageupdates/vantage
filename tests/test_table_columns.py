import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config


ROOT = Path(__file__).resolve().parents[1]


def test_global_column_width_config_is_bounded_and_schema_safe():
    original = copy.deepcopy(config.data)
    try:
        config.data = {"general": {"table_column_widths": {
            "market/live-abc": [-4, "bad", 99999],
            "": [80],
            "broken": "not-a-list",
            "too-many": [40] * 65,
        }}}
        config.verify_settings()
        assert config.data["general"]["table_column_widths"] == {
            "market/live-abc": [28, 80, 2400],
        }
    finally:
        config.data = original


COLUMN_MANAGER_SCRIPT = r"""
import json
import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QMenu, QTableWidget
from vantage.helpers import config
from vantage.helpers.responsive import TableColumnManager

profile = Path(os.environ['VANTAGE_DATA_DIR'])
profile.mkdir(parents=True, exist_ok=True)
config.load(str(profile / 'vantage.config.json'))
config.verify_settings()
app = QApplication([])
manager = TableColumnManager(app)

def make_table(headers, widths):
    table = QTableWidget(2, len(headers))
    table.setObjectName('ReusableAuctionTable')
    table.setAccessibleName('Live auction history')
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setMinimumSectionSize(28)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
    return table

first = make_table(('Time', 'Seller', 'Message'), (72, 96, 220))
header = first.horizontalHeader()
header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
header.setStretchLastSection(True)
first.setSortingEnabled(True)
first.show()
QTest.qWait(70)

first.setColumnWidth(0, 111)
first.setColumnWidth(1, 177)
first.setColumnWidth(2, 333)
first.setCurrentCell(0, 1)
before_keyboard = first.columnWidth(1)
QTest.keyClick(first, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(30)
menus = [widget for widget in app.topLevelWidgets()
         if isinstance(widget, QMenu) and widget.isVisible()]
menu_actions = [action.text() for action in menus[-1].actions() if action.text()]
menus[-1].actions()[0].trigger()
menus[-1].close()
QTest.qWait(420)
manager.flush()
persisted_widths = list(config.data['general']['table_column_widths'].values())[0]
first_key = first.property('vantageColumnKeyResolved')

second = make_table(('Time', 'Seller', 'Message'), (48, 58, 68))
second.show()
QTest.qWait(70)
restored = [second.columnWidth(column) for column in range(3)]

different_schema = make_table(('Time', 'Buyer', 'Message'), (81, 91, 101))
different_schema.show()
QTest.qWait(70)
schema_widths = [different_schema.columnWidth(column) for column in range(3)]

second.setCurrentCell(0, 1)
manager.reset_view(second)
QTest.qWait(20)
reset_widths = [second.columnWidth(column) for column in range(3)]

print(json.dumps({
    'modes': [header.sectionResizeMode(column).name for column in range(3)],
    'stretch_last': header.stretchLastSection(),
    'sorting': first.isSortingEnabled(),
    'menu_actions': menu_actions,
    'keyboard_delta': first.columnWidth(1) - before_keyboard,
    'persisted': persisted_widths,
    'restored': restored,
    'schema_widths': schema_widths,
    'reset_widths': reset_widths,
    'first_key': first_key,
    'different_key': different_schema.property('vantageColumnKeyResolved'),
    'description': first.accessibleDescription(),
    'header_tip': header.toolTip(),
}))
app.quit()
"""


def test_every_column_is_interactive_keyboard_resizable_and_persistent(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", COLUMN_MANAGER_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["modes"] == ["Interactive"] * 3
    assert result["stretch_last"] is False
    assert result["sorting"] is True
    assert result["menu_actions"] == [
        "Widen Seller", "Narrow Seller", "Auto-fit Seller",
        "Reset this table's columns"]
    assert result["keyboard_delta"] == 32
    assert result["persisted"] == [111, 209, 333]
    assert result["restored"] == result["persisted"]
    assert result["schema_widths"] == [81, 91, 101]
    assert result["reset_widths"] == [70, 96, 220]
    assert result["first_key"] != result["different_key"]
    assert "Shift+F10" in result["description"]
    assert "double-click to auto-fit" in result["header_tip"]


APP_TABLES_SCRIPT = r"""
import json
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QTableView, QTreeView
from vantage.helpers.application import VantageApp

app = VantageApp([])
app._settings.show()
app.show_spell_library()
app.show_log_profiles()
for parser in app._parsers:
    parser.show()
QTest.qWait(140)

views = [
    widget for widget in app.allWidgets()
    if isinstance(widget, (QTableView, QTreeView)) and
    not isinstance(widget.window(), QFileDialog) and
    widget.model() is not None and widget.model().columnCount() > 0]
for view in views:
    app._column_widths._configure(view)
bad = []
for view in views:
    header = view.horizontalHeader()
    if header.stretchLastSection() or any(
            header.sectionResizeMode(column).name != 'Interactive'
            for column in range(header.count())):
        bad.append(view.objectName() or view.accessibleName() or
                   view.metaObject().className())
print(json.dumps({'count': len(views), 'bad': bad}))
app.quit()
"""


def test_all_live_vantage_tables_receive_interactive_columns(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", APP_TABLES_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=50)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["count"] >= 35
    assert result["bad"] == []


COMBAT_FIT_SCRIPT = r"""
import json
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp

app = VantageApp([])
combat = app._parsers_dict['combat']
combat.resize(520, 390)
combat.show()
QTest.qWait(120)
table = combat.tables['Overview']
app._column_widths._configure(table)
widths = [table.columnWidth(column) for column in range(table.columnCount())]
print(json.dumps({
    'sum': sum(widths),
    'leading_sum': sum(widths[:9]),
    'viewport': table.viewport().width(),
    'minimum': min(widths),
    'interactive': all(
        table.horizontalHeader().sectionResizeMode(column).name == 'Interactive'
        for column in range(table.columnCount())),
}))
app.quit()
"""


def test_compact_combat_columns_begin_inside_the_visible_right_edge(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", COMBAT_FIT_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["leading_sum"] <= result["viewport"]
    assert result["sum"] > result["viewport"]
    assert result["minimum"] >= 28
    assert result["interactive"] is True
