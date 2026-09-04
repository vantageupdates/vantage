import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.market import GearItem, gear_comparison_rows


ROOT = Path(__file__).resolve().parents[1]


def test_comparison_rows_report_values_deltas_and_tied_leaders():
    rows = gear_comparison_rows((
        GearItem(name="Base", ac=10, hp=100, awis=5),
        GearItem(name="Armor", ac=15, hp=50, awis=5),
        GearItem(name="Health", ac=8, hp=120, awis=2),
    ))
    ac = next(row for row in rows if row["key"] == "ac")
    hp = next(row for row in rows if row["key"] == "hp")
    wis = next(row for row in rows if row["key"] == "awis")
    assert ac["values"] == (10, 15, 8)
    assert ac["deltas"] == (0, 5, -2)
    assert ac["leaders"] == (1,)
    assert hp["leaders"] == (2,)
    assert wis["leaders"] == (0, 1)


SCRIPT = r"""
import json
from PySide6.QtWidgets import QAbstractItemView
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.market import GearItem, WikiItemCard

config.data["general"]["startup_window_state"] = "normal"
app = VantageApp([])
market = app._parsers_dict["market"]
market._refresh_timer.stop()
items = [
    GearItem(name="Base Robe", classes=8192, races=1, slots=131072,
             ac=10, hp=100, awis=5, wornName="Flowing Thought I"),
    GearItem(name="Armor Robe", classes=8192, races=1, slots=131072,
             ac=15, hp=50, awis=5, clickName="Shielding"),
    GearItem(name="Health Robe", classes=8192, races=1, slots=131072,
             ac=8, hp=120, awis=2, procName="Stun"),
]
market._gear_model.set_items(items)
market._gear_model.set_prices([
    {"n": "Base Robe", "t": 0, "a30": 1000, "t30": 3},
    {"n": "Armor Robe", "t": 0, "a30": 1400, "t30": 4},
    {"n": "Health Robe", "t": 0, "a30": 900, "t30": 2},
])
card = WikiItemCard(
    {"n": "Base Robe", "_gear": items[0]}, market,
    catalog=market._gear_model.items, price_lookup=market._auction_price)
card.show()
card.compare_button.click()
app.processEvents()
compare = card.compare_panel
compare.search.setText("Armor")
app.processEvents()
armor_results = compare._completion_model.stringList()
armor_add_enabled = compare.add_button.isEnabled()
compare.add_button.click()
compare.search.setText("Health")
app.processEvents()
health_results = compare._completion_model.stringList()
compare._add_completion("Health Robe")
app.processEvents()
table = compare.table
rows = {table.verticalHeaderItem(row).text(): row for row in range(table.rowCount())}
ac_row = rows["AC"]
hp_row = rows["HP"]
result = {
    "main_has_mode": hasattr(market, "compare_mode_button"),
    "main_selection_mode": market.gear_table.selectionMode().value,
    "single_mode": QAbstractItemView.SelectionMode.SingleSelection.value,
    "current_is_compare": card.pages.currentWidget() is compare,
    "design_size": [card._dialog_design_size.width(), card._dialog_design_size.height()],
    "window_size": [card.width(), card.height()],
    "window_title": card.windowTitle(),
    "card_tip": card.compare_button.toolTip(),
    "search_name": compare.search.accessibleName(),
    "search_description": compare.search.accessibleDescription(),
    "armor_results": armor_results,
    "armor_add_enabled": armor_add_enabled,
    "health_results": health_results,
    "selected": [item.name for item in compare.items],
    "selected_labels": [compare.selected_items.item(i).text() for i in range(compare.selected_items.count())],
    "headers": [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())],
    "ac": [table.item(ac_row, column).text() for column in range(3)],
    "hp": [table.item(hp_row, column).text() for column in range(3)],
    "price": [table.item(rows["30d price"], column).text() for column in range(3)],
    "worn": [table.item(rows["Worn"], column).text() for column in range(3)],
    "gain_color": table.item(ac_row, 1).foreground().color().name(),
    "loss_color": table.item(ac_row, 2).foreground().color().name(),
    "summary": compare.summary.text(),
    "summary_accessible": compare.summary.accessibleName(),
    "table_description": table.accessibleDescription(),
}
compare.selected_items.setCurrentRow(1)
compare.remove_button.click()
result["after_remove"] = [item.name for item in compare.items]
compare.back_button.click()
result["back_to_item"] = card.pages.currentWidget() is card.item_page
card.close()
app.quit()
print(json.dumps(result))
"""


def test_comparison_lives_inside_item_card_with_independent_search(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["main_has_mode"] is False
    assert result["main_selection_mode"] == result["single_mode"]
    assert result["current_is_compare"] is True
    assert result["design_size"] == [800, 500]
    assert result["window_size"] == [800, 500]
    assert result["window_title"] == "Vantage · Compare · Base Robe"
    assert "independent full-catalog search" in result["card_tip"]
    assert result["search_name"] == "Search all P99 items to compare"
    assert "independently of the main Market list" in result["search_description"]
    assert result["armor_results"] == ["Armor Robe"]
    assert result["armor_add_enabled"] is True
    assert result["health_results"] == ["Health Robe"]
    assert result["selected"] == ["Base Robe", "Armor Robe", "Health Robe"]
    assert result["selected_labels"][0] == "BASE · Base Robe"
    assert result["headers"] == ["BASE · Base Robe", "Armor Robe", "Health Robe"]
    assert result["ac"] == ["+10 · BASE", "BEST · +15 · GAIN +5", "+8 · LOSS -2"]
    assert result["hp"] == ["+100 · BASE", "+50 · LOSS -50", "BEST · +120 · GAIN +20"]
    assert result["price"] == ["1,000 pp · BASE", "1,400 pp · PRICE +400 pp", "900 pp · PRICE -100 pp"]
    assert result["worn"] == ["Flowing Thought I", "—", "—"]
    assert result["gain_color"] == "#8cf0c3"
    assert result["loss_color"] == "#ffaa9d"
    assert "GAIN" in result["summary"] and "LOSS" in result["summary"]
    assert "gains" in result["summary_accessible"]
    assert "losses" in result["summary_accessible"]
    assert "GAIN, LOSS, or SAME text and color" in result["table_description"]
    assert result["after_remove"] == ["Base Robe", "Health Robe"]
    assert result["back_to_item"] is True
