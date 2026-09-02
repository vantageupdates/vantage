"""Exhaustive offscreen closure audit for authored Vantage UI affordances."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit, QPlainTextEdit, QScrollBar, QTabWidget,
    QTableWidget, QTextEdit, QTreeWidget, QWidget,
)

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.combat_diagnostics import CombatDiagnosticsDialog
from vantage.helpers.friends_manager import FriendsBackupStore, FriendsManagerDialog
from vantage.helpers.log_monitor import LogMonitorDialog
from vantage.helpers.overlay_editor import OverlayManagerDialog
from vantage.helpers.spell_library import SpellLibraryDialog
from vantage.helpers.settings import (
    CustomTriggerSettings, GinaImportPreviewDialog, TriggerMatchLogDialog)
from vantage.helpers.threat_settings import ThreatSettingsDialog
from vantage.parsers.combat import CombatExportOptionsDialog
from vantage.parsers.market import WikiEntityCard, WikiItemCard
from vantage.parsers.spells import CustomTrigger
from vantage.parsers.timers import TimerEditDialog


OUTPUT = Path(os.environ["VANTAGE_TEST_OUTPUT"])
OUTPUT.mkdir(parents=True, exist_ok=True)
eq_root = OUTPUT / "sample-everquest"
(eq_root / "Logs").mkdir(parents=True, exist_ok=True)
config.data.setdefault("general", {})["eq_log_dir"] = str(eq_root / "Logs")


def label(widget):
    text = getattr(widget, "text", lambda: "")()
    return (
        widget.accessibleName() or widget.objectName() or str(text).strip()
        or (f"{widget.metaObject().className()}@"
            f"{widget.parentWidget().metaObject().className()}"))


def authored_control(widget):
    if isinstance(widget, QScrollBar):
        return False
    if widget.objectName().startswith("qt_"):
        return False
    parent = widget.parentWidget()
    if isinstance(parent, QLineEdit):
        return False
    if isinstance(widget, QLineEdit) and isinstance(parent, (
            QAbstractSpinBox, QComboBox)):
        return False
    return isinstance(widget, (
        QAbstractButton, QAbstractItemView, QAbstractSlider,
        QAbstractSpinBox, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit))


def audit_surface(surface):
    missing = []
    missing_accessible = []
    for widget in surface.findChildren(QWidget):
        if not authored_control(widget) or not widget.isEnabled():
            continue
        if not widget.toolTip().strip():
            missing.append(f"{type(widget).__name__}:{label(widget)}")
        if not widget.accessibleName().strip() and not str(
                getattr(widget, "text", lambda: "")()).strip():
            missing_accessible.append(
                f"{type(widget).__name__}:{widget.objectName() or '<unnamed>'}")

    missing_headers = []
    for table in surface.findChildren(QTableWidget):
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            if item is not None and not item.toolTip().strip():
                missing_headers.append(
                    f"{table.objectName() or type(table).__name__}:{item.text()}")
    for tree in surface.findChildren(QTreeWidget):
        for column in range(tree.columnCount()):
            if not tree.headerItem().toolTip(column).strip():
                missing_headers.append(
                    f"{tree.objectName() or type(tree).__name__}:column-{column}")

    missing_tabs = []
    for tabs in surface.findChildren(QTabWidget):
        for index in range(tabs.count()):
            if not tabs.tabToolTip(index).strip():
                missing_tabs.append(
                    f"{tabs.objectName() or type(tabs).__name__}:"
                    f"{tabs.tabText(index)}")
    return {
        "missing_tooltips": sorted(set(missing)),
        "missing_accessible_names": sorted(set(missing_accessible)),
        "missing_header_tooltips": sorted(set(missing_headers)),
        "missing_tab_tooltips": sorted(set(missing_tabs)),
    }


app = VantageApp([])
trigger = CustomTrigger(
    "Closure audit", "You feel yourself starting to appear.",
    "00:00:15", alert_text="Invisibility dropping", timer_type="countdown")
combat = app._parsers_dict["combat"]
library = CustomTriggerSettings()
dialogs = {
    "settings": app._settings,
    "timer_editor": TimerEditDialog(parent=app._parsers_dict["timers"]),
    "combat_output": CombatExportOptionsDialog(combat._output_options(), combat),
    "threat": ThreatSettingsDialog(config.data["combat"]["threat"], combat),
    "overlay_manager": OverlayManagerDialog(app._notification_overlay, combat),
    "friends": FriendsManagerDialog(
        backup_store=FriendsBackupStore(OUTPUT / "friends-backups")),
    "log_profiles": LogMonitorDialog(app),
    "trigger_library": library,
    "trigger_history": TriggerMatchLogDialog(library),
    "gina_preview": GinaImportPreviewDialog([trigger]),
    "item_card": WikiItemCard({"n": "Manastone", "a30": 50000}),
    "entity_card": WikiEntityCard("Quillmane", "npc"),
    "mobile": app._mobile_dialog,
    "live_setup": app._mobile_dialog._live_setup,
    "combat_diagnostics": CombatDiagnosticsDialog(combat._tracker, combat),
    "spell_library": SpellLibraryDialog(
        app._parsers_dict["market"], app._parsers_dict["spells"]),
}
app.processEvents()

results = {}
for name, dialog in dialogs.items():
    surface = getattr(dialog, "scaled_surface", getattr(dialog, "_surface", dialog))
    results[name] = audit_surface(surface)

for name, panel in app._parsers_dict.items():
    results[f"panel_{name}"] = audit_surface(panel._surface)

(OUTPUT / "closure-ui-audit.json").write_text(
    json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results))

for dialog in reversed(tuple(dialogs.values())):
    dialog.close()
app.quit()
