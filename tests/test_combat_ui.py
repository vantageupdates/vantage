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
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QWidget)
from vantage.helpers.application import VantageApp

app = VantageApp([])
combat = app._parsers_dict['combat']
combat._set_collapsed(False)
stamp = datetime.datetime.now().replace(microsecond=0)
for offset, line in (
        (0, 'Alice hits a bat for 50 points of damage.'),
        (0.1, 'Alice begins casting Harm Touch.'),
        (0.2, 'a bat hits Alice for 7 points of damage.'),
        (0.5, 'You hit a bat for 100 points of damage.'),
        (1, 'a bat hits You for 25 points of damage.'),
        (2, 'a bat tries to slash You, but You dodge!'),
        (3, 'a bat tries to hit You, but your magical skin absorbs the blow!'),
        (4, 'Cleric heals You for 80 hit points.')):
    combat.parse(stamp + datetime.timedelta(seconds=offset), line)
for offset, player, value in ((3, 'Alice', 800), (4, 'Bob', 900)):
    combat.parse(
        stamp + datetime.timedelta(seconds=offset),
        f'**A Magic Die is rolled by {player}.')
    combat.parse(
        stamp + datetime.timedelta(seconds=offset, milliseconds=500),
        '**It could have been any number from 0 to 1000, '
        f'but this time it turned up {value}.')
combat.refresh()
combat.resize(260, 150)
combat.show()
app.processEvents()
interactive = (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox)
missing = [type(widget).__name__ for widget in combat._surface.findChildren(QWidget)
           if isinstance(widget, interactive) and widget.isVisible()
           and not widget.toolTip()]
print(json.dumps({
    'tabs': [combat.tabs.tabText(i) for i in range(combat.tabs.count())],
    'chart_kind': combat.chart_canvas._data['kind'],
    'healing_columns': combat.tables['Healing'].columnCount(),
    'tanking_columns': combat.tables['Tanking'].columnCount(),
    'tanking_detail_rows': combat.tables['Tanking Details'].rowCount(),
    'tanking_detail_tooltips': all(
        combat.tables['Tanking Details'].horizontalHeaderItem(column).toolTip()
        for column in range(combat.tables['Tanking Details'].columnCount())),
    'overview_headers': [
        combat.tables['Overview'].horizontalHeaderItem(column).text()
        for column in range(combat.tables['Overview'].columnCount())],
    'overview_tooltips': all(
        combat.tables['Overview'].horizontalHeaderItem(column).toolTip()
        for column in range(combat.tables['Overview'].columnCount())),
    'overview_total': [
        combat.tables['Overview'].item(0, column).text()
        for column in range(combat.tables['Overview'].columnCount())],
    'alice_overview': [
        combat.tables['Overview'].item(row, column).text()
        for row in range(combat.tables['Overview'].rowCount())
        if combat.tables['Overview'].item(row, 0).text() == 'Alice'
        for column in range(combat.tables['Overview'].columnCount())],
    'player_dps_headers': [
        combat.tables['Player DPS'].horizontalHeaderItem(column).text()
        for column in range(combat.tables['Player DPS'].columnCount())],
    'tanking_results': [
        combat.tables['Hit Distribution'].item(row, 2).text()
        for row in range(combat.tables['Hit Distribution'].rowCount())],
    'roll_sets': combat.tables['Roll Sets'].rowCount(),
    'roll_winner': combat.tables['Roll Sets'].item(0, 5).text(),
    'surface': [combat._surface.width(), combat._surface.height()],
    'window': [combat.width(), combat.height()],
    'missing_tooltips': missing,
}))
combat.hide()
app.quit()
"""


def test_combat_charts_healing_randoms_and_scaled_tooltips(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert "Charts" in result["tabs"]
    assert result["chart_kind"] == "line"
    assert result["healing_columns"] == 10
    assert result["tanking_columns"] == 18
    assert result["tanking_detail_rows"] >= 3
    assert result["tanking_detail_tooltips"] is True
    assert result["overview_headers"] == [
        "Damage By", "Total", "% of Tot", "Time", "DPS", "SDPS",
        "Hits", "Max Hit", "Avg Hit", "Dmg to PC", "NPC Max",
        "Specials", "Class", "Rank"]
    assert result["overview_tooltips"] is True
    assert result["overview_total"][0] == "Total"
    assert result["overview_total"][1] == "150"
    assert result["overview_total"][2] == "100.0%"
    assert result["alice_overview"][9] == "7"
    assert result["alice_overview"][10] == "7"
    assert result["alice_overview"][11] == "H"
    assert result["alice_overview"][12] == "Shadow Knight"
    assert result["player_dps_headers"] == [
        "Player", "Damage", "DPS", "SDPS", "Time", "Hits",
        "Attempts", "Accuracy", "Min", "Max", "Avg"]
    assert "Defended" in result["tanking_results"]
    assert "Absorbed" in result["tanking_results"]
    assert result["roll_sets"] == 1
    assert result["roll_winner"] == "Bob"
    assert result["surface"] == [520, 300]
    assert result["window"] == [260, 150]
    assert result["missing_tooltips"] == []
