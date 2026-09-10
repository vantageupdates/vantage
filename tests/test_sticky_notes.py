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
from PySide6.QtWidgets import QApplication

from vantage.helpers.application import VantageApp

app = VantageApp([])
panel = app._parsers_dict["items_notes"]
note_id = panel._journal.upsert_note(
    "", "Raid list", "Bring @[Item: Coldain Skin Boots]")
panel._remember_journal_stamp()
panel._refresh_notes()
panel._select_note_id(note_id)
panel._load_note_fields(note_id)

panel.sticky_note_button.click()
app.processEvents()
window = panel._sticky_windows[note_id]
created = {
    "visible": window.isVisible(),
    "sticky": panel._journal.note(note_id)["sticky"],
    "button": panel.sticky_note_button.text(),
    "minimum": [window.minimumWidth(), window.minimumHeight()],
}

window.title.setText("Raid list from sticky")
window.editor.setPlainText("Bring cold and magic resist gear")
QTest.qWait(420)
app.processEvents()
sticky_to_notes = {
    "title": panel.note_title.text(),
    "text": panel.note_editor.toPlainText(),
    "saved": panel._journal.note(note_id)["text"],
}

panel.note_title.setText("Raid list from Notes")
panel.note_editor.setPlainText("Meet at Icewell Keep")
panel._save_current_note()
app.processEvents()
notes_to_sticky = {
    "title": window.title.text(),
    "text": window.editor.toPlainText(),
}

# Device Sync replaces the same atomic journal file. The normal settings signal
# must refresh both the main editor and every open sticky immediately.
path = panel._journal.path
payload = json.loads(path.read_text(encoding="utf-8"))
payload["notes"][0]["title"] = "Synced raid list"
payload["notes"][0]["text"] = "Synced from the second PC"
path.write_text(json.dumps(payload), encoding="utf-8")
app._signals["settings"].config_updated.emit()
app.processEvents()
synced = {
    "title": panel.note_title.text(),
    "text": panel.note_editor.toPlainText(),
    "sticky_title": window.title.text(),
    "sticky_text": window.editor.toPlainText(),
}

panel.show()
window.show()
window.raise_()
window.title.setFocus()
QTest.keyClick(window.title, Qt.Key.Key_Tab)
first_tab = QApplication.focusWidget() is window.editor
QTest.keyClick(window.editor, Qt.Key.Key_Tab)
second_tab = QApplication.focusWidget() is window.open_button
QTest.keyClick(window.open_button, Qt.Key.Key_Tab)
third_tab = QApplication.focusWidget() is window.unpin_button
QTest.keyClick(window.unpin_button, Qt.Key.Key_Backtab)
reverse_tab = QApplication.focusWidget() is window.open_button
accessibility = {
    "title": window.title.accessibleName(),
    "editor": window.editor.accessibleName(),
    "open": window.open_button.accessibleName(),
    "unpin": window.unpin_button.accessibleName(),
}

window.editor.setFocus()
QTest.keyClick(window.editor, Qt.Key.Key_Escape)
QTest.qWait(20)
app.processEvents()
hidden = {
    "visible": window.isVisible(),
    "still_sticky": panel._journal.note(note_id)["sticky"],
    "button": panel.sticky_note_button.text(),
    "focus_returned": panel._surface.focusWidget() is panel.sticky_note_button,
}
panel.sticky_note_button.click()
app.processEvents()
shown_again = window.isVisible()
window.unpin_button.click()
QTest.qWait(20)
app.processEvents()
returned = {
    "window_kept": note_id in panel._sticky_windows,
    "sticky": panel._journal.note(note_id)["sticky"],
    "note_exists": panel._journal.note(note_id) is not None,
    "button": panel.sticky_note_button.text(),
    "focus_returned": panel._surface.focusWidget() is panel.sticky_note_button,
}

print(json.dumps({
    "created": created,
    "sticky_to_notes": sticky_to_notes,
    "notes_to_sticky": notes_to_sticky,
    "synced": synced,
    "keyboard": [first_tab, second_tab, third_tab, reverse_tab],
    "hidden": hidden,
    "shown_again": shown_again,
    "returned": returned,
    "accessibility": accessibility,
}))
app.quit()
'''


RESTORE_SCRIPT = r'''
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
panel = app._parsers_dict["items_notes"]
app.processEvents()
windows = list(panel._sticky_windows.values())
window = windows[0] if windows else None
print(json.dumps({
    "count": len(windows),
    "visible": bool(window and window.isVisible()),
    "title": window.title.text() if window else "",
    "text": window.editor.toPlainText() if window else "",
    "geometry": [window.x(), window.y(), window.width(), window.height()]
        if window else [],
}))
app.quit()
'''


CREATE_RESTORABLE_SCRIPT = r'''
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
panel = app._parsers_dict["items_notes"]
note_id = panel._journal.upsert_note("", "Persistent sticky", "Still here")
panel._journal.set_note_sticky(note_id, True, [32, 44, 360, 220])
print(json.dumps({"note_id": note_id}))
app.quit()
'''


def test_notes_convert_to_small_interconnected_synced_stickies(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["created"] == {
        "visible": True,
        "sticky": True,
        "button": "Hide sticky",
        "minimum": [240, 160],
    }
    assert result["sticky_to_notes"] == {
        "title": "Raid list from sticky",
        "text": "Bring cold and magic resist gear",
        "saved": "Bring cold and magic resist gear",
    }
    assert result["notes_to_sticky"] == {
        "title": "Raid list from Notes",
        "text": "Meet at Icewell Keep",
    }
    assert result["synced"] == {
        "title": "Synced raid list",
        "text": "Synced from the second PC",
        "sticky_title": "Synced raid list",
        "sticky_text": "Synced from the second PC",
    }
    assert result["keyboard"] == [True, True, True, True]
    assert result["hidden"] == {
        "visible": False,
        "still_sticky": True,
        "button": "Show sticky",
        "focus_returned": True,
    }
    assert result["shown_again"] is True
    assert result["returned"] == {
        "window_kept": False,
        "sticky": False,
        "note_exists": True,
        "button": "Make sticky",
        "focus_returned": True,
    }
    assert result["accessibility"] == {
        "title": "Sticky note title",
        "editor": "Sticky note text",
        "open": "Open this sticky note in Items and Notes",
        "unpin": "Stop showing this note as a floating sticky note",
    }


def test_sticky_note_reopens_after_vantage_restart(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")

    subprocess.run(
        [sys.executable, "-c", CREATE_RESTORABLE_SCRIPT],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=45)
    completed = subprocess.run(
        [sys.executable, "-c", RESTORE_SCRIPT],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    geometry = result.pop("geometry")
    assert result == {
        "count": 1,
        "visible": True,
        "title": "Persistent sticky",
        "text": "Still here",
    }
    # Window managers may offset a tool window frame by a couple of pixels.
    assert abs(geometry[0] - 32) <= 3
    assert abs(geometry[1] - 44) <= 3
    assert geometry[2:] == [360, 220]
