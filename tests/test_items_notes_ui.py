import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from vantage.helpers.application import VantageApp
from vantage.helpers.item_journal import parse_inventory_dump

app = VantageApp([])
panel = app._parsers_dict["items_notes"]
panel._journal.import_snapshot(parse_inventory_dump(Path(__import__("os").environ["TEST_DUMP"])))
panel._refresh_everything()
panel._quests._catalog = ["Journeyman's Boots Quest"]
panel._refresh_references()

panel.item_table.selectRow(0)
selected = panel._selected_row()
opened = []
panel._market._show_wiki_item_name = lambda name: opened.append(("Item", name))
panel._market._show_wiki_entity = lambda target, label, kind: opened.append((kind.title(), label))
panel._open_selected_item()

note_id = panel._journal.upsert_note(
    "", "JBoots plan",
    "Get @[Item: Journeyman's Boots] during @[Quest: Journeyman's Boots Quest] in @[Zone: South Ro]")
panel._current_note_id = ""
panel._refresh_notes()
panel._select_note_id(note_id)
panel._note_selected(panel.note_list.currentItem(), None)
panel._render_preview()
for kind, label in (("Item", "Journeyman's Boots"),
                    ("Quest", "Journeyman's Boots Quest"),
                    ("Zone", "South Ro")):
    from PySide6.QtCore import QUrl, QUrlQuery
    query = QUrlQuery()
    query.addQueryItem("kind", kind)
    query.addQueryItem("label", label)
    url = QUrl("vantage-ref://open")
    url.setQuery(query)
    panel._reference_clicked(url)

bar = app._parsers_dict["quickbar"]
initial = panel.isVisible()
bar._trigger("items_notes")
QTest.qWait(20)
opened_window = panel.isVisible()
bar._trigger("items_notes")
QTest.qWait(20)
closed_window = not panel.isVisible()

print(json.dumps({
    "tabs": [panel.tabs.tabText(i) for i in range(panel.tabs.count())],
    "rows": panel.item_table.rowCount(),
    "groups": sorted({row["group"] for row in panel._journal.rows()}),
    "references": [entry for entry in panel.note_editor._entries
                   if "Journeyman" in entry or entry == "Zone · South Ro"],
    "preview_has_links": "vantage-ref" in panel.note_preview.toHtml(),
    "opened": opened,
    "quickbar_initial": initial,
    "quickbar_opened": opened_window,
    "quickbar_closed": closed_window,
    "table_accessible": panel.item_table.accessibleName(),
    "editor_accessible": panel.note_editor.accessibleName(),
}))
app.quit()
'''


def test_items_notes_window_tracks_opens_links_and_toggles(tmp_path):
    dump = tmp_path / "Pyco-Inventory.txt"
    dump.write_text(
        "Location\tName\tID\tCount\tSlots\n"
        "General1\tJourneyman's Boots\t2300\t1\t0\n"
        "Bank1\tBone Chips\t13073\t20\t0\n",
        encoding="utf-8")
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    env["TEST_DUMP"] = str(dump)
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["tabs"] == ["Items", "Notes"]
    assert payload["rows"] == 2
    assert payload["groups"] == ["Bank", "Inventory"]
    assert "Item · Journeyman's Boots" in payload["references"]
    assert "Quest · Journeyman's Boots Quest" in payload["references"]
    assert payload["preview_has_links"] is True
    assert payload["opened"] == [
        ["Item", "Journeyman's Boots"],
        ["Item", "Journeyman's Boots"],
        ["Quest", "Journeyman's Boots Quest"],
        ["Zone", "South Ro"],
    ]
    assert payload["quickbar_initial"] is False
    assert payload["quickbar_opened"] is True
    assert payload["quickbar_closed"] is True
    assert payload["table_accessible"] == "Tracked EverQuest items"
    assert payload["editor_accessible"] == "Current note text"
