import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers.friends_manager import (
    FriendsBackupStore,
    friend_ini_files,
    friend_server_suffix,
    merge_friend_files,
    normalize_friend_names,
    push_friends,
    render_friends_ini,
)


ROOT = Path(__file__).resolve().parents[1]


def test_eqtool_server_suffix_scan_merge_and_normalization(tmp_path):
    root = tmp_path / "EverQuest"
    root.mkdir()
    alice = root / "Alice_P1999Green.ini"
    bob = root / "Bob_P1999Green.ini"
    alice.write_text(
        "[Friends]\nFriend0=Zed\nFriend1=alice\nFriend2=*NULL*\n"
        "[Blocked]\nBlocked0=NotAFriend\n",
        encoding="utf-8")
    bob.write_text(
        "[Friends]\nFriend0=ALICE\nFriend1=Bob\n",
        encoding="utf-8")
    (root / "UI_Alice_P1999Green.ini").write_text(
        "[Friends]\nFriend0=Ignored\n", encoding="utf-8")
    (root / "Alice_P1999Blue.ini").write_text(
        "[Friends]\nFriend0=WrongServer\n", encoding="utf-8")

    assert friend_server_suffix("P1999Red") == "P1999PVP"
    assert friend_server_suffix("P1999Green") == "P1999Green"
    files = friend_ini_files(root, "P1999Green")
    assert [path.name for path in files] == [
        "Alice_P1999Green.ini", "Bob_P1999Green.ini"]
    friends, errors = merge_friend_files(files)
    assert friends == ["alice", "Bob", "Zed"]
    assert errors == []
    assert normalize_friend_names(
        [" Zed ", "zed", "", "*NULL*", "Amy"]) == ["Amy", "Zed"]
    assert len(normalize_friend_names(
        [f"Friend{index:03d}" for index in range(120)])) == 100


def test_eqtool_friends_section_replacement_preserves_other_sections():
    original = (
        "[Defaults]\r\nWindowedMode=TRUE\r\n"
        "[Friends]\r\nFriend0=Old\r\nFriend20=Stale\r\n"
        "[Blocked]\r\nBlocked0=KeepMe\r\n")
    rendered = render_friends_ini(original, ["Zed", "alice", "ALICE"])

    assert rendered.startswith(
        "[Defaults]\r\nWindowedMode=TRUE\r\n[Friends]\r\n"
        "Friend0=alice\r\nFriend1=Zed\r\nFriend2=*NULL*\r\n")
    assert rendered.count("Friend99=*NULL*") == 1
    assert "Friend20=Stale" not in rendered
    assert rendered.endswith("[Blocked]\r\nBlocked0=KeepMe\r\n")

    appended = render_friends_ini("[Defaults]\nWindowedMode=TRUE\n", ["Amy"])
    assert "\n[Friends]\nFriend0=Amy\nFriend1=*NULL*\n" in appended


def test_push_has_exact_recoverable_backup_and_updates_every_file(tmp_path):
    root = tmp_path / "EverQuest"
    root.mkdir()
    first = root / "Alice_P1999Green.ini"
    second = root / "Bob_P1999Green.ini"
    first_bytes = (
        b"[Friends]\r\nFriend0=Before\r\n[Defaults]\r\nSound=TRUE\r\n")
    second_bytes = (
        b"\xef\xbb\xbf[Defaults]\r\nLocale=English\r\n[Friends]\r\n"
        b"Friend0=Other\r\n")
    first.write_bytes(first_bytes)
    second.write_bytes(second_bytes)
    store = FriendsBackupStore(tmp_path / "profile" / "friends-backups")

    report = push_friends(
        [first, second], ["Zed", "amy", "AMY"], "P1999Green", store)

    assert report.errors == ()
    assert report.updated == (str(first), str(second))
    assert Path(report.backup_manifest).is_file()
    assert store.has_backup() is True
    for path in (first, second):
        text = path.read_text(encoding="utf-8-sig")
        assert "Friend0=amy" in text
        assert "Friend1=Zed" in text
        assert "Friend99=*NULL*" in text

    restored = store.restore_latest()
    assert restored.errors == ()
    assert first.read_bytes() == first_bytes
    assert second.read_bytes() == second_bytes


