"""Native, multi-view EverQuest combat parser workspace."""

import csv
import datetime
import json
from pathlib import Path
import re

from PySide6.QtCore import (
    QMimeData, QObject, QSize, QThread, Qt, QTimer, Signal, Slot)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox, QHeaderView,
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
    QSplitter, QStyleOptionViewItem, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.activity_archive import ActivityArchive
from vantage.helpers.chat_archive import ChatArchive
from vantage.helpers.combat import (
    ChatEvent, CoinEvent, CombatTracker, FactionEvent, LootEvent,
    build_random_sets)
from vantage.helpers.combat_diagnostics import CombatDiagnosticsDialog
from vantage.helpers.combat_charts import (
    CHART_MODES, CombatChartWidget, build_chart_data)
from vantage.helpers.combat_exports import (
    bbcode_table, detailed_plain_text, eq_summary_lines, html_report,
    tabular_text, xml_report)
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.responsive import (
    ensure_table_header_tooltips, ensure_tab_tooltips)
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spell_catalog import infer_p99_class
from vantage.helpers.threat import ThreatEstimator
from vantage.helpers.threat_settings import ThreatSettingsDialog


LOG_TIMESTAMP = re.compile(r"^\[(?P<value>[^\]]+)\]")

# The supplied GamParse binary maps the P99-era Harm Touch cast to ``H`` in
# its Overview / Specials column.  Keep this deliberately narrow: Vantage
# never claims a special that the local log did not actually expose.
GAMPARSE_P99_SPECIAL_CODES = (("harm touch", "H"),)