SCRIPT = r"""
import json
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QHelpEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from vantage.helpers import config
from vantage.helpers.friends_manager import FriendsBackupStore, FriendsManagerDialog


def tooltip(dialog, control):
    logical = control.mapTo(dialog.scaled_surface, control.rect().center())
    scene = dialog._dialog_proxy.mapToScene(QPointF(logical))
    point = dialog._dialog_view.mapFromScene(scene)
    event = QHelpEvent(
        QEvent.Type.ToolTip, point,
        dialog._dialog_view.viewport().mapToGlobal(point))
    QToolTip.hideText()
    QApplication.sendEvent(dialog._dialog_view.viewport(), event)
    app.processEvents()
    return QToolTip.text()


def click(dialog, control):
    logical = control.mapTo(dialog.scaled_surface, control.rect().center())
    scene = dialog._dialog_proxy.mapToScene(QPointF(logical))
    point = dialog._dialog_view.mapFromScene(scene)
    QTest.mouseClick(
        dialog._dialog_view.viewport(), Qt.MouseButton.LeftButton, pos=point)


root = Path(os.environ["VANTAGE_TEST_EQ_ROOT"])
logs = root / "Logs"
logs.mkdir(parents=True)
(root / "Alice_P1999Green.ini").write_text(
    "[Friends]\nFriend0=Zed\nFriend1=Amy\n", encoding="utf-8")
config.data.setdefault("general", {})["eq_log_dir"] = str(logs)

app = QApplication.instance() or QApplication([])
dialog = FriendsManagerDialog(
    backup_store=FriendsBackupStore(
        Path(os.environ["VANTAGE_DATA_DIR"]) / "friends-backups"))
dialog.show()
QTest.qWait(80)
normal_layout = {
    "server": [dialog.server.x(), dialog.server.y(),
               dialog.server.width(), dialog.server.height()],
    "editor": [dialog.editor.x(), dialog.editor.y(),
               dialog.editor.width(), dialog.editor.height()],
    "push": [dialog.push_button.x(), dialog.push_button.y(),
             dialog.push_button.width(), dialog.push_button.height()],
}
tooltips = {
    "server": tooltip(dialog, dialog.server),
    "editor": tooltip(dialog, dialog.editor),
    "reload": tooltip(dialog, dialog.reload_button),
    "restore": tooltip(dialog, dialog.restore_button),
    "push": tooltip(dialog, dialog.push_button),
}
dialog.resize(dialog.minimumSize())
QTest.qWait(80)
small_layout = {
    "server": [dialog.server.x(), dialog.server.y(),
               dialog.server.width(), dialog.server.height()],
    "editor": [dialog.editor.x(), dialog.editor.y(),
               dialog.editor.width(), dialog.editor.height()],
    "push": [dialog.push_button.x(), dialog.push_button.y(),
             dialog.push_button.width(), dialog.push_button.height()],
}
click(dialog, dialog.editor)
dialog.editor.moveCursor(QTextCursor.MoveOperation.End)
QTest.keyClick(dialog._dialog_view.viewport(), Qt.Key.Key_Return)
QTest.keyClicks(dialog._dialog_view.viewport(), "Bob")
app.processEvents()

print(json.dumps({
    "friends": dialog.editor.toPlainText().splitlines(),
    "files": len(dialog._scan.files),
    "source": dialog.source.text(),
    "logical": [dialog.scaled_surface.width(), dialog.scaled_surface.height()],
    "minimum": [dialog.width(), dialog.height()],
    "scale": round(dialog.uniform_scale, 3),
    "normal_layout": normal_layout,
    "small_layout": small_layout,
    "tooltips": tooltips,
}))
dialog.close()
app.quit()
"""


def test_friends_dialog_scales_without_reflow_and_forwards_input_tooltips(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    env["VANTAGE_TEST_EQ_ROOT"] = str(tmp_path / "EverQuest")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["friends"] == ["Amy", "Zed", "Bob"]
    assert result["files"] == 1
    assert result["source"].startswith("SOURCE · ")
    assert result["logical"] == [650, 460]
    assert result["minimum"] == [195, 138]
    assert result["scale"] == 0.3
    assert result["small_layout"] == result["normal_layout"]
    assert all(result["tooltips"].values())