class PercentBarDelegate(QStyledItemDelegate):
    """Paint a muted in-cell bar without adding progress-bar widgets."""

    def paint(self, painter, option, index):
        clean_option = QStyleOptionViewItem(option)
        self.initStyleOption(clean_option, index)
        text = str(clean_option.text or '')
        try:
            percent = max(0.0, min(100.0, float(text.rstrip('%'))))
        except ValueError:
            super().paint(painter, clean_option, index)
            return
        clean_option.text = ''
        style = (
            clean_option.widget.style() if clean_option.widget
            else QApplication.style())
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            clean_option, painter, clean_option.widget)
        painter.save()
        if percent > 0:
            color = QColor('#6B522E')
            color.setAlpha(118)
            bar = option.rect.adjusted(1, 2, -1, -2)
            bar.setWidth(max(1, int(bar.width() * percent / 100.0)))
            painter.fillRect(bar, color)
        selected = clean_option.state & QStyle.StateFlag.State_Selected
        painter.setPen(
            clean_option.palette.highlightedText().color() if selected
            else clean_option.palette.text().color())
        painter.drawText(
            clean_option.rect.adjusted(3, 0, -3, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            text)
        painter.restore()


def _reverse_log_lines(path, block_size=64 * 1024):
    """Yield a large log backwards without loading the full file in memory."""
    with path.open("rb") as source:
        source.seek(0, 2)
        position = source.tell()
        pending = b""
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            source.seek(position)
            pending = source.read(read_size) + pending
            lines = pending.split(b"\n")
            pending = lines[0]
            for line in reversed(lines[1:]):
                if line:
                    yield line.rstrip(b"\r").decode(
                        "utf-8", errors="replace")
        if pending:
            yield pending.rstrip(b"\r").decode("utf-8", errors="replace")


def _line_timestamp(line):
    match = LOG_TIMESTAMP.match(line)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(
            match.group("value"), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


class LogSearchWorker(QObject):
    finished = Signal(list, str, bool)

    def __init__(
            self, directory, query, limit=1500, regex=False, reverse=True,
            since=None, until=None):
        super().__init__()
        self.directory = Path(directory)
        self.query = str(query)
        self.limit = max(1, min(20000, int(limit)))
        self.regex = bool(regex)
        self.reverse = bool(reverse)
        self.since = since
        self.until = until

    @Slot()
    def run(self):
        results = []
        truncated = False
        try:
            pattern = None
            if self.regex:
                try:
                    pattern = re.compile(self.query, re.IGNORECASE)
                except re.error as error:
                    self.finished.emit([], f"Invalid regular expression: {error}", False)
                    return
            folded_query = self.query.casefold()
            files = sorted(
                self.directory.glob('eqlog*.txt'),
                key=lambda path: path.stat().st_mtime,
                reverse=self.reverse)
            for path in files:
                if self.reverse:
                    # Reverse results use an unknown physical line number until
                    # selected; avoiding a full-file count keeps the search fast.
                    lines = ((None, line) for line in _reverse_log_lines(path))
                else:
                    log = path.open('r', encoding='utf-8', errors='replace')
                    lines = enumerate(log, 1)
                try:
                    for line_number, line in lines:
                        if QThread.currentThread().isInterruptionRequested():
                            self.finished.emit([], '', False)
                            return
                        clean_line = line.rstrip('\r\n')
                        timestamp = _line_timestamp(clean_line)
                        if self.since and timestamp and timestamp < self.since:
                            if self.reverse:
                                break
                            continue
                        if self.until and timestamp and timestamp > self.until:
                            continue
                        matched = (
                            bool(pattern.search(clean_line)) if pattern else
                            folded_query in clean_line.casefold())
                        if matched:
                            results.append((
                                path.name,
                                line_number if line_number is not None else "—",
                                clean_line))
                            if len(results) >= self.limit:
                                truncated = True
                                break
                finally:
                    if not self.reverse:
                        log.close()
                if truncated:
                    break
            self.finished.emit(results, '', truncated)
        except OSError as error:
            self.finished.emit([], str(error), False)


class CombatExportOptionsDialog(UniformScaleDialog):
    """Compact settings shared by EQ, text, and HTML output actions."""

    def __init__(self, options, parent=None):
        super().__init__(
            QSize(540, 486), parent, minimum_size=QSize(216, 194))
        self.setWindowTitle("Combat Output Options")
        self._initial = dict(options or {})
        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)
        notice = QLabel(
            "OUTPUT IS COPY-ONLY · Vantage never types into or sends input to EverQuest")
        notice.setObjectName("CombatDataNotice")
        notice.setWordWrap(True)
        notice.setFixedHeight(40)
        notice.setToolTip(
            "EQ-formatted summaries are placed on the clipboard for you to paste manually")
        layout.addWidget(notice)

        eq_group = QGroupBox("EQ clipboard summary")
        eq_form = QFormLayout(eq_group)
        eq_form.setContentsMargins(8, 7, 8, 7)
        eq_form.setSpacing(5)
        self.output_channel = QLineEdit(
            str(self._initial.get("output_channel", "")))
        self.output_channel.setPlaceholderText("Optional, e.g. /gu")
        self.output_channel.setAccessibleName("Default EverQuest output channel")
        self.output_channel.setToolTip(
            "Optional text prefix copied with each line; Vantage never submits it to the game")
        eq_form.addRow("Channel prefix", self.output_channel)
        self.separator = QLineEdit(
            str(self._initial.get("separator", " | ") or " | "))
        self.separator.setMaxLength(20)
        self.separator.setAccessibleName("EQ summary separator")
        self.separator.setToolTip(
            "Text placed between the encounter summary and each ranked player")
        eq_form.addRow("Separator", self.separator)
        self.top_players = QComboBox()
        for label, value in (("All", 0), ("Top 5", 5), ("Top 10", 10),
                             ("Top 15", 15), ("Top 20", 20), ("Top 40", 40)):
            self.top_players.addItem(label, value)
        index = self.top_players.findData(
            int(self._initial.get("top_players", 10) or 0))
        self.top_players.setCurrentIndex(max(0, index))
        self.top_players.setAccessibleName("Number of players in EQ summary")
        self.top_players.setToolTip(
            "Limit ranked players to keep the clipboard text within practical EQ line lengths")
        eq_form.addRow("Players", self.top_players)
        eq_checks = QWidget()
        eq_checks_layout = QGridLayout(eq_checks)
        eq_checks_layout.setContentsMargins(0, 0, 0, 0)
        eq_checks_layout.setSpacing(4)
        self.eq_checks = {}
        for index, (key, label, tooltip) in enumerate((
                ("show_opponent", "Opponent", "Include target name and encounter duration"),
                ("show_damage", "DMG", "Include total damage for the encounter and each player"),
                ("show_percentage", "% DMG", "Include each player's share of total damage"),
                ("show_dps", "DPS", "Include active DPS for each player"),
                ("show_sdps", "SDPS", "Include damage scaled over full encounter duration"),
                ("append_dps_label", "Add ‘dps’", "Append the letters dps to active DPS values"))):
            check = QCheckBox(label)
            check.setChecked(bool(self._initial.get(key, key != "append_dps_label")))
            check.setAccessibleName(label + " in EQ summary")
            check.setToolTip(tooltip)
            eq_checks_layout.addWidget(check, index // 3, index % 3)
            self.eq_checks[key] = check
        eq_form.addRow("Fields", eq_checks)
        layout.addWidget(eq_group)

        detail_group = QGroupBox("Detailed plain text")
        detail_layout = QHBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 7, 8, 7)
        detail_layout.setSpacing(8)
        self.plain_checks = {}
        for key, label, tooltip in (
                ("plain_show_type", "Damage by type",
                 "Add per-player slash, spell, kick, and other damage totals"),
                ("plain_show_crit", "Critical hits",
                 "Add accurate critical and normal hit counts"),
                ("plain_show_accuracy", "Hits and accuracy",
                 "Add attempts, hits, misses, defended attempts, and accuracy")):
            check = QCheckBox(label)
            check.setChecked(bool(self._initial.get(key, False)))
            check.setAccessibleName(label + " in detailed text")
            check.setToolTip(tooltip)
            detail_layout.addWidget(check)
            self.plain_checks[key] = check
        detail_layout.addStretch(1)
        layout.addWidget(detail_group)

        html_group = QGroupBox("HTML report")
        html_form = QFormLayout(html_group)
        html_form.setContentsMargins(8, 7, 8, 7)
        html_form.setSpacing(5)
        self.html_font = QComboBox()
        for label, value in (("Small", "small"), ("Medium", "medium"),
                             ("Large", "large")):
            self.html_font.addItem(label, value)
        self.html_font.setCurrentIndex(max(
            0, self.html_font.findData(
                self._initial.get("html_font_size", "small"))))
        self.html_font.setAccessibleName("HTML report font size")
        self.html_font.setToolTip(
            "Choose a compact, medium, or large font for saved and copied HTML")
        html_form.addRow("Font size", self.html_font)
        self.html_theme = QComboBox()
        for label, value in (("Vantage dark", "dark"),
                             ("Neutral light", "neutral"),
                             ("Slate dark", "slate")):
            self.html_theme.addItem(label, value)
        self.html_theme.setCurrentIndex(max(
            0, self.html_theme.findData(
                self._initial.get("html_theme", "dark"))))
        self.html_theme.setAccessibleName("HTML report color theme")
        self.html_theme.setToolTip(
            "Choose table, background, border, and text colors for the standalone report")
        html_form.addRow("Colors", self.html_theme)
        self.html_truncate = QCheckBox("Limit each section to the top 40 rows")
        self.html_truncate.setChecked(bool(
            self._initial.get("html_truncate", False)))
        self.html_truncate.setAccessibleName("Truncate HTML report")
        self.html_truncate.setToolTip(
            "Keep forum-sized reports compact by retaining at most 40 rows per table")
        html_form.addRow("Forum limit", self.html_truncate)
        layout.addWidget(html_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.setAccessibleName("Save or cancel combat output options")
        buttons.setToolTip("Save these output settings or close without changing them")
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setAccessibleName("Save combat output options")
        save_button.setToolTip("Save every EQ, text, and HTML output option")
        cancel_button.setAccessibleName("Cancel combat output options")
        cancel_button.setToolTip("Discard changes and close this dialog")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        value = dict(self._initial)
        value.update({
            "output_channel": self.output_channel.text().strip()[:40],
            "separator": (self.separator.text() or " | ")[:20],
            "top_players": int(self.top_players.currentData() or 0),
            "html_font_size": str(self.html_font.currentData()),
            "html_theme": str(self.html_theme.currentData()),
            "html_truncate": self.html_truncate.isChecked(),
        })
        value.update({key: check.isChecked()
                      for key, check in self.eq_checks.items()})
        value.update({key: check.isChecked()
                      for key, check in self.plain_checks.items()})
        return value


class Combat(ParserWindow):
    TABS = (
        "Overview", "Player DPS", "Damage Breakdown", "Tanking",
        "Tanking Details", "Hit Distribution", "Charts", "Threat", "Spells", "Direct Damage",
        "Damage over Time", "Damage Mods", "Timeline", "Healing",
        "Healer Breakdown", "Fights", "Pets", "Loot", "Randoms",
        "Faction", "Chat", "Log Search")

    def __init__(self):
        self.name = "combat"
        super().__init__()
        self.setWindowTitle("Combat Parser")
        self._tracker = CombatTracker(
            config.data["combat"]["encounter_timeout"],
            config.data["combat"]["history_limit"],
            config.data["combat"].get("pet_links", {}))
        self._tracker.set_diagnostics_enabled(
            config.data["combat"].get("parser_diagnostics_enabled", False))
        self._diagnostics_dialog = None
        self._chat_archive = ChatArchive()
        for values in self._chat_archive.recent(self._tracker.chat.maxlen):
            self._tracker.chat.append(ChatEvent(*values))
        self._chat_archive_total = self._chat_archive.count()
        QApplication.instance().aboutToQuit.connect(self._chat_archive.close)
        self._activity_archive = ActivityArchive()
        for values in reversed(self._activity_archive.recent_loot(
                self._tracker.loot.maxlen)):
            self._tracker.loot.appendleft(LootEvent(*values))
        for values in reversed(self._activity_archive.recent_coins(
                self._tracker.coins.maxlen)):
            self._tracker.coins.appendleft(CoinEvent(*values))
        for values in reversed(self._activity_archive.recent_faction(
                self._tracker.faction.maxlen)):
            timestamp, faction, change, zone, delta, character, server = values
            self._tracker.faction.appendleft(FactionEvent(
                timestamp, faction, change, zone, delta, character, server))
        QApplication.instance().aboutToQuit.connect(self._activity_archive.close)
        self._threat = ThreatEstimator(
            config.data["combat"].get("threat", {}),
            config.data["combat"]["history_limit"])
        self._history_signature = None
        self._activity_signature = None
        self._chart_signature = None
        self._pet_revision = -1
        self._search_thread = None
        self._search_worker = None
        self._random_breaks = set()
        self._chat_clear_after = datetime.datetime.now()
        self._chat_channel_signature = None
        self._chat_profile_signature = None
        self._chat_visible_events = []
        self._spell_signature = None
        self._context_revision = None

        self.mode = QComboBox()
        for label, value in (
                ("Current", "current"), ("Last", "last"),
                ("Selected", "selected"), ("Session", "session")):
            self.mode.addItem(label, value)
        self.mode.setAccessibleName("Combat scope")
        self.mode.setToolTip(
            "Choose the active fight, last completed fight, selected history, or session")
        self.mode.currentIndexChanged.connect(self.refresh)
        self.menu_area.addWidget(self.mode)

        self.live_overlay = QToolButton()
        self.live_overlay.setObjectName("CompactMenuButton")
        self.live_overlay.setIcon(game_icon("combat"))
        self.live_overlay.setCheckable(True)
        self.live_overlay.setChecked(
            config.data["combat"].get("live_overlay_enabled", False))
        self.live_overlay.setAccessibleName("Live combat overlay")
        self.live_overlay.setToolTip(
            "Click to toggle the live DPS overlay; use the arrow to choose its overlay and row count")
        self.live_overlay.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.live_overlay_menu = QMenu(self.live_overlay)
        self.live_overlay_menu.setToolTipsVisible(True)
        self.live_overlay_menu.aboutToShow.connect(
            self._rebuild_live_overlay_menu)
        self.live_overlay.setMenu(self.live_overlay_menu)
        self.live_overlay.clicked.connect(self._live_overlay_toggled)
        self.menu_area.addWidget(self.live_overlay)

        self.export = QToolButton()
        self.export.setObjectName("CompactMenuButton")
        self.export.setIcon(game_icon("copy"))
        self.export.setAccessibleName("Copy or export combat data")
        self.export.setToolTip(
            "Click to copy this table; use the arrow to export CSV or session JSON")
        self.export.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.export.clicked.connect(self._copy_current_view)
        self.export_menu = QMenu(self.export)
        self.export_menu.setToolTipsVisible(True)
        self._build_export_menu()
        self.export.setMenu(self.export_menu)
        self.menu_area.addWidget(self.export)

        clear = QPushButton()
        clear.setIcon(game_icon("delete"))
        clear.setAccessibleName("Clear combat session")
        clear.setToolTip("Clear active and completed parsed fights")
        clear.setObjectName("DangerAction")
        clear.clicked.connect(self._clear)
        self.menu_area.addWidget(clear)

        summary = QWidget()
        summary.setObjectName("CombatSummary")
        self.summary_panel = summary
        self._summary_layout = QGridLayout(summary)
        self._summary_layout.setContentsMargins(7, 5, 7, 5)
        self._summary_layout.setSpacing(4)
        self.target = QLabel("Waiting for combat")
        self.target.setObjectName("CombatTarget")
        self.target.setWordWrap(True)
        self.total = QLabel("0 damage")
        self.total.setObjectName("CombatMetric")
        self.dps = QLabel("0 DPS")
        self.dps.setObjectName("CombatDps")
        self.duration = QLabel("0:00")
        self.duration.setObjectName("CombatMetric")
        self.content.addWidget(summary)
        self._layout_summary()

        self.tabs = QTabWidget()
        self.tabs.setObjectName("CombatTabs")
        self.tabs.setAccessibleName("Combat analysis views")
        self.tabs.setToolTip(
            "Switch between damage, tanking, spells, fights, activity, and log search")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tables = {}
        self.tables["Overview"] = self._make_table((
            "Damage By", "Total", "% of Tot", "Time", "DPS", "SDPS",
            "Hits", "Max Hit", "Avg Hit", "Dmg to PC", "NPC Max",
            "Specials", "Class", "Rank"))
        self.tables["Overview"].setItemDelegateForColumn(
            2, PercentBarDelegate(self.tables["Overview"]))
        self.tables["Overview"].setToolTip(
            "Complete damage overview; select a row for exact values")
        self._set_header_tooltips(self.tables["Overview"], (
            "Attacker; linked pets can be merged into their owner",
            "Total outgoing damage observed in the local log",
            "Share of all outgoing damage in this encounter",
            "Inclusive seconds from this attacker's first to last attempt",
            "Damage divided by the attacker's active Time",
            "Scaled DPS: damage divided by the full encounter duration",
            "Successful damaging hits", "Largest outgoing hit",
            "Outgoing damage divided by successful hits",
            "Incoming damage observed against this player or linked pet",
            "Largest incoming melee hit observed for this player or pet",
            "P99 special codes only when the matching cast is visible",
            "Class inferred only from unambiguous P99 spell data",
            "Damage rank; Total uses rank 0"))
        self.tables["Player DPS"] = self._make_table((
            "Player", "Damage", "DPS", "SDPS", "Time", "Hits",
            "Attempts", "Accuracy", "Min", "Max", "Avg"))
        self._set_header_tooltips(self.tables["Player DPS"], (
            "Attacker; linked pets can be merged into their owner",
            "Total outgoing damage", "Damage divided by active Time",
            "Damage divided by the full encounter duration",
            "Inclusive seconds from first to last attack attempt",
            "Successful damaging hits", "Hits plus visible misses",
            "Hits divided by attempts", "Smallest outgoing hit",
            "Largest outgoing hit", "Damage divided by hits"))
        self.tables["Damage Breakdown"] = self._make_table(
            ("Player", "Attack", "Damage", "%", "Hits", "Min", "Avg", "Max"))
        self.tables["Tanking"] = self._make_table(
            ("Tank", "Damage In", "DTPS", "Avg Hit", "Attempts",
             "Invuln", "Miss", "Riposte", "Parry", "Dodge", "Block",
             "Defended", "Def %", "Absorbed", "Real Hits", "Accuracy",
             "Min", "Max"))
        self._set_header_tooltips(self.tables["Tanking"], (
            "Tank visible in the local log",
            "Observed incoming damage; fully absorbed attempts contribute zero damage",
            "Observed incoming damage divided by encounter duration",
            "Observed incoming damage divided by real damaging hits",
            "All visible hit, miss, defense, invulnerability, and absorption attempts",
            "Attempts rejected as INVULNERABLE",
            "Visible opponent misses after earlier defense checks",
            "Visible ripostes; included in Defended",
            "Visible parries; included in Defended",
            "Visible dodges; included in Defended",
            "Visible blocks; included in Defended",
            "Riposte + parry + dodge + block; misses remain separate",
            "Defended divided by non-invulnerable attempts",
            "Visible magical-skin or no-damage absorptions; counted as Hits but not Real Hits",
            "Hits with an observable non-zero damage amount",
            "Hits including absorbed attempts divided by hits plus misses",
            "Smallest observed real hit", "Largest observed real hit"))
        self.tables["Tanking Details"] = self._make_table((
            "Tank", "Hit Type", "Damage", "Avg Hit", "Attempts",
            "Invuln", "%I", "Missed", "%M", "Riposted", "%R",
            "Parried", "%P", "Dodged", "%D", "Blocked", "%B",
            "Defended", "%Def", "Absorbed", "%A", "Hits", "%H"))
        self._set_header_tooltips(self.tables["Tanking Details"], (
            "Tank visible in the local log", "Incoming attack type or Total",
            "Observed damage for this attack type",
            "Damage divided by real damaging hits", "All visible attempts",
            "Invulnerable count / all attempts", "Invulnerable chance rate",
            "Miss count / remaining chances", "Miss rate after invulnerability",
            "Riposte count / remaining chances", "Riposte chance rate",
            "Parry count / remaining chances", "Parry chance rate",
            "Dodge count / remaining chances", "Dodge chance rate",
            "Block count / remaining chances", "Block chance rate",
            "Riposte + parry + dodge + block / non-invulnerable attempts",
            "Overall defended rate", "Absorbed count / Hits",
            "Absorbed share of hit outcomes",
            "Real damaging hits / all hit outcomes, matching the source breakdown grid",
            "Real-hit share after defenses, misses, and absorption"))
        self.tables["Hit Distribution"] = self._make_table(
            ("Tank", "Hit Type", "Result", "Count", "Attempts", "%"))
        self._set_header_tooltips(self.tables["Hit Distribution"], (
            "Tank visible in the local log", "Incoming attack type or Total",
            "Attempts, each defense outcome, Real Hits, or an observed hit amount",
            "Number of matching results", "Eligible attempts for this result",
            "Count divided by the displayed eligible attempts"))
        self.tables["Threat"] = self._make_table(
            ("Target", "Threat", "TPM", "Flux", "MH", "OH",
             "Proc", "Skill", "Spell", "State"))
        self.tables["Spells"] = self._make_table(
            ("Caster", "Class", "Casts", "Fizzles", "Interrupts",
             "Resists", "Reflects", "Blocks"), extended=True)
        self._set_header_tooltips(self.tables["Spells"], (
            "Caster visible in the log",
            "Class inferred only from an observed spell unique to one P99 class",
            "Spell, discipline, or action casts visible during the encounter",
            "Visible failed spell or song casts",
            "Visible interrupted casts",
            "Visible resisted spells",
            "Visible reflected spells",
            "Visible spells that did not take hold or were blocked"))
        self.tables["Spell Comparison"] = self._make_table(
            ("Caster", "Spell / action", "Casts", "Fizz", "Int",
             "Resist", "Reflect", "Block"))
        self._set_header_tooltips(self.tables["Spell Comparison"], (
            "Selected caster", "Observed spell, discipline, or action",
            "Observed casts", "Fizzled spells or songs",
            "Interrupted casts", "Resisted casts", "Reflected casts",
            "Blocked spells or spells that did not take hold"))
        self.tables["Spell Comparison"].horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.tables["Spell Comparison"].horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.tables["Spell Timeline"] = self._make_table(
            ("Time", "Caster", "Spell / action", "Outcome", "Detail"))
        self.tables["Direct Damage"] = self._make_table(
            ("Spell", "Damage", "% spell", "Hits", "Average", "Maximum"))
        self.tables["Damage over Time"] = self._make_table(
            ("Spell", "Damage", "% spell", "Ticks", "Average", "Maximum"))
        self.tables["Damage Mods"] = self._make_table(
            ("Player", "Attack", "Critical", "Reported", "Actual",
             "Modifier", "Samples"))
        self._set_header_tooltips(self.tables["Damage Mods"], (
            "Attacker whose critical report and damage line were both visible",
            "Weapon or melee attack type",
            "Critical, Crippling, Finishing, or Deadly report type",
            "Average amount printed in the separate critical report",
            "Average amount on the matching damage line",
            "Actual versus reported damage; positive is a bonus and negative is a penalty",
            "Number of safely matched report-and-hit pairs"))
        self.tables["Timeline"] = self._make_table(
            ("Time", "Event", "Actor", "Target", "Amount", "Detail"))
        self.tables["Healing"] = self._make_table((
            "Healer", "Observed", "Full", "Overheal", "AHPS", "FHPS",
            "Heals", "Average", "Maximum", "Most healed"))
        self._set_header_tooltips(self.tables["Healing"], (
            "Healer visible in this P99 log",
            "Healing amount observed in the log",
            "Full healing is unavailable because P99 logs do not expose target HP",
            "Overheal is unavailable because P99 logs do not expose target HP",
            "Observed healing divided by encounter duration",
            "Full HPS is unavailable without target HP and overheal data",
            "Number of observed heals", "Average observed heal",
            "Largest observed heal", "Target receiving the most observed healing"))
        self.tables["Healer Breakdown"] = self._make_table(
            ("Healer", "Target", "Healing", "Heals", "Avg", "Max"))
        self.tables["Fights"] = self._make_table(
            ("Target", "Started", "Duration", "Zone", "Players",
             "Your DPS", "Damage", "DPS", "Result"),
            extended=True)
        self.tables["Pets"] = self._make_table(
            ("Pet", "Owner", "Source"), extended=True)
        self.tables["Loot"] = self._make_table(
            ("Time", "Looter", "Item", "Qty", "NPC", "Zone", "Profile"))
        self._set_header_tooltips(self.tables["Loot"], (
            "Time the loot line was written", "Character receiving the item",
            "Item name exactly as printed by EverQuest",
            "Quantity reported by the loot line",
            "Corpse or source when the log includes it",
            "Zone active when the loot was recorded",
            "Character and server log that produced the event"))
        self.tables["Coin"] = self._make_table(
            ("Time", "Amount", "Copper", "Source", "Zone", "Profile"))
        self._set_header_tooltips(self.tables["Coin"], (
            "Time the coin line was written",
            "Denominations exactly as printed by EverQuest",
            "Normalized total in copper for accurate summing",
            "Corpse, group split, vendor, or item sale",
            "Zone active when the coin was recorded",
            "Character and server log that produced the event"))
        self.tables["Randoms"] = self._make_table(
            ("Time", "Player", "Range", "Roll"))
        self.tables["Roll Sets"] = self._make_table((
            "Started", "Range", "Rolls", "Players", "Duplicates",
            "Winner", "Winning roll"))
        self.tables["Faction"] = self._make_table(
            ("Time", "Faction", "Change", "Zone", "Profile"))
        self._set_header_tooltips(self.tables["Faction"], (
            "Time the faction line was written", "Faction named by EverQuest",
            "Numeric adjustment, direction, or capped state",
            "Zone active when the faction change was recorded",
            "Character and server log that produced the event"))
        self.tables["Chat"] = self._make_table(
            ("Time", "Channel", "Speaker", "Message"))
        self.tables["Log Search"] = self._make_table(
            ("File", "Line", "Matching log line"))

        for label in self.TABS:
            if label in ("Healing", "Healer Breakdown"):
                host = QWidget()
                layout = QVBoxLayout(host)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(2)
                note = QLabel(
                    "P99 LOG LIMIT · observed healing is complete only for heals "
                    "done by you or received by you; unavailable fields show —")
                note.setObjectName("CombatDataNotice")
                note.setWordWrap(True)
                note.setToolTip(
                    "Classic EverQuest logs cannot see every heal between other raid members")
                layout.addWidget(note)
                layout.addWidget(self.tables[label], 1)
                self.tabs.addTab(host, label)
            elif label == "Log Search":
                self.tabs.addTab(self._build_log_search(), label)
            elif label == "Chat":
                self.tabs.addTab(self._build_chat(), label)
            elif label == "Threat":
                self.tabs.addTab(self._build_threat(), label)
            elif label == "Pets":
                self.tabs.addTab(self._build_pets(), label)
            elif label == "Fights":
                self.tabs.addTab(self._build_fights(), label)
            elif label == "Charts":
                self.tabs.addTab(self._build_charts(), label)
            elif label == "Randoms":
                self.tabs.addTab(self._build_randoms(), label)
            elif label == "Loot":
                self.tabs.addTab(self._build_loot(), label)
            elif label == "Faction":
                self.tabs.addTab(self._build_faction(), label)
            elif label == "Spells":
                self.tabs.addTab(self._build_spells(), label)
            else:
                self.tabs.addTab(self.tables[label], label)
        ensure_tab_tooltips(self.tabs, {
            "Overview": "Compare the complete damage summary",
            "Player DPS": "Inspect outgoing damage and accuracy by attacker",
            "Damage Breakdown": "Break one player's damage down by attack type",
            "Tanking": "Compare incoming damage and defensive outcomes by tank",
            "Tanking Details": "Inspect sequential defense chances by attack type",
            "Hit Distribution": "Inspect incoming hit amounts and outcome frequencies",
            "Charts": "Plot native damage, DPS, healing, or tanking graphs",
            "Threat": "View the local log-observable threat estimate",
            "Spells": "Compare caster totals, spell outcomes, and cast timing",
            "Direct Damage": "Break direct spell damage down by spell",
            "Damage over Time": "Break damage-over-time ticks down by spell",
            "Damage Mods": "Inspect safely matched critical reports and actual hits",
            "Timeline": "Read combat events in chronological order",
            "Healing": "Compare healing values observable in the P99 log",
            "Healer Breakdown": "Break observed healing down by healer and target",
            "Fights": "Select, combine, rename, or export completed encounters",
            "Pets": "Review and edit pet-to-owner links",
            "Loot": "Search persistent item and coin history",
            "Randoms": "Resolve /random sets, duplicates, ties, and winners",
            "Faction": "Search persistent faction-change history",
            "Chat": "Browse and search local chat channels and tells",
            "Log Search": "Search linked EQ logs without modifying them",
        })
        self.content.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._combat_tab_changed)
        QTimer.singleShot(0, self._polish_tab_scrollers)
        self._combat_tab_changed(self.tabs.currentIndex())

        fights = self.tables["Fights"]
        fights.itemSelectionChanged.connect(self._fight_selection_changed)
        fights.cellDoubleClicked.connect(self._open_selected_fights)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def _polish_tab_scrollers(self):
        buttons = self.tabs.tabBar().findChildren(QToolButton)
        for index, button in enumerate(buttons):
            label = "Previous combat tab" if index == 0 else "Next combat tab"
            button.setAccessibleName(label)
            button.setToolTip(label)

    def _combat_tab_changed(self, index):
        label = self.tabs.tabText(index) if index >= 0 else ""
        self.summary_panel.setVisible(label not in {
            "Pets", "Loot", "Randoms", "Faction", "Chat", "Log Search"})
        if label == "Chat":
            self._refresh_chat_view(rebuild_channels=True)

    def _live_overlay_toggled(self, enabled):
        self._overlay_enabled_toggled("damage", enabled)

    def _rebuild_live_overlay_menu(self):
        self.live_overlay_menu.clear()
        manager = QApplication.instance()._notification_overlay
        for label, kind, key in (
                ("Live damage / DPS", "damage", "live_overlay_enabled"),
                ("Secondary DPS", "secondary", "secondary_overlay_enabled"),
                ("Live tanking", "tanking", "tanking_overlay_enabled")):
            action = self.live_overlay_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(config.data["combat"].get(key, False))
            action.setToolTip(
                f"Show or hide the independent {label.casefold()} overlay")
            action.triggered.connect(
                lambda checked=False, value=kind:
                self._overlay_enabled_toggled(value, checked))

        self.live_overlay_menu.addSeparator()
        for label, kind, key in (
                ("Damage destination", "damage", "live_overlay_id"),
                ("Secondary destination", "secondary", "secondary_overlay_id"),
                ("Tanking destination", "tanking", "tanking_overlay_id")):
            route_menu = self.live_overlay_menu.addMenu(label)
            route_menu.setToolTipsVisible(True)
            selected = config.data["combat"].get(key, "alerts")
            for overlay_id, settings in manager.definitions().items():
                if not settings.get("enabled", True):
                    continue
                action = route_menu.addAction(
                    settings.get("label") or overlay_id)
                action.setCheckable(True)
                action.setChecked(overlay_id == selected)
                action.setToolTip(
                    f"Route {kind} summaries to this movable overlay")
                action.triggered.connect(
                    lambda _checked=False, overlay_kind=kind,
                    value=overlay_id:
                    self._select_combat_overlay(overlay_kind, value))

        rows_root = self.live_overlay_menu.addMenu("Visible rows")
        rows_root.setToolTipsVisible(True)
        for label, kind, key, default in (
                ("Damage", "damage", "live_overlay_rows", 6),
                ("Secondary DPS", "secondary", "secondary_overlay_rows", 3),
                ("Tanking", "tanking", "tanking_overlay_rows", 5)):
            rows_menu = rows_root.addMenu(label)
            rows_menu.setToolTipsVisible(True)
            current_rows = config.data["combat"].get(key, default)
            for count in (3, 5, 6, 8, 10, 12):
                action = rows_menu.addAction(str(count))
                action.setCheckable(True)
                action.setChecked(count == current_rows)
                action.setToolTip(
                    f"Show the top {count} {kind} rows")
                action.triggered.connect(
                    lambda _checked=False, overlay_kind=kind, value=count:
                    self._select_combat_overlay_rows(overlay_kind, value))
        self.live_overlay_menu.addSeparator()
        manage = self.live_overlay_menu.addAction("Manage overlays…")
        manage.setToolTip("Create, arrange, style, disable, or delete overlays")
        manage.triggered.connect(
            lambda: QApplication.instance().manage_notification_overlays(self))

    def _overlay_enabled_toggled(self, kind, enabled):
        key = {
            "tanking": "tanking_overlay_enabled",
            "secondary": "secondary_overlay_enabled",
        }.get(kind, "live_overlay_enabled")
        config.data["combat"][key] = bool(enabled)
        if kind == "damage":
            self.live_overlay.setChecked(bool(enabled))
        if not enabled:
            prefix = {
                "tanking": "combat-tanking",
                "secondary": "combat-secondary",
            }.get(kind, "combat")
            QApplication.instance().dismiss_overlay_timer(f"{prefix}-live")
            QApplication.instance().dismiss_overlay_timer(
                f"{prefix}-completed")
        config.save()
        self.refresh()

    def _select_live_overlay(self, overlay_id):
        self._select_combat_overlay("damage", overlay_id)

    def _select_live_overlay_rows(self, count):
        self._select_combat_overlay_rows("damage", count)

    def _select_combat_overlay(self, kind, overlay_id):
        key = {
            "tanking": "tanking_overlay_id",
            "secondary": "secondary_overlay_id",
        }.get(kind, "live_overlay_id")
        config.data["combat"][key] = str(overlay_id)
        config.save()
        self._refresh_live_combat_overlay()

    def _select_combat_overlay_rows(self, kind, count):
        key = {
            "tanking": "tanking_overlay_rows",
            "secondary": "secondary_overlay_rows",
        }.get(kind, "live_overlay_rows")
        config.data["combat"][key] = int(count)
        config.save()
        self._refresh_live_combat_overlay()

    def _show_combat_overlay(self, encounter, completed=False):
        if not encounter or not config.data["combat"].get(
                "live_overlay_enabled", False):
            return
        attackers = sorted(
            self._tracker.display_attackers(
                encounter, config.data["combat"].get("merge_pets", True)),
            key=lambda value: value.damage, reverse=True)
        limit = config.data["combat"].get("live_overlay_rows", 6)
        total = max(1, encounter.total_damage)
        duration = max(1.0, encounter.duration)
        rows = [
            f"{index}. {stats.name}  {stats.damage:,}  "
            f"{stats.damage / duration:,.1f} DPS  "
            f"{stats.damage / total * 100:.1f}%"
            for index, stats in enumerate(attackers[:limit], 1)]
        if not rows:
            rows = ["No outgoing damage visible in this log"]
        title = (
            f"COMPLETED · {encounter.target}" if completed else
            f"LIVE · {encounter.target}")
        QApplication.instance().show_overlay_notification(
            title, "\n".join(rows),
            msecs=8500 if completed else 2400,
            overlay_id=config.data["combat"].get(
                "live_overlay_id", "alerts"),
            timer_key="combat-completed" if completed else "combat-live")

    def _show_tanking_overlay(self, encounter, completed=False):
        if not encounter or not config.data["combat"].get(
                "tanking_overlay_enabled", False):
            return
        tanks = sorted(
            encounter.tanks.values(),
            key=lambda value: value.damage, reverse=True)
        limit = config.data["combat"].get("tanking_overlay_rows", 5)
        duration = max(1.0, encounter.duration)
        rows = []
        for index, stats in enumerate(tanks[:limit], 1):
            rows.append(
                f"{index}. {stats.name}  {stats.damage:,}  "
                f"{stats.damage / duration:,.1f} DTPS  "
                f"{stats.defended_percent:.1f}% defended  "
                f"{stats.accuracy:.1f}% hit")
        if not rows:
            rows = ["No incoming damage visible in this log"]
        title = (
            f"TANKING COMPLETE · {encounter.target}" if completed else
            f"LIVE TANKING · {encounter.target}")
        QApplication.instance().show_overlay_notification(
            title, "\n".join(rows),
            msecs=8500 if completed else 2400,
            overlay_id=config.data["combat"].get(
                "tanking_overlay_id", "alerts"),
            timer_key=(
                "combat-tanking-completed" if completed else
                "combat-tanking-live"))

    def _show_secondary_dps_overlay(self, encounter):
        if not encounter or not config.data['combat'].get(
                'secondary_overlay_enabled', False):
            return
        attackers = sorted(
            self._tracker.display_attackers(
                encounter, config.data['combat'].get('merge_pets', True)),
            key=lambda value: value.damage, reverse=True)
        limit = config.data['combat'].get('secondary_overlay_rows', 3)
        total = max(1, encounter.total_damage)
        duration = max(1.0, encounter.duration)
        rows = [
            f"{index}. {stats.name}  {stats.damage / duration:,.1f} DPS  "
            f"{stats.damage / total * 100:.1f}%"
            for index, stats in enumerate(attackers[:limit], 1)]
        if not rows:
            rows = ['No outgoing damage visible in this log']
        QApplication.instance().show_overlay_notification(
            f'SECONDARY DPS · {encounter.target}', '\n'.join(rows),
            msecs=2400,
            overlay_id=config.data['combat'].get(
                'secondary_overlay_id', 'alerts'),
            timer_key='combat-secondary-live')

    def _refresh_live_combat_overlay(self):
        encounter = self._tracker.current()
        if encounter:
            self._show_combat_overlay(encounter)
            self._show_secondary_dps_overlay(encounter)
            self._show_tanking_overlay(encounter)
        else:
            QApplication.instance().dismiss_overlay_timer("combat-live")
            QApplication.instance().dismiss_overlay_timer(
                "combat-tanking-live")
            QApplication.instance().dismiss_overlay_timer(
                'combat-secondary-live')

    def _make_table(self, headers, extended=False):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        ensure_table_header_tooltips(table, "the combat")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection if extended else
            QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(headers)):
            table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        table.setAccessibleName(f"Combat {headers[0]} table")
        table.setToolTip("Select a row for details; headers describe each parsed metric")
        return table

    def _build_spells(self):
        """GamParse-style caster overview, comparison, and cast timeline."""
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        notice = QLabel(
            "P99 LOG LIMIT · caster, spell and outcome are shown only when "
            "the local log exposes them; class requires a unique P99 spell")
        notice.setObjectName("CombatDataNotice")
        notice.setWordWrap(True)
        notice.setAccessibleName("P99 spell visibility limitation")
        notice.setToolTip(
            "Select one or more casters in Overview; Comparison and By Time "
            "will use exactly that selection")
        layout.addWidget(notice)

        self.spell_tabs = QTabWidget()
        self.spell_tabs.setObjectName("SpellAnalysisTabs")
        self.spell_tabs.setDocumentMode(True)
        self.spell_tabs.setAccessibleName("Spell caster analysis views")
        self.spell_tabs.setToolTip(
            "Switch between caster totals, selected-caster comparison, and casts by time")
        for label, key, tooltip in (
                ("Overview", "Spells",
                 "Select casters and compare total casts and failed outcomes"),
                ("Comparison", "Spell Comparison",
                 "Compare spells and outcomes for the casters selected in Overview"),
                ("By Time", "Spell Timeline",
                 "Inspect each selected caster's spells in chronological order")):
            index = self.spell_tabs.addTab(self.tables[key], label)
            self.spell_tabs.setTabToolTip(index, tooltip)
        layout.addWidget(self.spell_tabs, 1)
        self.tables["Spells"].itemSelectionChanged.connect(
            self._refresh_spell_details)
        return host

    @staticmethod
    def _set_header_tooltips(table, tooltips):
        for column, tooltip in enumerate(tooltips):
            item = table.horizontalHeaderItem(column)
            if item:
                item.setToolTip(str(tooltip))

    def _build_charts(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)

        self.chart_mode = QComboBox()
        for label, value in CHART_MODES:
            self.chart_mode.addItem(label, value)
        self.chart_mode.setAccessibleName("Combat chart type")
        self.chart_mode.setToolTip(
            "Choose damage, DPS, healing, or tanking chart data")
        self.chart_mode.currentIndexChanged.connect(
            lambda *_: self._refresh_chart())
        controls.addWidget(self.chart_mode)

        self.chart_actor = QComboBox()
        self.chart_actor.setAccessibleName("Chart player or tank")
        self.chart_actor.setToolTip(
            "Show the total or one visible player, healer, or tank")
        self.chart_actor.currentIndexChanged.connect(
            lambda *_: self._refresh_chart())
        controls.addWidget(self.chart_actor, 1)

        self.chart_export = QToolButton()
        self.chart_export.setObjectName("CompactMenuButton")
        self.chart_export.setIcon(game_icon("copy"))
        self.chart_export.setAccessibleName("Copy or save combat chart")
        self.chart_export.setToolTip(
            "Click to copy the chart image; use the arrow to save a PNG")
        self.chart_export.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.chart_export.clicked.connect(self._copy_chart)
        export_menu = QMenu(self.chart_export)
        export_menu.setToolTipsVisible(True)
        copy_action = export_menu.addAction("Copy chart image")
        copy_action.setToolTip("Copy the rendered chart to the clipboard")
        copy_action.triggered.connect(self._copy_chart)
        png_action = export_menu.addAction("Save chart as PNG…")
        png_action.setToolTip("Choose a PNG file for the rendered chart")
        png_action.triggered.connect(self._export_chart_png)
        self.chart_export.setMenu(export_menu)
        controls.addWidget(self.chart_export)
        layout.addLayout(controls)

        self.chart_notice = QLabel(
            "1-SECOND BINS · rolling lines use a 6-second window · "
            "healing is limited to log-observable events")
        self.chart_notice.setObjectName("CombatDataNotice")
        self.chart_notice.setWordWrap(True)
        self.chart_notice.setToolTip(
            "P99 cannot expose complete healing between other players; "
            "the chart never estimates missing or overheal values")
        layout.addWidget(self.chart_notice)
        self.chart_canvas = CombatChartWidget()
        layout.addWidget(self.chart_canvas, 1)
        return host

    def _chart_actor_names(self, encounter, mode):
        if not encounter or mode in ("damage_total", "active_dps"):
            return ["Total"]
        if mode == "damage_timeline":
            values = encounter.attackers
        elif mode == "healing_timeline":
            values = encounter.healers
        else:
            values = encounter.tanks
        return ["Total", *sorted(values, key=str.casefold)]

    def _refresh_chart(self, encounter=None):
        if not hasattr(self, "chart_canvas"):
            return
        if encounter is None or not hasattr(encounter, "events"):
            encounter = self._scope()
        mode = self.chart_mode.currentData() or "damage_timeline"
        actor_names = self._chart_actor_names(encounter, mode)
        previous = self.chart_actor.currentText() or "Total"
        current_names = [
            self.chart_actor.itemText(index)
            for index in range(self.chart_actor.count())]
        if current_names != actor_names:
            self.chart_actor.blockSignals(True)
            self.chart_actor.clear()
            self.chart_actor.addItems(actor_names)
            index = self.chart_actor.findText(previous)
            self.chart_actor.setCurrentIndex(max(0, index))
            self.chart_actor.blockSignals(False)
        actor_enabled = mode not in ("damage_total", "active_dps")
        self.chart_actor.setEnabled(actor_enabled)
        actor = self.chart_actor.currentText() or "Total"
        signature = (
            id(encounter), getattr(encounter, "last_at", None),
            getattr(encounter, "total_damage", 0),
            getattr(encounter, "total_healing", 0),
            len(getattr(encounter, "events", ())), mode, actor)
        if signature == self._chart_signature:
            return
        self.chart_canvas.set_data(build_chart_data(encounter, mode, actor))
        self._chart_signature = signature

    def _copy_chart(self):
        QApplication.clipboard().setPixmap(self.chart_canvas.grab())
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", "Copied combat chart image", msecs=2200)

    def _export_chart_png(self):
        suggested = f"Vantage-Combat-Chart-{datetime.datetime.now():%Y%m%d-%H%M}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Combat Chart", suggested,
            "PNG image (*.png);;All Files (*)")
        if not path:
            return
        if not path.casefold().endswith(".png"):
            path += ".png"
        if not self.chart_canvas.grab().save(path, "PNG"):
            QMessageBox.warning(
                self, "Chart Export Failed", "Vantage could not save that PNG file.")
            return
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Saved chart · {Path(path).name}", msecs=2500)

    def _build_chat(self):
        """Build the compact channel browser used by the original parser flow."""
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        filters = QHBoxLayout()
        filters.setContentsMargins(3, 3, 3, 0)
        filters.setSpacing(3)
        self.chat_search = QLineEdit()
        self.chat_search.setPlaceholderText(
            "Search speaker, message, or channel")
        self.chat_search.setClearButtonEnabled(True)
        self.chat_search.setAccessibleName("Search captured chat")
        self.chat_search.setToolTip(
            "Filter the currently captured chat by speaker, message text, or channel")
        for button in self.chat_search.findChildren(QToolButton):
            button.setAccessibleName("Clear chat search")
            button.setToolTip("Clear the chat search text")
        self.chat_search.textChanged.connect(self._chat_filter_changed)
        filters.addWidget(self.chat_search, 1)

        self.chat_profile = QComboBox()
        self.chat_profile.addItem("All profiles", "*")
        self.chat_profile.setAccessibleName("Filter chat by log profile")
        self.chat_profile.setToolTip(
            "Show messages from every monitored log or one character and server")
        self.chat_profile.currentIndexChanged.connect(
            self._chat_profile_changed)
        filters.addWidget(self.chat_profile)

        self.chat_time = QComboBox()
        for label, value in (
                ("All history", "all"), ("New since clear", "clear"),
                ("Last 15 min", 15 * 60), ("Last 30 min", 30 * 60),
                ("Last hour", 60 * 60), ("Last 2 hours", 2 * 60 * 60),
                ("Last 4 hours", 4 * 60 * 60),
                ("Last 8 hours", 8 * 60 * 60),
                ("Last 24 hours", 24 * 60 * 60)):
            self.chat_time.addItem(label, value)
        saved_range = config.data["combat"].get("chat_time_filter", "all")
        saved_index = self.chat_time.findData(saved_range)
        if saved_index < 0:
            try:
                saved_index = self.chat_time.findData(int(saved_range))
            except (TypeError, ValueError):
                saved_index = 0
        self.chat_time.setCurrentIndex(max(0, saved_index))
        self.chat_time.setAccessibleName("Restrict chat by time")
        self.chat_time.setToolTip(
            "Show all captured chat, only messages after Clear View, or a recent time range")
        self.chat_time.currentIndexChanged.connect(self._chat_time_changed)
        filters.addWidget(self.chat_time)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        actions.setContentsMargins(3, 0, 3, 0)
        actions.setSpacing(3)
        self.chat_summary = QLabel("0 captured messages")
        self.chat_summary.setObjectName("CombatDataNotice")
        self.chat_summary.setAccessibleName("Visible chat result count")
        self.chat_summary.setToolTip(
            "Shows how many messages remain after channel, time, and text filters")
        actions.addWidget(self.chat_summary, 1)
        for text, icon, accessible, tooltip, callback in (
                ("Clear View", "delete", "Clear visible chat history",
                 "Hide existing messages without deleting the captured session; new chat remains visible",
                 self._clear_chat_view),
                ("Copy", "copy", "Copy selected chat",
                 "Copy selected message rows, or every visible row when none is selected",
                 self._copy_chat_rows),
                ("Copy Link", "search", "Copy web link from chat",
                 "Copy the first web link found in the selected or visible messages",
                 self._copy_chat_link),
                ("Save", "export", "Save visible chat results",
                 "Save every currently visible chat result to a UTF-8 text file",
                 self._save_chat_results)):
            button = QToolButton()
            button.setObjectName("ToolbarAction")
            button.setText(text)
            button.setIcon(game_icon(icon))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setAccessibleName(accessible)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setAccessibleName("Chat channels and results divider")
        splitter.setToolTip(
            "Drag the divider to change the width of the channel list and chat results")
        self.chat_splitter = splitter

        self.chat_channels = QTableWidget(0, 2)
        self.chat_channels.setHorizontalHeaderLabels(("#", "Channel"))
        self.chat_channels.verticalHeader().setVisible(False)
        self.chat_channels.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.chat_channels.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.chat_channels.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.chat_channels.setAlternatingRowColors(True)
        self.chat_channels.setAccessibleName("Captured chat channels")
        self.chat_channels.setToolTip(
            "Select one or several channels or tell conversations to combine their messages")
        self.chat_channels.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.chat_channels.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._set_header_tooltips(self.chat_channels, (
            "Number of captured messages in this channel",
            "Channel or individual tell conversation; Ctrl-click to combine rows"))
        self.chat_channels.selectionModel().selectionChanged.connect(
            self._chat_selection_changed)
        splitter.addWidget(self.chat_channels)

        result_table = self.tables["Chat"]
        result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        result_table.setAccessibleName("Filtered chat results")
        result_table.setToolTip(
            "Select one or several messages to copy; double-click text to inspect the row")
        for column in range(3):
            result_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self._set_header_tooltips(result_table, (
            "EverQuest log timestamp", "Normalized chat channel or tell thread",
            "Character who sent the message", "Exact message text from the log"))
        splitter.addWidget(result_table)
        splitter.setSizes((155, 700))
        layout.addWidget(splitter, 1)
        return host

    def _chat_time_changed(self, *_):
        config.data["combat"]["chat_time_filter"] = self.chat_time.currentData()
        config.save()
        self._refresh_chat_view()

    def _chat_filter_changed(self, *_):
        self._refresh_chat_view()

    def _chat_profile_changed(self, *_):
        self._chat_channel_signature = None
        self._refresh_chat_view(rebuild_channels=True)

    def _chat_selection_changed(self, *_):
        self._refresh_chat_view()

    def _selected_chat_channels(self):
        if not hasattr(self, "chat_channels"):
            return None
        selected = set()
        for index in self.chat_channels.selectionModel().selectedRows(1):
            item = self.chat_channels.item(index.row(), 1)
            if item:
                selected.add(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if not selected or "*" in selected:
            return None
        return selected

    @staticmethod
    def _chat_profile_key(event):
        return f"{event.character}\0{event.server}"

    def _refresh_chat_profiles(self, events):
        counts = {}
        labels = {}
        for event in events:
            if not event.character and not event.server:
                continue
            key = self._chat_profile_key(event)
            counts[key] = counts.get(key, 0) + 1
            labels[key] = " · ".join(
                value for value in (event.character, event.server) if value)
        signature = tuple(sorted(counts.items()))
        if signature == self._chat_profile_signature:
            return
        selected = str(self.chat_profile.currentData() or "*")
        self.chat_profile.blockSignals(True)
        self.chat_profile.clear()
        self.chat_profile.addItem("All profiles", "*")
        for key in sorted(counts, key=lambda value: labels[value].casefold()):
            self.chat_profile.addItem(
                f"{labels[key]} · {counts[key]:,}", key)
        index = self.chat_profile.findData(selected)
        self.chat_profile.setCurrentIndex(max(0, index))
        self.chat_profile.blockSignals(False)
        self._chat_profile_signature = signature

    def _events_for_chat_profile(self, events):
        selected = str(self.chat_profile.currentData() or "*")
        if selected == "*":
            return list(events)
        return [
            event for event in events
            if self._chat_profile_key(event) == selected]

    def _refresh_chat_channels(self, events):
        counts = {}
        tell_count = 0
        for event in events:
            counts[event.channel] = counts.get(event.channel, 0) + 1
            if event.channel.casefold().startswith("tell ·"):
                tell_count += 1
        signature = tuple(sorted(counts.items(), key=lambda item: item[0].casefold()))
        if signature == self._chat_channel_signature:
            return
        selected = self._selected_chat_channels()
        selected = {"*"} if selected is None else selected
        preferred = {
            "Guild": 0, "Group": 1, "Raid": 2, "Fellowship": 3,
            "Tell": 4, "OOC": 5, "Auction": 6, "Shout": 7, "Say": 8,
        }
        channels = sorted(
            counts, key=lambda value: (
                preferred.get(value.split(" ·", 1)[0], 20), value.casefold()))
        rows = [("*", len(events), "All chat")]
        if tell_count:
            rows.append(("__tells__", tell_count, "All tells"))
        rows.extend((channel, counts[channel], channel) for channel in channels)

        self.chat_channels.blockSignals(True)
        self.chat_channels.clearSelection()
        self.chat_channels.setRowCount(len(rows))
        for row, (key, count, label) in enumerate(rows):
            count_item = QTableWidgetItem(f"{count:,}")
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count_item.setToolTip(f"{count:,} captured messages")
            channel_item = QTableWidgetItem(label)
            channel_item.setData(Qt.ItemDataRole.UserRole, key)
            channel_item.setToolTip(
                "All captured chat" if key == "*" else
                "Every individual tell conversation" if key == "__tells__" else
                f"Messages captured in {label}")
            self.chat_channels.setItem(row, 0, count_item)
            self.chat_channels.setItem(row, 1, channel_item)
            if key in selected:
                self.chat_channels.selectRow(row)
        if not self.chat_channels.selectionModel().selectedRows():
            self.chat_channels.selectRow(0)
        self.chat_channels.blockSignals(False)
        self._chat_channel_signature = signature

    def _filtered_chat_events(self):
        events = list(self._tracker.chat)
        events = self._events_for_chat_profile(events)
        selected = self._selected_chat_channels()
        search = self.chat_search.text().strip().casefold()
        time_filter = self.chat_time.currentData()
        threshold = None
        if time_filter == "clear":
            threshold = self._chat_clear_after
        elif isinstance(time_filter, int):
            threshold = datetime.datetime.now() - datetime.timedelta(
                seconds=time_filter)
        visible = []
        for event in events:
            if threshold and event.timestamp < threshold:
                continue
            if selected:
                channel_match = event.channel in selected
                tells_match = (
                    "__tells__" in selected and
                    event.channel.casefold().startswith("tell ·"))
                if not channel_match and not tells_match:
                    continue
            if search and search not in " ".join((
                    event.channel, event.speaker, event.message)).casefold():
                continue
            visible.append(event)
        return list(reversed(visible))

    def _refresh_chat_view(self, events=None, rebuild_channels=False):
        if not hasattr(self, "chat_channels"):
            return
        if events is None:
            events = list(self._tracker.chat)
        if rebuild_channels:
            self._refresh_chat_profiles(events)
            self._refresh_chat_channels(
                self._events_for_chat_profile(events))
        visible = self._filtered_chat_events()
        table = self.tables["Chat"]
        table.setSortingEnabled(False)
        table.setRowCount(len(visible))
        for row, event in enumerate(visible):
            values = (
                event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                event.channel, event.speaker, event.message)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                table.setItem(row, column, item)
        self._chat_visible_events = visible
        total = len(self._tracker.chat)
        archived = self._chat_archive_total
        archive_label = (
            f" · {archived:,} stored" if self._chat_archive.available else
            " · no archive")
        self.chat_summary.setText(
            f"{len(visible):,}/{total:,} shown{archive_label}")

    def _clear_chat_view(self):
        self._chat_clear_after = datetime.datetime.now()
        index = self.chat_time.findData("clear")
        if self.chat_time.currentIndex() == index:
            self._refresh_chat_view()
        else:
            self.chat_time.setCurrentIndex(index)
        self.chat_summary.setText(
            "View cleared · captured history remains available under All history")

    def _chat_table_rows(self, prefer_selection=True):
        table = self.tables["Chat"]
        selected_rows = sorted({item.row() for item in table.selectedItems()})
        row_numbers = (
            selected_rows if prefer_selection and selected_rows else
            list(range(table.rowCount())))
        return [[
            table.item(row, column).text() if table.item(row, column) else ""
            for column in range(table.columnCount())]
            for row in row_numbers]

    def _copy_chat_rows(self):
        rows = self._chat_table_rows(prefer_selection=True)
        if not rows:
            self.chat_summary.setText("No visible chat messages to copy")
            return
        headers = ("Time", "Channel", "Speaker", "Message")
        QApplication.clipboard().setText("\n".join(
            ["\t".join(headers)] + ["\t".join(row) for row in rows]))
        self.chat_summary.setText(f"Copied {len(rows):,} chat message(s)")
        QApplication.instance().show_overlay_notification(
            "Vantage · Chat", f"Copied {len(rows):,} chat message(s)",
            msecs=2200)

    def _copy_chat_link(self):
        rows = self._chat_table_rows(prefer_selection=True)
        for row in rows:
            match = re.search(r"https?://[^\s<>()]+", row[3], re.IGNORECASE)
            if not match:
                continue
            url = match.group(0).rstrip(".,;:!?)]}")
            QApplication.clipboard().setText(url)
            self.chat_summary.setText("Copied web link from chat")
            QApplication.instance().show_overlay_notification(
                "Vantage · Chat", "Copied web link from chat", msecs=2200)
            return
        self.chat_summary.setText("No web link found in the selected messages")

    def _save_chat_results(self):
        rows = self._chat_table_rows(prefer_selection=False)
        if not rows:
            self.chat_summary.setText("No visible chat messages to save")
            return
        suggested = f"Vantage-chat-{datetime.datetime.now():%Y%m%d-%H%M}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Chat Results", suggested,
            "Text file (*.txt);;All Files (*)")
        if not path:
            return
        try:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as output:
                output.write("Time\tChannel\tSpeaker\tMessage\n")
                for row in rows:
                    output.write("\t".join(row) + "\n")
        except OSError as error:
            QMessageBox.warning(self, "Save Chat Failed", str(error))
            return
        self.chat_summary.setText(f"Saved {len(rows):,} chat message(s)")
        QApplication.instance().show_overlay_notification(
            "Vantage · Chat", f"Saved {len(rows):,} chat message(s)",
            msecs=2400)

    @staticmethod
    def _activity_profile(event):
        character = str(getattr(event, 'character', '') or '')
        server = str(getattr(event, 'server', '') or '')
        return (
            f'{character} · {server}' if character and server else
            character or server or 'Unassigned')

    @staticmethod
    def _format_coin(copper):
        copper = max(0, int(copper or 0))
        platinum, copper = divmod(copper, 1000)
        gold, copper = divmod(copper, 100)
        silver, copper = divmod(copper, 10)
        values = []
        for value, suffix in (
                (platinum, 'p'), (gold, 'g'), (silver, 's'), (copper, 'c')):
            if value or (not values and suffix == 'c'):
                values.append(f'{value:,}{suffix}')
        return ' '.join(values) if values else '0c'

    def _activity_filters_changed(self, *_):
        self._activity_signature = None
        self._refresh_activity()

    @staticmethod
    def _sync_filter_combo(combo, entries, all_label):
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, '*')
        for label, value in entries:
            combo.addItem(label, value)
        selected = combo.findData(current)
        combo.setCurrentIndex(max(0, selected))
        combo.blockSignals(False)

    def _build_activity_filter(self, noun):
        search = QLineEdit()
        search.setPlaceholderText(f'Search {noun.casefold()}…')
        search.setClearButtonEnabled(True)
        search.setAccessibleName(f'Search {noun.casefold()} history')
        search.setToolTip(
            f'Filter {noun.casefold()} by names, source, zone, or profile')
        for button in search.findChildren(QToolButton):
            button.setAccessibleName(f'Clear {noun.casefold()} search')
            button.setToolTip(f'Clear the {noun.casefold()} search text')
        search.textChanged.connect(self._activity_filters_changed)
        profile = QComboBox()
        profile.addItem('All profiles', '*')
        profile.setAccessibleName(f'{noun} profile filter')
        profile.setToolTip(
            'Show events from every monitored character or one character/server')
        profile.currentIndexChanged.connect(self._activity_filters_changed)
        zone = QComboBox()
        zone.addItem('All zones', '*')
        zone.setAccessibleName(f'{noun} zone filter')
        zone.setToolTip('Show events from every zone or one detected zone')
        zone.currentIndexChanged.connect(self._activity_filters_changed)
        return search, profile, zone

    def _build_loot(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.loot_search, self.loot_profile, self.loot_zone = (
            self._build_activity_filter('Loot and coin'))
        controls.addWidget(self.loot_search, 1)
        controls.addWidget(self.loot_profile)
        controls.addWidget(self.loot_zone)
        layout.addLayout(controls)
        self.loot_notice = QLabel(
            'LOOT · waiting for item or coin lines from EverQuest')
        self.loot_notice.setObjectName('CombatDataNotice')
        self.loot_notice.setToolTip(
            'Coin is normalized to copper only for summing; original denominations remain visible')
        layout.addWidget(self.loot_notice)
        self.loot_tabs = QTabWidget()
        self.loot_tabs.setDocumentMode(True)
        self.loot_tabs.setAccessibleName('Loot items and coin history')
        self.loot_tabs.setToolTip(
            'Switch between item drops and normalized coin events')
        self.loot_tabs.addTab(self.tables['Loot'], 'Items')
        self.loot_tabs.addTab(self.tables['Coin'], 'Coin')
        ensure_tab_tooltips(self.loot_tabs, {
            'Items': 'Show item loot with looter, source, zone, and profile',
            'Coin': 'Show coin events with exact denominations and copper totals',
        })
        layout.addWidget(self.loot_tabs, 1)
        return host

    def _build_faction(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.faction_search, self.faction_profile, self.faction_zone = (
            self._build_activity_filter('Faction'))
        controls.addWidget(self.faction_search, 1)
        self.faction_change = QComboBox()
        for label, value in (
                ('All changes', '*'), ('Improved', 'gain'),
                ('Worsened', 'loss'), ('At cap', 'cap'),
                ('Numeric only', 'numeric')):
            self.faction_change.addItem(label, value)
        self.faction_change.setAccessibleName('Faction change filter')
        self.faction_change.setToolTip(
            'Show gains, losses, capped messages, or exact numeric adjustments')
        self.faction_change.currentIndexChanged.connect(
            self._activity_filters_changed)
        controls.addWidget(self.faction_change)
        controls.addWidget(self.faction_profile)
        controls.addWidget(self.faction_zone)
        layout.addLayout(controls)
        self.faction_notice = QLabel(
            'FACTION · persistent local history · original EQ log stays authoritative')
        self.faction_notice.setObjectName('CombatDataNotice')
        self.faction_notice.setToolTip(
            'Vantage stores parsed rows locally for fast history; it never edits the EQ log')
        layout.addWidget(self.faction_notice)
        layout.addWidget(self.tables['Faction'], 1)
        return host

    def _build_randoms(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)

        self.random_policy = QComboBox()
        for label, value in (
                ("First roll", "first"), ("Highest roll", "highest"),
                ("Latest roll", "latest")):
            self.random_policy.addItem(label, value)
        self.random_policy.setAccessibleName("Duplicate roll policy")
        self.random_policy.setToolTip(
            "Choose which roll counts when one player rolls more than once")
        self.random_policy.currentIndexChanged.connect(
            self._random_controls_changed)
        controls.addWidget(self.random_policy)

        self.random_gap = QComboBox()
        for seconds in (10, 20, 30, 60):
            self.random_gap.addItem(f"{seconds}s gap", seconds)
        self.random_gap.setCurrentIndex(1)
        self.random_gap.setAccessibleName("Random set inactivity gap")
        self.random_gap.setToolTip(
            "Start a new set after this many seconds without a roll in the same range")
        self.random_gap.currentIndexChanged.connect(
            self._random_controls_changed)
        controls.addWidget(self.random_gap)

        split = QToolButton()
        split.setIcon(game_icon("roll"))
        split.setAccessibleName("Split before selected roll")
        split.setToolTip(
            "Start a new roll set at the selected raw roll")
        split.clicked.connect(self._split_random_set)
        controls.addWidget(split)
        clear_splits = QToolButton()
        clear_splits.setIcon(game_icon("delete"))
        clear_splits.setAccessibleName("Clear manual roll splits")
        clear_splits.setToolTip(
            "Remove every manual split; parsed rolls are never deleted")
        clear_splits.clicked.connect(self._clear_random_splits)
        controls.addWidget(clear_splits)
        layout.addLayout(controls)

        self.random_notice = QLabel(
            "ROLL SETS · grouped by range and inactivity · duplicate policy: first roll")
        self.random_notice.setObjectName("CombatDataNotice")
        self.random_notice.setToolTip(
            "Manual splits affect only this Vantage session and do not edit the EQ log")
        self.random_notice.setWordWrap(True)
        layout.addWidget(self.random_notice)
        self.random_tabs = QTabWidget()
        self.random_tabs.setDocumentMode(True)
        self.random_tabs.setAccessibleName("Raw rolls and resolved roll sets")
        self.random_tabs.setToolTip(
            "Inspect every raw /random or the grouped winner summary")
        self.random_tabs.addTab(self.tables["Randoms"], "Raw Rolls")
        self.random_tabs.addTab(self.tables["Roll Sets"], "Roll Sets")
        ensure_tab_tooltips(self.random_tabs, {
            'Raw Rolls': 'Show every parsed /random line before grouping',
            'Roll Sets': 'Show grouped ranges, duplicate policy, and winner',
        })
        layout.addWidget(self.random_tabs, 1)
        return host

    def _random_controls_changed(self, *_):
        self._activity_signature = None
        self._refresh_activity()

    def _split_random_set(self):
        row = self.tables["Randoms"].currentRow()
        randoms = list(self._tracker.randoms)
        if not 0 <= row < len(randoms):
            self.random_notice.setText(
                "Select a row in Raw Rolls before creating a manual split")
            return
        self._random_breaks.add(randoms[row].timestamp)
        self._activity_signature = None
        self._refresh_activity()

    def _clear_random_splits(self):
        self._random_breaks.clear()
        self._activity_signature = None
        self._refresh_activity()

    def _build_fights(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.fight_status = QLabel(
            'Select fights to combine, or double-click to inspect the selection')
        self.fight_status.setObjectName('CombatDataNotice')
        self.fight_status.setToolTip(
            'Manual history edits affect only this Vantage session, never the EQ log')
        controls.addWidget(self.fight_status, 1)
        self.fight_combine = QToolButton()
        self.fight_combine.setText('Combine')
        self.fight_combine.setIcon(game_icon('copy'))
        self.fight_combine.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fight_combine.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.fight_combine.setToolTip(
            'Combine all selected fights into one named encounter')
        self.fight_combine.clicked.connect(self._combine_selected_fights)
        combine_menu = QMenu(self.fight_combine)
        combine_menu.setToolTipsVisible(True)
        by_target = combine_menu.addAction('Combine by target name')
        by_target.setToolTip(
            'Combine only selected fights whose target names match')
        by_target.triggered.connect(
            lambda: self._combine_selected_fights(by_target=True))
        self.fight_combine.setMenu(combine_menu)
        controls.addWidget(self.fight_combine)
        self.fight_rename = QToolButton()
        self.fight_rename.setIcon(game_icon('edit'))
        self.fight_rename.setAccessibleName('Rename selected fight')
        self.fight_rename.setToolTip(
            'Rename one selected encounter without changing parsed statistics')
        self.fight_rename.clicked.connect(self._rename_selected_fight)
        controls.addWidget(self.fight_rename)
        self.fight_undo = QToolButton()
        self.fight_undo.setIcon(game_icon('refresh'))
        self.fight_undo.setAccessibleName('Undo fight history edit')
        self.fight_undo.setToolTip(
            'Undo the most recent combine or rename operation')
        self.fight_undo.clicked.connect(self._undo_fight_change)
        controls.addWidget(self.fight_undo)
        layout.addLayout(controls)
        layout.addWidget(self.tables['Fights'], 1)
        self._update_fight_actions()
        return host

    def _build_log_search(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.log_query = QLineEdit()
        self.log_query.setPlaceholderText('Search every linked EverQuest log…')
        self.log_query.setClearButtonEnabled(True)
        clear_query = self.log_query.findChild(QToolButton)
        if clear_query:
            clear_query.setAccessibleName("Clear log search")
            clear_query.setToolTip("Clear the log search query")
        self.log_query.setToolTip(
            'On-demand background search; Vantage never rewrites the original logs')
        self.log_query.returnPressed.connect(self._start_log_search)
        controls.addWidget(self.log_query, 1)
        self.log_saved = QComboBox()
        self.log_saved.setAccessibleName('Saved log searches')
        self.log_saved.setToolTip(
            'Load a named query with its regex, time, fight and result-limit options')
        self.log_saved.currentIndexChanged.connect(self._load_saved_search)
        self.log_saved.activated.connect(self._load_saved_search)
        controls.addWidget(self.log_saved)
        self.log_save_button = QToolButton()
        self.log_save_button.setIcon(game_icon('add'))
        self.log_save_button.setAccessibleName('Save current log search')
        self.log_save_button.setToolTip(
            'Save this query and every selected search option under a name')
        self.log_save_button.clicked.connect(self._save_log_search)
        controls.addWidget(self.log_save_button)
        self.log_delete_button = QToolButton()
        self.log_delete_button.setIcon(game_icon('delete'))
        self.log_delete_button.setAccessibleName('Delete saved log search')
        self.log_delete_button.setToolTip(
            'Delete only the selected saved query; no EverQuest log is changed')
        self.log_delete_button.clicked.connect(self._delete_saved_search)
        controls.addWidget(self.log_delete_button)
        self.log_search_button = QPushButton('Search')
        self.log_search_button.setIcon(game_icon('search'))
        self.log_search_button.setToolTip('Search all eqlog*.txt files without blocking combat parsing')
        self.log_search_button.clicked.connect(self._start_log_search)
        controls.addWidget(self.log_search_button)
        layout.addLayout(controls)

        options = QHBoxLayout()
        options.setContentsMargins(3, 0, 3, 0)
        options.setSpacing(5)
        self.log_regex = QCheckBox("Regex")
        self.log_regex.setToolTip(
            "Treat the query as a regular expression; invalid patterns show an error")
        options.addWidget(self.log_regex)
        self.log_reverse = QCheckBox("Newest first")
        self.log_reverse.setChecked(True)
        self.log_reverse.setToolTip(
            "Read large logs backwards without loading them fully into memory")
        options.addWidget(self.log_reverse)
        self.log_current_fight = QCheckBox("Fight only")
        self.log_current_fight.setToolTip(
            "Restrict results to the start and end time of the selected combat scope")
        options.addWidget(self.log_current_fight)
        self.log_range = QComboBox()
        self.log_range.setAccessibleName("Log search time range")
        self.log_range.setToolTip("Restrict results by the timestamp in each EQ log line")
        for label, hours in (
                ("All time", 0), ("Last hour", 1), ("Today", 24),
                ("7 days", 24 * 7), ("30 days", 24 * 30)):
            self.log_range.addItem(label, hours)
        options.addWidget(self.log_range)
        self.log_limit = QComboBox()
        self.log_limit.setAccessibleName("Log search result limit")
        self.log_limit.setToolTip(
            "Bound result count so a broad query remains responsive")
        for label, limit in (
                ("500 rows", 500), ("1,500 rows", 1500),
                ("5,000 rows", 5000), ("20,000 rows", 20000)):
            self.log_limit.addItem(label, limit)
        self.log_limit.setCurrentIndex(1)
        options.addWidget(self.log_limit)
        options.addStretch(1)
        layout.addLayout(options)
        self.log_search_status = QLabel('Ready · searches the original EQ logs on demand')
        self.log_search_status.setObjectName('CombatDataNotice')
        layout.addWidget(self.log_search_status)
        layout.addWidget(self.tables['Log Search'], 1)
        self._refresh_saved_searches()
        return host

    def _build_threat(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.threat_status = QLabel()
        self.threat_status.setObjectName("CombatDataNotice")
        self.threat_status.setToolTip(
            "Current local estimate and active target; server hate is not visible in P99 logs")
        controls.addWidget(self.threat_status, 1)
        configure = QPushButton("Weapons")
        configure.setIcon(game_icon("settings"))
        configure.setToolTip(
            "Configure main-hand, off-hand, same-animation split, and proc log text")
        configure.clicked.connect(self._configure_threat)
        controls.addWidget(configure)
        reset = QPushButton()
        reset.setIcon(game_icon("refresh"))
        reset.setAccessibleName("Reset threat estimates")
        reset.setToolTip("Clear every local threat estimate without changing the EQ log")
        reset.clicked.connect(self._reset_threat)
        controls.addWidget(reset)
        layout.addLayout(controls)
        note = QLabel(
            "ESTIMATE · counts attempts, not damage dealt · no memory reading or remote sharing")
        note.setObjectName("CombatDataNotice")
        note.setToolTip(
            "Classic logs omit the actual hate list, some off-hand identity, and unobserved player actions")
        layout.addWidget(note)
        layout.addWidget(self.tables["Threat"], 1)
        return host

    def _build_pets(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.setContentsMargins(3, 3, 3, 0)
        controls.setSpacing(3)
        self.merge_pets = QCheckBox("Merge into owner")
        self.merge_pets.setChecked(
            config.data["combat"].get("merge_pets", True))
        self.merge_pets.setToolTip(
            "Show owner and linked pet damage as one combined row")
        self.merge_pets.toggled.connect(self._merge_pets_changed)
        controls.addWidget(self.merge_pets)
        self.pet_name = QLineEdit()
        self.pet_name.setPlaceholderText("Pet name")
        self.pet_name.setClearButtonEnabled(True)
        self.pet_name.setToolTip(
            "Exact pet name as it appears in the EverQuest combat log")
        pet_clear = self.pet_name.findChild(QToolButton)
        if pet_clear:
            pet_clear.setAccessibleName("Clear pet name")
            pet_clear.setToolTip("Clear the pet-name field")
        controls.addWidget(self.pet_name)
        self.pet_owner = QLineEdit()
        self.pet_owner.setPlaceholderText("Owner")
        self.pet_owner.setClearButtonEnabled(True)
        self.pet_owner.setToolTip("Player to receive the linked pet's damage")
        owner_clear = self.pet_owner.findChild(QToolButton)
        if owner_clear:
            owner_clear.setAccessibleName("Clear pet owner")
            owner_clear.setToolTip("Clear the owner field")
        controls.addWidget(self.pet_owner)
        add = QPushButton("Link")
        add.setIcon(game_icon("add"))
        add.setToolTip("Remember this pet-to-owner link and refresh every fight")
        add.clicked.connect(self._add_pet_link)
        controls.addWidget(add)
        remove = QPushButton()
        remove.setIcon(game_icon("delete"))
        remove.setAccessibleName("Delete selected pet links")
        remove.setToolTip("Delete selected remembered pet-to-owner links")
        remove.clicked.connect(self._delete_pet_links)
        controls.addWidget(remove)
        layout.addLayout(controls)
        self.pet_context = QLabel(
            "LOCAL LOG · waiting for character, group, and pet events")
        self.pet_context.setObjectName("CombatDataNotice")
        self.pet_context.setMinimumWidth(0)
        self.pet_context.setToolTip(
            "Character level and class, group leader, and active pet are learned "
            "only from exact EverQuest log messages. Manual pet links remain "
            "available when the client emits no /pet leader response.")
        layout.addWidget(self.pet_context)
        layout.addWidget(self.tables["Pets"], 1)
        return host

    def _merge_pets_changed(self, enabled):
        config.data["combat"]["merge_pets"] = bool(enabled)
        config.save()
        self.refresh()

    def _add_pet_link(self):
        if not self._tracker.register_pet(
                self.pet_name.text(), self.pet_owner.text(), "Manual"):
            return
        self.pet_name.clear()
        self.pet_owner.clear()
        self._save_pet_links()
        self._refresh_pets()
        self.refresh()

    def _delete_pet_links(self):
        rows = sorted({
            item.row() for item in self.tables["Pets"].selectedItems()},
            reverse=True)
        visible = self._tracker.pet_rows()
        changed = False
        for row in rows:
            if 0 <= row < len(visible):
                changed = self._tracker.remove_pet(visible[row]["pet"]) or changed
        if changed:
            self._save_pet_links()
            self._refresh_pets()
            self.refresh()

    def _save_pet_links(self):
        config.data["combat"]["pet_links"] = {
            value["pet"]: value["owner"]
            for value in self._tracker.pet_rows()}
        config.save()
        self._pet_revision = self._tracker.pet_revision

    def _refresh_pets(self):
        if self._pet_revision == self._tracker.pet_revision:
            return
        rows = self._tracker.pet_rows()
        self._set_rows(self.tables["Pets"], [(
            value["pet"], value["owner"], value["source"])
            for value in rows])
        self._pet_revision = self._tracker.pet_revision

    def _sync_character_context(self):
        context = getattr(self, '_character_context', None)
        if not context:
            return
        identity = (
            context.server.casefold(), context.character.casefold(),
            context.revision)
        if identity == self._context_revision:
            return
        self._context_revision = identity
        player = context.character or "Current character"
        profile = player
        if context.level or context.player_class:
            profile += " · " + " ".join(
                value for value in (
                    str(context.level) if context.level else "",
                    context.player_class) if value)
        leader = context.group_leader or "none"
        pet = context.pet_name or "none"
        if context.pet_name and context.pet_state:
            pet += f" ({context.pet_state})"
        self.pet_context.setText(
            f"LOCAL LOG · {profile} · LEADER {leader} · PET {pet}")
        self.pet_context.setToolTip(
            f"Profile: {player}" +
            (f" · {context.server}" if context.server else "") +
            f"\nGroup leader: {leader}\nActive pet: {pet}" +
            (f"\nSummon spell: {context.pet_spell}"
             if context.pet_spell else "") +
            "\nSource: exact messages in the local EverQuest log")
        if context.pet_name:
            self._tracker.register_pet(
                context.pet_name, context.character or "You",
                "Local pet context")

    def _configure_threat(self):
        dialog = ThreatSettingsDialog(
            config.data["combat"].get("threat", {}), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config.data["combat"]["threat"] = dialog.value()
        config.save()
        self._threat.configure(config.data["combat"]["threat"])
        self._refresh_threat()

    def _reset_threat(self):
        if not self._threat.targets:
            return
        answer = QMessageBox.question(
            self, "Reset Threat Estimates",
            "Clear every local threat estimate?\n"
            "Weapon settings and the original EverQuest log will remain unchanged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._threat.reset()
            self._refresh_threat()

    def _refresh_threat(self):
        if not self._threat.enabled:
            self.threat_status.setText("Threat parsing off · weapon settings retained")
        elif not self._threat.configured:
            self.threat_status.setText("Configure a main-hand weapon to begin estimating")
        else:
            current = self._threat.current()
            self.threat_status.setText(
                f"{current.name} · {current.total:,.0f} threat"
                if current else "Ready · waiting for your next weapon attempt")
        rows = []
        for target in self._threat.recent():
            rows.append((
                target.name, f"{target.total:,.0f}",
                f"{target.threat_per_minute:,.0f}", f"{target.equal_flux:,}",
                target.main_swings, target.off_swings, target.procs,
                f"{target.skill_threat:,.0f}", f"{target.spell_threat:+,.0f}",
                "Killed" if target.killed else (
                    "Active" if target is self._threat.current() else "Recent")))
        self._set_rows(self.tables["Threat"], rows)
        if self._threat.last_error:
            self.threat_status.setToolTip(
                self._threat.last_error +
                "\nOpen Weapons to match the selected item types to the EQ attack verb.")

    def _refresh_saved_searches(self, selected=''):
        self.log_saved.blockSignals(True)
        self.log_saved.clear()
        self.log_saved.addItem('Saved searches…', None)
        selected_index = 0
        for index, item in enumerate(
                config.data['combat'].get('saved_searches', []), 1):
            self.log_saved.addItem(item['name'], index - 1)
            self.log_saved.setItemData(
                index, f"{item['query']} · saved search",
                Qt.ItemDataRole.ToolTipRole)
            if item['name'] == selected:
                selected_index = index
        self.log_saved.setCurrentIndex(selected_index)
        self.log_saved.blockSignals(False)
        self.log_delete_button.setEnabled(selected_index > 0)

    def _load_saved_search(self, index):
        saved_index = self.log_saved.itemData(index)
        searches = config.data['combat'].get('saved_searches', [])
        if saved_index is None or not 0 <= int(saved_index) < len(searches):
            self.log_delete_button.setEnabled(False)
            return
        item = searches[int(saved_index)]
        self.log_query.setText(item['query'])
        self.log_regex.setChecked(item['regex'])
        self.log_reverse.setChecked(item['reverse'])
        self.log_current_fight.setChecked(item['fight_only'])
        range_index = self.log_range.findData(item['hours'])
        self.log_range.setCurrentIndex(max(0, range_index))
        limit_index = self.log_limit.findData(item['limit'])
        self.log_limit.setCurrentIndex(max(0, limit_index))
        self.log_delete_button.setEnabled(True)
        self.log_search_status.setText(
            f"Loaded saved search · {item['name']}")

    def _save_log_search(self):
        query = self.log_query.text().strip()
        if len(query) < 2:
            self.log_search_status.setText(
                'Enter at least 2 characters before saving')
            return
        current = (
            self.log_saved.currentText()
            if self.log_saved.currentIndex() > 0 else query[:48])
        name, accepted = QInputDialog.getText(
            self, 'Save Log Search', 'Search name:', text=current)
        name = name.strip()[:80]
        if not accepted or not name:
            return
        saved = {
            'name': name,
            'query': query,
            'regex': self.log_regex.isChecked(),
            'reverse': self.log_reverse.isChecked(),
            'fight_only': self.log_current_fight.isChecked(),
            'hours': int(self.log_range.currentData() or 0),
            'limit': int(self.log_limit.currentData() or 1500),
        }
        searches = config.data['combat'].setdefault('saved_searches', [])
        existing = next((
            index for index, item in enumerate(searches)
            if item['name'].casefold() == name.casefold()), None)
        if existing is None:
            searches.append(saved)
        else:
            searches[existing] = saved
        config.save()
        self._refresh_saved_searches(name)
        self.log_search_status.setText(f'Saved search · {name}')

    def _delete_saved_search(self):
        saved_index = self.log_saved.currentData()
        searches = config.data['combat'].get('saved_searches', [])
        if saved_index is None or not 0 <= int(saved_index) < len(searches):
            return
        name = searches[int(saved_index)]['name']
        searches.pop(int(saved_index))
        config.save()
        self._refresh_saved_searches()
        self.log_search_status.setText(f'Deleted saved search · {name}')

    def _start_log_search(self):
        query = self.log_query.text().strip()
        directory = config.data['general'].get('eq_log_dir', '')
        if len(query) < 2:
            self.log_search_status.setText('Enter at least 2 characters')
            return
        if not Path(directory).is_dir():
            self.log_search_status.setText('Link the EverQuest Logs folder first')
            return
        if self._search_thread and self._search_thread.isRunning():
            return
        self.log_search_button.setEnabled(False)
        self.log_search_status.setText(f'Searching all linked logs for “{query}”…')
        hours = int(self.log_range.currentData() or 0)
        since = (
            datetime.datetime.now() - datetime.timedelta(hours=hours)
            if hours else None)
        until = None
        if self.log_current_fight.isChecked():
            encounter = self._scope()
            if not encounter:
                self.log_search_button.setEnabled(True)
                self.log_search_status.setText(
                    "Choose an active, last, or selected fight first")
                return
            since = max(filter(None, (since, encounter.started_at)), default=None)
            until = encounter.last_at
        self._search_thread = QThread(self)
        self._search_worker = LogSearchWorker(
            directory, query,
            limit=int(self.log_limit.currentData()),
            regex=self.log_regex.isChecked(),
            reverse=self.log_reverse.isChecked(),
            since=since, until=until)
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._search_complete)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.finished.connect(self._search_worker.deleteLater)
        self._search_thread.finished.connect(self._search_finished)
        self._search_thread.finished.connect(self._search_thread.deleteLater)
        self._search_thread.start()

    def _search_finished(self):
        self._search_worker = None
        self._search_thread = None

    def _search_complete(self, results, error, truncated):
        self.log_search_button.setEnabled(True)
        if error:
            self.log_search_status.setText(f'Log search failed · {error}')
            self.tables['Log Search'].setRowCount(0)
            return
        rows = [
            (filename,
             f'{line_number:,}' if isinstance(line_number, int) else line_number,
             line)
            for filename, line_number, line in results]
        self._set_rows(self.tables['Log Search'], rows)
        suffix = ' · result limit reached' if truncated else ''
        self.log_search_status.setText(f'{len(results):,} matches{suffix}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_summary_layout"):
            self._layout_summary()

    def _layout_summary(self):
        for widget in (self.target, self.total, self.dps, self.duration):
            self._summary_layout.removeWidget(widget)
        # ParserWindow scales one immutable logical layout. Base this choice on
        # the canonical surface, never on the outer physical window size, so a
        # resize cannot rearrange the summary.
        if self._design_size.width() >= 560:
            self._summary_layout.addWidget(self.target, 0, 0)
            self._summary_layout.addWidget(self.total, 0, 1)
            self._summary_layout.addWidget(self.dps, 0, 2)
            self._summary_layout.addWidget(self.duration, 0, 3)
            self._summary_layout.setColumnStretch(0, 1)
        else:
            self._summary_layout.addWidget(self.target, 0, 0, 1, 3)
            self._summary_layout.addWidget(self.total, 1, 0)
            self._summary_layout.addWidget(self.dps, 1, 1)
            self._summary_layout.addWidget(self.duration, 1, 2)

    def parse(self, timestamp, text):
        self._tracker.timeout = config.data["combat"]["encounter_timeout"]
        previous_pet_revision = self._tracker.pet_revision
        self._sync_character_context()
        previous_last = self._tracker.last()
        previous_chat = self._tracker.chat[0] if self._tracker.chat else None
        previous_loot = self._tracker.loot[0] if self._tracker.loot else None
        previous_coin = self._tracker.coins[0] if self._tracker.coins else None
        previous_faction = (
            self._tracker.faction[0] if self._tracker.faction else None)
        self._tracker.ingest(timestamp, text)
        if self._tracker.chat and self._tracker.chat[0] is not previous_chat:
            event = self._tracker.chat[0]
            event.character = str(getattr(self, "_active_character", "") or "")
            event.server = str(getattr(self, "_active_server", "") or "")
            if self._chat_archive.append(
                    event.timestamp, event.channel, event.speaker, event.message,
                    event.character, event.server):
                self._chat_archive_total += 1
        character = str(getattr(self, "_active_character", "") or "")
        server = str(getattr(self, "_active_server", "") or "")
        if self._tracker.loot and self._tracker.loot[0] is not previous_loot:
            event = self._tracker.loot[0]
            event.character, event.server = character, server
            self._activity_archive.append_loot(event, character, server)
        if self._tracker.coins and self._tracker.coins[0] is not previous_coin:
            event = self._tracker.coins[0]
            event.character, event.server = character, server
            self._activity_archive.append_coin(event, character, server)
        if (self._tracker.faction and
                self._tracker.faction[0] is not previous_faction):
            event = self._tracker.faction[0]
            event.character, event.server = character, server
            self._activity_archive.append_faction(event, character, server)
        if self._tracker.last() is not previous_last:
            self._show_combat_overlay(self._tracker.last(), completed=True)
            self._show_tanking_overlay(self._tracker.last(), completed=True)
        if self._tracker.pet_revision != previous_pet_revision:
            self._save_pet_links()
        self._threat.configure(config.data["combat"].get("threat", {}))
        self._threat.ingest(timestamp, text)

    def _clear(self):
        if not any((self._tracker.active, self._tracker.completed)):
            return
        answer = QMessageBox.question(
            self, "Clear Combat Session",
            "Clear every active and completed parsed fight?\n"
            "The original EverQuest log file will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._tracker.reset_session(include_activity=False)
            self._threat.reset()
            self._random_breaks.clear()
            self._history_signature = None
            self._activity_signature = None
            self._chart_signature = None
            self.refresh()

    def _scope(self):
        mode = self.mode.currentData()
        if mode == "current":
            return self._tracker.current()
        if mode == "last":
            return self._tracker.last()
        if mode == "session":
            return self._tracker.session()
        selected = []
        completed = list(self._tracker.completed)
        for index in sorted({item.row() for item in self.tables["Fights"].selectedItems()}):
            if 0 <= index < len(completed):
                selected.append(completed[index])
        return self._tracker.combine(
            selected, f"Selected · {len(selected)} fights")

    def _selected_fight_rows(self):
        return sorted({
            item.row() for item in self.tables['Fights'].selectedItems()})

    def _combine_selected_fights(self, _checked=False, by_target=False):
        rows = self._selected_fight_rows()
        if len(rows) < 2:
            self.fight_status.setText('Select at least two fights to combine')
            return
        name = ''
        if not by_target:
            completed = list(self._tracker.completed)
            targets = [
                completed[row].target for row in rows
                if 0 <= row < len(completed)]
            unique = list(dict.fromkeys(targets))
            suggested = (
                f'{unique[0]} · {len(rows)} fights' if len(unique) == 1 else
                ' + '.join(unique[:3]))
            name, accepted = QInputDialog.getText(
                self, 'Combine Fights', 'Combined encounter name:',
                text=suggested[:120])
            name = name.strip()[:120]
            if not accepted or not name:
                return
        combined = self._tracker.combine_completed(
            rows, name=name, by_target=by_target)
        if not combined:
            self.fight_status.setText(
                'No matching target has two selected fights to combine'
                if by_target else 'The selected fights could not be combined')
            self._update_fight_actions()
            return
        self._history_signature = None
        self._refresh_fights()
        combined_ids = {id(encounter) for encounter in combined}
        table = self.tables['Fights']
        table.clearSelection()
        for row, encounter in enumerate(self._tracker.completed):
            if id(encounter) in combined_ids:
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item:
                        item.setSelected(True)
        self.fight_status.setText(
            f'Combined {len(rows)} selected fights into '
            f'{len(combined)} encounter' + ('s' if len(combined) != 1 else ''))
        self._update_fight_actions()
        self.refresh()

    def _rename_selected_fight(self):
        rows = self._selected_fight_rows()
        if len(rows) != 1:
            self.fight_status.setText('Select exactly one fight to rename')
            return
        completed = list(self._tracker.completed)
        if not 0 <= rows[0] < len(completed):
            return
        encounter = completed[rows[0]]
        name, accepted = QInputDialog.getText(
            self, 'Rename Fight', 'Encounter name:', text=encounter.target)
        if not accepted or not self._tracker.rename_completed(rows[0], name):
            return
        self._history_signature = None
        self._refresh_fights()
        self.tables['Fights'].selectRow(rows[0])
        self.fight_status.setText(f'Renamed encounter · {name.strip()[:120]}')
        self._update_fight_actions()
        self.refresh()

    def _undo_fight_change(self):
        if not self._tracker.undo_completed_change():
            self.fight_status.setText('Nothing to undo')
            return
        self._history_signature = None
        self._refresh_fights()
        self.fight_status.setText('Restored the previous fight history')
        self._update_fight_actions()
        self.refresh()

    def _update_fight_actions(self):
        if not hasattr(self, 'fight_combine'):
            return
        count = len(self._selected_fight_rows())
        self.fight_combine.setEnabled(count >= 2)
        self.fight_rename.setEnabled(count == 1)
        self.fight_undo.setEnabled(
            self._tracker.can_undo_completed_change)

    def _fight_selection_changed(self):
        self._update_fight_actions()
        if self.mode.currentData() == "selected":
            self.refresh()

    def _open_selected_fights(self, *_):
        index = self.mode.findData("selected")
        self.mode.setCurrentIndex(index)
        self.refresh()

    @staticmethod
    def _format_duration(seconds):
        seconds = max(0, int(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    @staticmethod
    def _count_rate(values):
        count, attempts = values
        percent = count / attempts * 100.0 if attempts else 0.0
        return f"{count:,}/{attempts:,}", f"{percent:.1f}%"

    def _tanking_detail_row(self, tank, hit_type, stats):
        rates = stats.defense_rates()
        invuln = self._count_rate(rates["Invulnerable"])
        missed = self._count_rate(rates["Missed"])
        riposted = self._count_rate(rates["Riposted"])
        parried = self._count_rate(rates["Parried"])
        dodged = self._count_rate(rates["Dodged"])
        blocked = self._count_rate(rates["Blocked"])
        defended = self._count_rate(rates["Defended"])
        absorbed = self._count_rate(rates["Absorbed"])
        hits = self._count_rate(rates["Hits"])
        return (
            tank, hit_type, f"{stats.damage:,}", f"{stats.average_hit:,.1f}",
            stats.attempts, invuln[0], invuln[1], missed[0], missed[1],
            riposted[0], riposted[1], parried[0], parried[1],
            dodged[0], dodged[1], blocked[0], blocked[1],
            defended[0], defended[1], absorbed[0], absorbed[1],
            hits[0], hits[1])

    def _tanking_hit_rows(self, tanks):
        rows = []
        order = (
            ("Invulnerable", "Invulnerable"),
            ("Riposted", "Riposted"),
            ("Parried", "Parried"),
            ("Dodged", "Dodged"),
            ("Blocked", "Blocked"),
            ("Defended", "Defended"),
            ("Missed", "Missed"),
            ("Hits", "Hits"),
            ("Absorbed", "Absorbed"),
            ("Real Hits", "Real Hits"),
        )
        for tank in tanks:
            groups = [("Total", tank)] + sorted(
                tank.by_type.items(),
                key=lambda item: (item[1].damage, item[1].attempts),
                reverse=True)
            for hit_type, stats in groups:
                rows.append((
                    tank.name, hit_type, "Attempts", stats.attempts,
                    stats.attempts, "100.0%" if stats.attempts else "0.0%"))
                rates = stats.hit_count_rates()
                for label, key in order:
                    count, attempts = rates[key]
                    rows.append((
                        tank.name, hit_type, label, count, attempts,
                        f"{count / attempts * 100.0:.1f}%" if attempts else
                        "0.0%"))
                for amount, count in sorted(stats.hit_counts.items()):
                    rows.append((
                        tank.name, hit_type, f"Hit {amount:,}", count,
                        stats.real_hits,
                        f"{count / stats.real_hits * 100.0:.1f}%"
                        if stats.real_hits else "0.0%"))
        return rows

    def _set_rows(self, table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight |
                        Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, item)

    @staticmethod
    def _real_attacker_names(stats):
        """Return log identities, excluding a synthetic ``Owner + pets``."""
        names = {
            str(value).strip() for value in getattr(
                stats, "source_names", {stats.name})
            if str(value).strip() and
            not str(value).strip().casefold().endswith(" + pets")}
        if not names:
            name = str(stats.name).strip()
            if name.casefold().endswith(" + pets"):
                name = name[:-7].rstrip()
            names.add(name)
        return names

    @classmethod
    def _attacker_spells(cls, encounter, stats):
        wanted = {name.casefold() for name in cls._real_attacker_names(stats)}
        return {
            spell
            for caster, spells in encounter.caster_spells.items()
            if caster.casefold() in wanted
            for spell in spells}

    @classmethod
    def _attacker_class(cls, encounter, stats):
        return infer_p99_class(cls._attacker_spells(encounter, stats))

    @classmethod
    def _attacker_specials(cls, encounter, stats):
        codes = []
        for spell in sorted(cls._attacker_spells(encounter, stats), key=str.casefold):
            folded = spell.casefold()
            for prefix, code in GAMPARSE_P99_SPECIAL_CODES:
                if folded.startswith(prefix) and code not in codes:
                    codes.append(code)
        return " ".join(codes) if codes else "—"

    @classmethod
    def _incoming_for_attacker(cls, encounter, stats):
        wanted = {name.casefold() for name in cls._real_attacker_names(stats)}
        tanks = [
            tank for name, tank in encounter.tanks.items()
            if name.casefold() in wanted]
        return (
            sum(tank.damage for tank in tanks),
            max((tank.max_hit for tank in tanks), default=0))

    @classmethod
    def _gamparse_overview_rows(cls, encounter, attackers):
        """Build the supplied GamParse binary's fourteen Overview fields."""
        duration = max(1.0, encounter.duration)
        total = encounter.total_damage
        total_hits = sum(stats.hits for stats in attackers)
        total_in = sum(stats.damage for stats in encounter.tanks.values())
        total_in_max = max(
            (stats.max_hit for stats in encounter.tanks.values()), default=0)
        rows = [(
            "Total", f"{total:,}", "100.0%", cls._format_duration(duration),
            f"{total / duration:,.1f}", f"{total / duration:,.1f}",
            total_hits, max((stats.max_hit for stats in attackers), default=0),
            f"{total / max(1, total_hits):,.1f}", f"{total_in:,}",
            total_in_max, "—", "—", 0)]
        for rank, stats in enumerate(attackers, 1):
            damage_in, npc_max = cls._incoming_for_attacker(
                encounter, stats)
            active = max(1.0, stats.active_duration)
            rows.append((
                stats.name, f"{stats.damage:,}",
                f"{stats.damage / total * 100:.2f}%" if total else "0.00%",
                cls._format_duration(active),
                f"{stats.damage / active:,.1f}",
                f"{stats.damage / duration:,.1f}", stats.hits,
                stats.max_hit,
                f"{stats.damage / max(1, stats.hits):,.1f}",
                f"{damage_in:,}", npc_max,
                cls._attacker_specials(encounter, stats),
                cls._attacker_class(encounter, stats), rank))
        return rows

    def _selected_spell_casters(self):
        table = self.tables["Spells"]
        return {
            table.item(row, 0).text()
            for row in {item.row() for item in table.selectedItems()}
            if table.item(row, 0)
        }

    def _refresh_spells(self, encounter):
        self._spell_scope = encounter
        overview = self.tables["Spells"]
        selected = self._selected_spell_casters()
        caster_rows = []
        for caster, spell_map in sorted(
                encounter.caster_spells.items(),
                key=lambda item: (
                    -sum(stats.casts for stats in item[1].values()),
                    item[0].casefold())):
            values = list(spell_map.values())
            caster_rows.append((
                caster,
                infer_p99_class(spell_map.keys()),
                sum(stats.casts for stats in values),
                sum(stats.fizzles for stats in values),
                sum(stats.interrupts for stats in values),
                sum(stats.resists for stats in values),
                sum(stats.reflects for stats in values),
                sum(stats.blocks for stats in values)))
        overview.blockSignals(True)
        self._set_rows(overview, caster_rows)
        selected_rows = [
            row for row in range(overview.rowCount())
            if overview.item(row, 0).text() in selected]
        if not selected_rows and overview.rowCount():
            selected_rows = [0]
        for row in selected_rows:
            for column in range(overview.columnCount()):
                overview.item(row, column).setSelected(True)
        overview.blockSignals(False)
        self._refresh_spell_details()

    def _refresh_spell_details(self):
        encounter = getattr(self, "_spell_scope", None)
        selected = self._selected_spell_casters()
        if not encounter or not selected:
            self.tables["Spell Comparison"].setRowCount(0)
            self.tables["Spell Timeline"].setRowCount(0)
            return
        comparison = []
        for caster in sorted(selected, key=str.casefold):
            for spell, stats in sorted(
                    encounter.caster_spells.get(caster, {}).items(),
                    key=lambda item: (-item[1].casts, item[0].casefold())):
                comparison.append((
                    caster, spell, stats.casts, stats.fizzles,
                    stats.interrupts, stats.resists, stats.reflects,
                    stats.blocks))
        self._set_rows(self.tables["Spell Comparison"], comparison)
        timeline = [
            (record.timestamp.strftime("%H:%M:%S"), record.caster,
             record.spell, record.outcome, record.detail or "—")
            for record in sorted(
                encounter.spell_casts, key=lambda value: value.timestamp)
            if record.caster in selected]
        self._set_rows(self.tables["Spell Timeline"], timeline)

    def _refresh_damage_mods(self, encounter):
        rows = []
        for attacker in sorted(
                encounter.attackers.values(), key=lambda value: value.name.casefold()):
            for values in sorted(
                    attacker.damage_modifiers.values(),
                    key=lambda value: (
                        value.attack_type.casefold(),
                        value.critical_type.casefold())):
                modifier = values.modifier_percent
                rows.append((
                    attacker.name, values.attack_type, values.critical_type,
                    f"{values.reported_average:,.1f}",
                    f"{values.actual_average:,.1f}",
                    f"{modifier:+.1f}%", values.samples))
        self._set_rows(self.tables["Damage Mods"], rows)

    def _refresh_fights(self):
        completed = list(self._tracker.completed)
        signature = tuple((
            encounter.target, encounter.started_at, encounter.last_at,
            encounter.total_damage, encounter.killed) for encounter in completed)
        if signature == self._history_signature:
            return
        selected = {item.row() for item in self.tables["Fights"].selectedItems()}
        rows = []
        for encounter in completed:
            rows.append((
                encounter.target,
                encounter.started_at.strftime("%H:%M:%S"),
                self._format_duration(encounter.duration),
                encounter.zone or "—",
                encounter.player_count,
                f"{encounter.your_dps:,.1f}",
                f"{encounter.total_damage:,}",
                f"{encounter.dps:,.1f}",
                "Killed" if encounter.killed else "Timed out"))
        self._set_rows(self.tables["Fights"], rows)
        for row in selected:
            if row < self.tables["Fights"].rowCount():
                self.tables["Fights"].selectRow(row)
        self._history_signature = signature
        self._update_fight_actions()

    def _refresh_activity(self):
        chat = list(self._tracker.chat)
        loot = list(self._tracker.loot)
        coins = list(self._tracker.coins)
        randoms = list(self._tracker.randoms)
        faction = list(self._tracker.faction)
        if hasattr(self, 'loot_profile'):
            loot_events = loot + coins
            profiles = sorted({
                self._activity_profile(event) for event in loot_events},
                key=str.casefold)
            zones = sorted({
                event.zone for event in loot_events if event.zone},
                key=str.casefold)
            self._sync_filter_combo(
                self.loot_profile,
                [(label, label.casefold()) for label in profiles],
                'All profiles')
            self._sync_filter_combo(
                self.loot_zone,
                [(label, label.casefold()) for label in zones], 'All zones')
        if hasattr(self, 'faction_profile'):
            profiles = sorted({
                self._activity_profile(event) for event in faction},
                key=str.casefold)
            zones = sorted({
                event.zone for event in faction if event.zone},
                key=str.casefold)
            self._sync_filter_combo(
                self.faction_profile,
                [(label, label.casefold()) for label in profiles],
                'All profiles')
            self._sync_filter_combo(
                self.faction_zone,
                [(label, label.casefold()) for label in zones], 'All zones')
        random_policy = (
            self.random_policy.currentData()
            if hasattr(self, "random_policy") else "first")
        random_gap = (
            self.random_gap.currentData()
            if hasattr(self, "random_gap") else 20)
        loot_filters = (
            self.loot_search.text().strip().casefold(),
            self.loot_profile.currentData(), self.loot_zone.currentData())
        faction_filters = (
            self.faction_search.text().strip().casefold(),
            self.faction_change.currentData(),
            self.faction_profile.currentData(), self.faction_zone.currentData())
        signature = (
            len(chat),
            ((chat[0].timestamp, chat[0].channel, chat[0].speaker,
              chat[0].message) if chat else None),
            len(loot),
            ((loot[0].timestamp, loot[0].looter, loot[0].item)
             if loot else None),
            len(coins),
            ((coins[0].timestamp, coins[0].amount, coins[0].copper)
             if coins else None), loot_filters,
            len(randoms),
            ((randoms[-1].timestamp, randoms[-1].player,
              randoms[-1].value) if randoms else None),
            random_policy, random_gap, tuple(sorted(self._random_breaks)),
            len(faction),
            ((faction[0].timestamp, faction[0].faction,
              faction[0].change) if faction else None), faction_filters)
        if signature == self._activity_signature:
            return
        self._refresh_chat_view(chat, rebuild_channels=True)
        loot_query, loot_profile, loot_zone = loot_filters
        visible_loot = [event for event in loot if (
            (loot_profile == '*' or
             self._activity_profile(event).casefold() == loot_profile) and
            (loot_zone == '*' or event.zone.casefold() == loot_zone) and
            (not loot_query or loot_query in ' '.join((
                event.looter, event.item, event.source, event.zone,
                self._activity_profile(event))).casefold()))]
        visible_coins = [event for event in coins if (
            (loot_profile == '*' or
             self._activity_profile(event).casefold() == loot_profile) and
            (loot_zone == '*' or event.zone.casefold() == loot_zone) and
            (not loot_query or loot_query in ' '.join((
                event.amount, event.kind, event.source, event.item, event.zone,
                self._activity_profile(event))).casefold()))]
        self._set_rows(self.tables["Loot"], [(
            event.timestamp.strftime("%H:%M:%S"), event.looter,
            event.item, event.count, event.source or '—', event.zone or '—',
            self._activity_profile(event)) for event in visible_loot])
        self._set_rows(self.tables['Coin'], [(
            event.timestamp.strftime('%H:%M:%S'), event.amount,
            f'{event.copper:,}',
            ' · '.join(filter(None, (event.kind, event.source, event.item))),
            event.zone or '—', self._activity_profile(event))
            for event in visible_coins])
        if hasattr(self, 'loot_notice'):
            total_copper = sum(event.copper for event in visible_coins)
            total_items = sum(event.count for event in visible_loot)
            stored = 'persistent' if self._activity_archive.available else 'session only'
            self.loot_notice.setText(
                f'LOOT · {total_items:,} items · {len(visible_coins):,} coin '
                f'events · {self._format_coin(total_copper)} · {stored}')
        self._set_rows(self.tables["Randoms"], [(
            event.timestamp.strftime("%H:%M:%S"), event.player,
            f"{event.low:,}–{event.high:,}", f"{event.value:,}")
            for event in randoms])
        random_sets = build_random_sets(
            randoms, random_policy, random_gap, self._random_breaks)
        self._set_rows(self.tables["Roll Sets"], [(
            values["started"].strftime("%H:%M:%S"),
            f'{values["low"]:,}–{values["high"]:,}',
            values["rolls"], values["players"], values["duplicates"],
            values["winner"],
            (f'{values["winning_value"]:,}'
             if values["winning_value"] is not None else "—"))
            for values in random_sets])
        if hasattr(self, "random_notice"):
            policy_label = self.random_policy.currentText().casefold()
            self.random_notice.setText(
                f"ROLL SETS · {len(randoms)} rolls · {len(random_sets)} sets · "
                f"duplicates use {policy_label}")
        faction_query, faction_change, faction_profile, faction_zone = (
            faction_filters)
        visible_faction = []
        for event in faction:
            change_folded = event.change.casefold()
            if faction_profile != '*' and (
                    self._activity_profile(event).casefold() != faction_profile):
                continue
            if faction_zone != '*' and event.zone.casefold() != faction_zone:
                continue
            if faction_query and faction_query not in ' '.join((
                    event.faction, event.change, event.zone,
                    self._activity_profile(event))).casefold():
                continue
            if faction_change == 'gain' and not (
                    event.delta > 0 or change_folded == 'got better'):
                continue
            if faction_change == 'loss' and not (
                    event.delta < 0 or change_folded == 'got worse'):
                continue
            if faction_change == 'cap' and not change_folded.startswith(
                    'could not possibly'):
                continue
            if faction_change == 'numeric' and not event.change.startswith(
                    ('+', '-')):
                continue
            visible_faction.append(event)
        self._set_rows(self.tables["Faction"], [(
            event.timestamp.strftime("%H:%M:%S"), event.faction,
            event.change, event.zone or "—", self._activity_profile(event))
            for event in visible_faction])
        if hasattr(self, 'faction_notice'):
            stored = 'persistent local history' if self._activity_archive.available else 'session only'
            self.faction_notice.setText(
                f'FACTION · {len(visible_faction):,}/{len(faction):,} shown · '
                f'{stored} · EQ log remains authoritative')
        self._activity_signature = signature

    def refresh(self, *_):
        self._tracker.expire(datetime.datetime.now())
        self._refresh_fights()
        self._refresh_activity()
        self._refresh_pets()
        self._refresh_threat()
        self._refresh_live_combat_overlay()
        encounter = self._scope()
        self._refresh_chart(encounter)
        if not encounter:
            self.target.setText("Waiting for combat")
            self.total.setText("0 damage")
            self.dps.setText("0 DPS")
            self.duration.setText("0:00")
            for name in (
                    "Overview", "Player DPS", "Tanking", "Tanking Details",
                    "Hit Distribution",
                    "Spells", "Spell Comparison", "Spell Timeline",
                    "Direct Damage", "Damage over Time", "Damage Mods",
                    "Timeline", "Healing", "Damage Breakdown",
                    "Healer Breakdown"):
                self.tables[name].setRowCount(0)
            self._spell_scope = None
            return

        duration = max(1.0, encounter.duration)
        total = encounter.total_damage
        suffix = " · KILLED" if encounter.killed else ""
        self.target.setText(encounter.target + suffix)
        self.total.setText(f"{total:,} damage")
        self.dps.setText(f"{total / duration:,.1f} DPS")
        self.duration.setText(self._format_duration(duration))

        attackers = sorted(
            self._tracker.display_attackers(
                encounter, config.data["combat"].get("merge_pets", True)),
            key=lambda value: value.damage, reverse=True)
        self._set_rows(
            self.tables["Overview"],
            self._gamparse_overview_rows(encounter, attackers))
        self._set_rows(self.tables["Player DPS"], [(
            stats.name, f"{stats.damage:,}",
            f"{stats.damage / stats.active_duration:,.1f}",
            f"{stats.damage / duration:,.1f}",
            self._format_duration(stats.active_duration),
            stats.hits, stats.attempts, f"{stats.accuracy:.1f}%",
            stats.min_hit, stats.max_hit,
            f"{stats.damage / max(1, stats.hits):,.1f}")
            for stats in attackers])
        breakdown_rows = []
        for stats in attackers:
            for attack in sorted(
                    stats.by_type.values(), key=lambda value: value.damage,
                    reverse=True):
                breakdown_rows.append((
                    stats.name, attack.name, f"{attack.damage:,}",
                    f"{attack.damage / stats.damage * 100:.1f}%"
                    if stats.damage else "0.0%",
                    attack.hits, attack.min_hit,
                    f"{attack.damage / max(1, attack.hits):,.1f}",
                    attack.max_hit))
        self._set_rows(self.tables["Damage Breakdown"], breakdown_rows)

        tanks = sorted(
            encounter.tanks.values(), key=lambda value: value.damage,
            reverse=True)
        self._set_rows(self.tables["Tanking"], [(
            stats.name, f"{stats.damage:,}",
            f"{stats.damage / duration:,.1f}",
            f"{stats.average_hit:,.1f}", stats.attempts,
            stats.invulnerable, stats.misses, stats.ripostes,
            stats.parries, stats.dodges, stats.blocks, stats.defended,
            f"{stats.defended_percent:.1f}%", stats.absorbed,
            stats.real_hits, f"{stats.accuracy:.1f}%",
            stats.min_hit, stats.max_hit) for stats in tanks])
        detail_rows = []
        for stats in tanks:
            detail_rows.append(self._tanking_detail_row(
                stats.name, "Total", stats))
            for hit_type, values in sorted(
                    stats.by_type.items(),
                    key=lambda item: (item[1].damage, item[1].attempts),
                    reverse=True):
                detail_rows.append(self._tanking_detail_row(
                    stats.name, hit_type, values))
        self._set_rows(self.tables["Tanking Details"], detail_rows)
        self._set_rows(
            self.tables["Hit Distribution"], self._tanking_hit_rows(tanks))

        spells = sorted(
            encounter.spells.values(),
            key=lambda value: (value.damage, value.casts), reverse=True)
        self._refresh_spells(encounter)
        self._set_rows(self.tables["Direct Damage"], [(
            stats.name, f"{stats.direct_damage:,}",
            f"{stats.direct_damage / max(1, stats.damage) * 100:.1f}%",
            stats.direct_hits,
            f"{stats.direct_damage / max(1, stats.direct_hits):,.1f}",
            stats.direct_max)
            for stats in spells if stats.direct_damage])
        self._set_rows(self.tables["Damage over Time"], [(
            stats.name, f"{stats.dot_damage:,}",
            f"{stats.dot_damage / max(1, stats.damage) * 100:.1f}%",
            stats.dot_ticks,
            f"{stats.dot_damage / max(1, stats.dot_ticks):,.1f}",
            stats.dot_max)
            for stats in spells if stats.dot_damage])
        self._refresh_damage_mods(encounter)
        self._set_rows(self.tables["Timeline"], [(
            event.timestamp.strftime("%H:%M:%S"), event.kind,
            event.actor or "—", event.target or "—",
            f"{event.amount:,}" if event.amount else "—", event.detail or "—")
            for event in encounter.events])

        healers = sorted(
            encounter.healers.values(), key=lambda value: value.healing,
            reverse=True)
        self._set_rows(self.tables["Healing"], [(
            stats.name, f"{stats.healing:,}", "—", "—",
            f"{stats.healing / duration:,.1f}", "—", stats.heals,
            f"{stats.healing / max(1, stats.heals):,.1f}", stats.max_heal,
            (f"{max(stats.by_target.items(), key=lambda item: item[1]['healing'])[0]}"
             f" · {max(values['healing'] for values in stats.by_target.values()):,}"
             if stats.by_target else "—"))
            for stats in healers])
        healer_rows = []
        for stats in healers:
            for target, values in sorted(
                    stats.by_target.items(),
                    key=lambda item: item[1]["healing"], reverse=True):
                healer_rows.append((
                    stats.name, target, f"{values['healing']:,}",
                    values["heals"],
                    f"{values['healing'] / max(1, values['heals']):,.1f}",
                    values["max_heal"]))
        self._set_rows(self.tables["Healer Breakdown"], healer_rows)

    def _build_export_menu(self):
        def add_action(menu, label, tooltip, callback):
            action = menu.addAction(label)
            action.setToolTip(tooltip)
            action.triggered.connect(callback)
            return action

        clipboard_menu = self.export_menu.addMenu("Copy format")
        clipboard_menu.setToolTipsVisible(True)
        clipboard_menu.menuAction().setToolTip(
            "Choose an EQ, text, BBCode, HTML, or tabular clipboard format")
        add_action(
            clipboard_menu, "Current table",
            "Copy the visible table as tab-separated text",
            self._copy_current_view)
        add_action(
            clipboard_menu, "EQ summary",
            "Copy a ranked EQ-sized summary; Vantage never sends input to the game",
            self._copy_eq_summary)
        add_action(
            clipboard_menu, "Highlighted players for EQ",
            "Copy only rows selected in Overview using the configured EQ fields",
            lambda: self._copy_eq_summary(highlighted=True))
        add_action(
            clipboard_menu, "Selected spell casters for EQ",
            "Copy compact cast and outcome totals for casters selected in Spells Overview",
            self._copy_spell_casters_eq)
        add_action(
            clipboard_menu, "Damage modifiers for EQ",
            "Copy safely matched critical damage bonuses or penalties; no game input is sent",
            self._copy_damage_mods_eq)
        add_action(
            clipboard_menu, "Detailed plain text",
            "Copy the familiar multi-line damage, DPS, SDPS, and optional detail report",
            self._copy_detailed_text)
        add_action(
            clipboard_menu, "Current table as BBCode",
            "Copy forum-compatible BBCode for the visible table",
            self._copy_current_bbcode)
        add_action(
            clipboard_menu, "Current table as HTML",
            "Copy rich HTML plus a plain-text fallback to the clipboard",
            self._copy_current_html)

        save_menu = self.export_menu.addMenu("Save format")
        save_menu.setToolTipsVisible(True)
        save_menu.menuAction().setToolTip(
            "Choose CSV, HTML, XML, PNG, or session JSON output")
        add_action(
            save_menu, "Current table as CSV…",
            "Choose a file and export the visible table as UTF-8 CSV",
            self._export_current_view_csv)
        add_action(
            save_menu, "Full encounter as HTML…",
            "Save every populated combat analysis table in one styled standalone report",
            self._save_full_html)
        add_action(
            save_menu, "Full encounter as XML…",
            "Save every populated combat analysis table as structured XML",
            self._save_full_xml)
        add_action(
            save_menu, "Current view as PNG…",
            "Capture the current combat tab exactly as displayed and save a PNG",
            self._save_current_view_png)
        add_action(
            save_menu, "Combat session as JSON…",
            "Export active and completed encounter data without raw log duplication",
            self._export_session_json)

        self.export_menu.addSeparator()
        add_action(
            self.export_menu, "Output options…",
            "Configure EQ fields, top players, separators, detailed text, and HTML style",
            self._open_export_options)
        add_action(
            self.export_menu, "Parser diagnostics…",
            "Open the opt-in, bounded Log Details view for melee, defense, damage, DoT, healing, and spells",
            self._open_parser_diagnostics)

    def _open_parser_diagnostics(self):
        if self._diagnostics_dialog is None:
            self._diagnostics_dialog = CombatDiagnosticsDialog(
                self._tracker, self)
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    def _output_options(self):
        return dict(config.data["combat"].get("export_options", {}))

    def _open_export_options(self):
        dialog = CombatExportOptionsDialog(self._output_options(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config.data["combat"]["export_options"] = dialog.value()
        config.save()
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", "Saved combat output options", msecs=2200)

    def _attackers_for_export(self, encounter, highlighted=False):
        attackers = sorted(
            self._tracker.display_attackers(
                encounter, config.data["combat"].get("merge_pets", True)),
            key=lambda value: value.damage, reverse=True)
        if not highlighted:
            return attackers
        table = self.tables["Overview"]
        selected_rows = sorted({item.row() for item in table.selectedItems()})
        selected_names = [
            table.item(row, 0).text()
            for row in selected_rows if table.item(row, 0)]
        by_name = {stats.name: stats for stats in attackers}
        return [by_name[name] for name in selected_names if name in by_name]

    def _copy_eq_summary(self, highlighted=False):
        encounter = self._scope()
        if not encounter:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Choose a current, last, selected, or session encounter first",
                msecs=3000)
            return
        attackers = self._attackers_for_export(encounter, highlighted)
        if highlighted and not attackers:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Select one or more rows in Overview first",
                msecs=3000)
            return
        lines = eq_summary_lines(
            encounter, attackers, self._output_options(), max_chars=240)
        QApplication.clipboard().setText("\n".join(lines))
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat",
            f"Copied EQ summary · {len(lines)} clipboard line" +
            ("s" if len(lines) != 1 else "") + " · no game input sent",
            msecs=3200)

    def _eq_prefix(self):
        prefix = str(self._output_options().get("output_channel", "")).strip()
        return f"{prefix} " if prefix else ""

    def _copy_spell_casters_eq(self):
        encounter = self._scope()
        selected = self._selected_spell_casters()
        if not encounter or not selected:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat",
                "Select one or more casters in Spells · Overview first",
                msecs=3000)
            return
        lines = []
        for caster in sorted(selected, key=str.casefold):
            spell_map = encounter.caster_spells.get(caster, {})
            values = list(spell_map.values())
            casts = sum(item.casts for item in values)
            outcomes = (
                ("F", sum(item.fizzles for item in values)),
                ("I", sum(item.interrupts for item in values)),
                ("R", sum(item.resists for item in values)),
                ("RF", sum(item.reflects for item in values)),
                ("B", sum(item.blocks for item in values)),
            )
            suffix = " ".join(
                f"{label}:{count}" for label, count in outcomes if count)
            line = f"{self._eq_prefix()}{caster} - {casts} casts"
            if suffix:
                line += f" ({suffix})"
            lines.append(line[:240])
        QApplication.clipboard().setText("\n".join(lines))
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat",
            f"Copied {len(lines)} caster line" +
            ("s" if len(lines) != 1 else "") + " · no game input sent",
            msecs=3000)

    def _copy_damage_mods_eq(self):
        encounter = self._scope()
        if not encounter:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Choose an encounter before copying modifiers",
                msecs=2800)
            return
        values = []
        for attacker in sorted(
                encounter.attackers.values(), key=lambda item: item.name.casefold()):
            for stats in sorted(
                    attacker.damage_modifiers.values(),
                    key=lambda item: (
                        item.attack_type.casefold(), item.critical_type.casefold())):
                values.append(
                    f"{attacker.name} {stats.attack_type} "
                    f"{stats.modifier_percent:+.1f}% ({stats.samples})")
        if not values:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat",
                "No critical report-and-hit pairs are visible for this encounter",
                msecs=3200)
            return
        separator = str(self._output_options().get("separator", " | ") or " | ")
        lines = []
        prefix = f"{self._eq_prefix()}{encounter.target} mods: "
        current = prefix
        for value in values:
            candidate = current + (separator if current != prefix else "") + value
            if len(candidate) > 240 and current != prefix:
                lines.append(current)
                current = f"{self._eq_prefix()}mods: {value}"
            else:
                current = candidate
        if current != prefix:
            lines.append(current[:240])
        QApplication.clipboard().setText("\n".join(lines))
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat",
            f"Copied {len(lines)} damage-modifier line" +
            ("s" if len(lines) != 1 else "") + " · no game input sent",
            msecs=3000)

    def _copy_detailed_text(self):
        encounter = self._scope()
        if not encounter:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Choose an encounter before copying details",
                msecs=2800)
            return
        text = detailed_plain_text(
            encounter, self._attackers_for_export(encounter),
            self._output_options())
        QApplication.clipboard().setText(text)
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", "Copied detailed plain-text report", msecs=2500)

    @staticmethod
    def _table_data(table):
        headers = [
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())]
        rows = [[
            table.item(row, column).text() if table.item(row, column) else ""
            for column in range(table.columnCount())]
            for row in range(table.rowCount())]
        return headers, rows

    def _export_title_summary(self, label, encounter):
        if not encounter:
            return f"Vantage · {label}", f"{label} · visible session activity"
        duration = self._format_duration(encounter.duration)
        title = f"{encounter.target} · {label}"
        summary = (
            f"{encounter.total_damage:,} damage · {encounter.dps:,.1f} SDPS · "
            f"{duration} · {encounter.zone or 'Unknown zone'}")
        return title, summary

    def _copy_current_bbcode(self):
        label, encounter, headers, rows = self._current_table_data()
        if not headers:
            return
        title, summary = self._export_title_summary(label, encounter)
        QApplication.clipboard().setText(
            bbcode_table(title, summary, headers, rows))
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Copied {label} as BBCode", msecs=2400)

    def _copy_current_html(self):
        label, encounter, headers, rows = self._current_table_data()
        if not headers:
            return
        title, summary = self._export_title_summary(label, encounter)
        html = html_report(
            title, summary, [(label, headers, rows)], self._output_options())
        mime = QMimeData()
        mime.setHtml(html)
        mime.setText(tabular_text(headers, rows))
        QApplication.clipboard().setMimeData(mime)
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Copied {label} as HTML", msecs=2400)

    def _encounter_sections(self):
        sections = []
        for label in (
                "Overview", "Player DPS", "Damage Breakdown", "Tanking",
                "Tanking Details", "Hit Distribution", "Threat", "Spells",
                "Spell Comparison",
                "Spell Timeline", "Direct Damage", "Damage over Time",
                "Damage Mods", "Timeline", "Healing",
                "Healer Breakdown"):
            table = self.tables[label]
            headers, rows = self._table_data(table)
            if rows:
                sections.append((label, headers, rows))
        return sections

    @staticmethod
    def _with_extension(path, suffix):
        value = Path(path)
        return value if value.suffix.casefold() == suffix else value.with_suffix(suffix)

    def _full_report_context(self):
        encounter = self._scope()
        if not encounter:
            return None, "", "", []
        title = f"Overall Summary for {encounter.target}"
        summary = (
            f"Total Damage done: {encounter.total_damage:,} · "
            f"Total SDPS: {encounter.dps:,.1f} · "
            f"Total time: {self._format_duration(encounter.duration)} · "
            f"Zone: {encounter.zone or 'Unknown'}")
        return encounter, title, summary, self._encounter_sections()

    def _save_full_html(self):
        encounter, title, summary, sections = self._full_report_context()
        if not encounter or not sections:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Choose an encounter before saving HTML",
                msecs=2800)
            return
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", encounter.target).strip("-")
        suggested = f"Vantage-{safe_name or 'Encounter'}.html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Full Encounter HTML", suggested,
            "HTML report (*.html);;All Files (*)")
        if not path:
            return
        target = self._with_extension(path, ".html")
        try:
            target.write_text(
                html_report(title, summary, sections, self._output_options()),
                encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "HTML Export Failed", str(error))
            return
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Saved HTML · {target.name}", msecs=2600)

    def _save_full_xml(self):
        encounter, title, summary, sections = self._full_report_context()
        if not encounter or not sections:
            QApplication.instance().show_overlay_notification(
                "Vantage · Combat", "Choose an encounter before saving XML",
                msecs=2800)
            return
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", encounter.target).strip("-")
        suggested = f"Vantage-{safe_name or 'Encounter'}.xml"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Full Encounter XML", suggested,
            "XML report (*.xml);;All Files (*)")
        if not path:
            return
        target = self._with_extension(path, ".xml")
        try:
            target.write_text(
                xml_report(title, summary, sections), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "XML Export Failed", str(error))
            return
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Saved XML · {target.name}", msecs=2600)

    def _save_current_view_png(self):
        label = self.tabs.tabText(self.tabs.currentIndex())
        suggested = (
            f"Vantage-{label.replace(' ', '-')}-"
            f"{datetime.datetime.now():%Y%m%d-%H%M}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Combat View", suggested,
            "PNG image (*.png);;All Files (*)")
        if not path:
            return
        target = self._with_extension(path, ".png")
        QApplication.processEvents()
        pixmap = self.tabs.currentWidget().grab()
        if pixmap.isNull():
            pixmap = self.grab()
        if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
            QMessageBox.warning(
                self, "PNG Export Failed", "Vantage could not save that image.")
            return
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat", f"Saved PNG · {target.name}", msecs=2500)

    def _copy_current_view(self):
        label, encounter, headers, rows = self._current_table_data()
        if not headers:
            return
        lines = []
        if (encounter and not label.startswith('Loot') and
                label not in ("Faction", "Chat", "Log Search")):
            lines.append(
                f"{encounter.target} · {encounter.total_damage:,} damage · "
                f"{encounter.dps:,.1f} DPS · "
                f"{self._format_duration(encounter.duration)}")
        lines.append("\t".join(headers))
        lines.extend("\t".join(row) for row in rows)
        QApplication.clipboard().setText("\n".join(lines))
        QApplication.instance().show_overlay_notification(
            "Vantage · Combat",
            f"Copied {label}" + (
                f" for {encounter.target}" if encounter else ""),
            msecs=2500)

    def _current_table_data(self):
        encounter = self._scope()
        label = self.tabs.tabText(self.tabs.currentIndex())
        if label == "Randoms" and hasattr(self, "random_tabs"):
            nested_label = self.random_tabs.tabText(
                self.random_tabs.currentIndex())
            table = self.tables[
                "Roll Sets" if nested_label == "Roll Sets" else "Randoms"]
            label = f"Randoms · {nested_label}"
        elif label == 'Loot' and hasattr(self, 'loot_tabs'):
            nested_label = self.loot_tabs.tabText(
                self.loot_tabs.currentIndex())
            table = self.tables[
                'Coin' if nested_label == 'Coin' else 'Loot']
            label = f'Loot · {nested_label}'
        elif label == "Spells" and hasattr(self, "spell_tabs"):
            nested_label = self.spell_tabs.tabText(
                self.spell_tabs.currentIndex())
            key = {
                "Overview": "Spells",
                "Comparison": "Spell Comparison",
                "By Time": "Spell Timeline",
            }.get(nested_label, "Spells")
            table = self.tables[key]
            label = f"Spells · {nested_label}"
        else:
            table = self.tables.get(label)
        if not table:
            return label, encounter, [], []
        headers = [
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())]
        rows = []
        for row in range(table.rowCount()):
            rows.append([
                table.item(row, column).text() if table.item(row, column) else ""
                for column in range(table.columnCount())])
        return label, encounter, headers, rows

    def _export_current_view_csv(self):
        label, encounter, headers, rows = self._current_table_data()
        if not headers:
            return
        suggested = (
            f"Vantage-{label.replace(' ', '-')}-"
            f"{datetime.datetime.now():%Y%m%d-%H%M}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Combat View', suggested,
            'CSV table (*.csv);;All Files (*)')
        if not path:
            return
        try:
            with Path(path).open('w', encoding='utf-8-sig', newline='') as out:
                writer = csv.writer(out)
                if (encounter and not label.startswith('Loot') and
                        label not in ('Faction', 'Chat', 'Log Search')):
                    writer.writerow((
                        encounter.target, f'{encounter.total_damage} damage',
                        f'{encounter.dps:.1f} DPS',
                        self._format_duration(encounter.duration)))
                writer.writerow(headers)
                writer.writerows(rows)
        except OSError as error:
            QMessageBox.warning(self, 'Export Failed', str(error))
            return
        QApplication.instance().show_overlay_notification(
            'Vantage · Combat', f'Exported {label} as CSV',
            msecs=2500)

    @staticmethod
    def _encounter_payload(encounter, active=False):
        return {
            'target': encounter.target,
            'active': bool(active),
            'started_at': encounter.started_at.isoformat(),
            'last_at': encounter.last_at.isoformat(),
            'zone': encounter.zone,
            'killed': encounter.killed,
            'duration_seconds': encounter.duration,
            'total_damage': encounter.total_damage,
            'attackers': [{
                'name': stats.name, 'damage': stats.damage,
                'hits': stats.hits, 'attempts': stats.attempts,
                'misses': stats.misses, 'criticals': stats.criticals,
                'critical_types': dict(stats.critical_types),
                'min_hit': stats.min_hit, 'max_hit': stats.max_hit,
                'active_seconds': stats.active_duration,
                'dps': stats.damage / max(1.0, stats.active_duration),
                'sdps': stats.damage / max(1.0, encounter.duration),
                'average_hit': stats.damage / max(1, stats.hits),
                'source_names': sorted(stats.source_names, key=str.casefold),
                'attacks': [vars(values) for values in stats.by_type.values()],
                'damage_modifiers': [
                    vars(values) for values in stats.damage_modifiers.values()],
            } for stats in encounter.attackers.values()],
            'tanks': [stats.to_dict() for stats in encounter.tanks.values()],
            'spells': [vars(stats) for stats in encounter.spells.values()],
            'caster_spells': [{
                'caster': caster,
                'spells': [vars(stats) for stats in spells.values()],
            } for caster, spells in encounter.caster_spells.items()],
            'spell_casts': [{
                **vars(record), 'timestamp': record.timestamp.isoformat(),
            } for record in encounter.spell_casts],
            'healers': [vars(stats) for stats in encounter.healers.values()],
            'timeline': [{
                'time': event.timestamp.isoformat(), 'kind': event.kind,
                'actor': event.actor, 'target': event.target,
                'amount': event.amount, 'detail': event.detail,
            } for event in encounter.events],
        }

    def _export_session_json(self):
        suggested = f"Vantage-combat-{datetime.datetime.now():%Y%m%d-%H%M}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Combat Session', suggested,
            'JSON data (*.json);;All Files (*)')
        if not path:
            return
        payload = {
            'source': 'Vantage local EverQuest log parser',
            'exported_at': datetime.datetime.now().isoformat(),
            'encounters': [
                self._encounter_payload(encounter, True)
                for encounter in self._tracker.active.values()] + [
                self._encounter_payload(encounter, False)
                for encounter in self._tracker.completed],
            'activity': {
                'loot': [{**vars(item), 'timestamp': item.timestamp.isoformat()}
                         for item in self._tracker.loot],
                'coin': [{**vars(item), 'timestamp': item.timestamp.isoformat()}
                         for item in self._tracker.coins],
                'faction': [{**vars(item), 'timestamp': item.timestamp.isoformat()}
                            for item in self._tracker.faction],
                'randoms': [{**vars(item), 'timestamp': item.timestamp.isoformat()}
                            for item in self._tracker.randoms],
                'chat': [{**vars(item), 'timestamp': item.timestamp.isoformat()}
                         for item in self._tracker.chat],
            },
        }
        try:
            Path(path).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding='utf-8')
        except (OSError, TypeError) as error:
            QMessageBox.warning(self, 'Export Failed', str(error))
            return
        QApplication.instance().show_overlay_notification(
            'Vantage · Combat', 'Exported the combat session as JSON',
            msecs=2500)
