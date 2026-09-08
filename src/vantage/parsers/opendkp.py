"""Generic OpenDKP guild browser, live auctions, and manual bidding."""

from __future__ import annotations

from datetime import datetime, timezone
import statistics
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QGridLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QToolButton, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.opendkp import (
    OpenDkpClient, auction_bids, auction_id, auction_item_name,
    normalize_guild_slug, rows_from_payload, watch_matches)
from vantage.helpers.parser import ParserWindow
from vantage.helpers.responsive import (
    ensure_tab_tooltips, ensure_table_header_tooltips)


def _clean(value, fallback="—"):
    text = " ".join(str(value or "").split())
    return text or fallback


def _number(value, digits=0):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if digits:
        return f"{amount:,.{digits}f}"
    return f"{amount:,.0f}"


def _percent(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if amount <= 1:
        amount *= 100
    return f"{amount:.1f}%"


def _date_text(value, with_time=False):
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        local = parsed.astimezone()
        return local.strftime("%b %d, %Y · %I:%M %p" if with_time else "%b %d, %Y")
    except (TypeError, ValueError):
        return raw[:24]


def _auction_end(auction):
    auction = auction if isinstance(auction, dict) else {}
    for key in ("EndTimestamp", "EndDate", "AuctionEnd", "EndsAt"):
        raw = auction.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            pass
    return None


def _remaining_text(auction):
    end = _auction_end(auction)
    if end is None:
        return "Live"
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    remaining = max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
    hours, remainder = divmod(remaining, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"


def _wins(auction):
    """Flatten a BidResults row into winner/value records."""
    result = []
    for bid in auction_bids(auction):
        if not isinstance(bid, dict):
            continue
        name = bid.get("CharacterName") or bid.get("Name") or bid.get("Winner")
        value = bid.get("Value", bid.get("BidAmount"))
        if name:
            result.append((_clean(name), value))
    if not result and isinstance(auction, dict) and auction.get("Winner"):
        result.append((_clean(auction.get("Winner")),
                       auction.get("BidAmount", auction.get("Value"))))
    return result


class SortItem(QTableWidgetItem):
    """Table item with an optional numeric sort key and attached source row."""

    def __init__(self, text, source=None, sort_value=None):
        super().__init__(str(text))
        if source is not None:
            self.setData(Qt.ItemDataRole.UserRole, source)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, SortItem):
            left, right = self._sort_value, other._sort_value
            if left is not None and right is not None:
                return left < right
        # Calling the wrapped C++ base comparator from a Python subclass can
        # crash PySide during QTableWidget's native sort. Compare the visible
        # strings in Python instead; numeric columns use the branch above.
        return self.text().casefold() < other.text().casefold()


class OpenDkpLoginDialog(QDialog):
    """Small credential prompt; the password is never exposed as plain text."""

    def __init__(self, guild_name, remembered_username="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Sign in · {guild_name}")
        self.setModal(True)
        self.setObjectName("OpenDkpLoginDialog")
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Sign in to use live auctions and manual bids. Public guild data "
            "does not require an account.")
        intro.setWordWrap(True)
        intro.setObjectName("OpenDkpLoginIntro")
        layout.addWidget(intro)
        form = QFormLayout()
        self.username = QLineEdit(remembered_username)
        self.username.setAccessibleName("OpenDKP username")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setAccessibleName("OpenDKP password")
        self.password.setAccessibleDescription(
            "Used only for this sign-in request and never saved by Vantage")
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        privacy = QLabel(
            "Vantage stores a renewable token in Windows Credential Manager; "
            "it never stores this password.")
        privacy.setWordWrap(True)
        privacy.setObjectName("OpenDkpPrivacyNote")
        layout.addWidget(privacy)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sign in")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password.returnPressed.connect(self.accept)


class OpenDKP(ParserWindow):
    """A compact, guild-agnostic OpenDKP surface."""

    name = "opendkp"
    _allow_clickthrough = False
    _minimum_scale = 0.80
    MAX_TABLE_ROWS = 2000

    def parse(self, _timestamp, _text):
        """OpenDKP is network-driven and intentionally ignores EQ log lines."""
        return None

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenDKP · Vantage")
        self._title.setText("OpenDKP")
        self._title.setToolTip("DKP, raids, loot, auctions, and bids for any OpenDKP guild")
        self.client = OpenDkpClient(self)
        self._guild_details = {}
        self._datasets = {
            "dkp": [], "characters": [], "raids": [], "items": [],
            "auctions": [], "adjustments": [], "active_auctions": [],
            "character_dkp": [], "character_items": [],
            "character_adjustments": [], "character_raids": []}
        self._eligible_characters = []
        self._notified_auctions = set()
        self._adjustments_loaded = False
        self._session_restore_slug = ""
        self._busy = False
        self._build_ui()
        self.client.response.connect(self._response)
        self.client.failed.connect(self._failed)
        self.client.busy_changed.connect(self._busy_changed)
        self.client.auth_changed.connect(self._auth_changed)
        self.client.live_changed.connect(self._live_changed)
        self.client.auction_event.connect(self._auction_event)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._refresh_active_countdowns)
        self._clock.start()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.client.close)
        QTimer.singleShot(0, self._restore_active_guild)

    # ----- construction -------------------------------------------------
    def _build_ui(self):
        shell = QFrame()
        shell.setObjectName("OpenDkpGuildBar")
        grid = QGridLayout(shell)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        guild_label = QLabel("Guild")
        guild_label.setObjectName("OpenDkpFieldLabel")
        grid.addWidget(guild_label, 0, 0)
        self.guild_selector = QComboBox()
        self.guild_selector.setEditable(True)
        self.guild_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.guild_selector.setMinimumContentsLength(18)
        self.guild_selector.setAccessibleName("OpenDKP guild")
        self.guild_selector.setAccessibleDescription(
            "Enter a guild subdomain or a guild.opendkp.com address")
        self.guild_selector.setToolTip(
            "Enter any OpenDKP guild, for example guildname or guildname.opendkp.com")
        self.guild_selector.lineEdit().setPlaceholderText(
            "guildname or guildname.opendkp.com")
        self.guild_selector.lineEdit().setToolTip(self.guild_selector.toolTip())
        self.guild_selector.view().setToolTip("Choose a saved OpenDKP guild")
        guild_label.setBuddy(self.guild_selector)
        self._fill_guild_profiles()
        grid.addWidget(self.guild_selector, 0, 1)

        self.load_button = self._make_button("Load", "ph-download", self._load_guild,
                                        "Load this OpenDKP guild")
        grid.addWidget(self.load_button, 0, 2)
        self.remove_button = self._make_button(
            "Remove", "delete", self._remove_guild,
            "Remove this saved guild profile; OpenDKP data is not changed")
        grid.addWidget(self.remove_button, 0, 3)
        self.site_button = self._make_button(
            "Open site", "ph-file-search", self._open_site,
            "Open the selected guild on OpenDKP")
        self.site_button.setEnabled(False)
        grid.addWidget(self.site_button, 0, 4)
        self.refresh_button = self._make_button(
            "Refresh", "refresh", self._refresh_all,
            "Refresh DKP, roster, raids, loot, and auction history")
        self.refresh_button.setEnabled(False)
        grid.addWidget(self.refresh_button, 0, 5)

        self.guild_status = QLabel("Enter any OpenDKP guild to begin")
        self.guild_status.setObjectName("OpenDkpStatusPill")
        self.guild_status.setProperty("state", "idle")
        self.guild_status.setAccessibleName(self.guild_status.text())
        grid.addWidget(self.guild_status, 1, 0, 1, 3)
        self.progress = QProgressBar()
        self.progress.setObjectName("OpenDkpProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("OpenDKP loading progress")
        self.progress.hide()
        grid.addWidget(self.progress, 1, 3)
        self.sign_in_button = self._make_button(
            "Sign in", "ph-power", self._sign_in,
            "Sign in for live auctions and manual bidding")
        self.sign_in_button.setEnabled(False)
        grid.addWidget(self.sign_in_button, 1, 4)
        self.disconnect_button = self._make_button(
            "Disconnect", "ph-mute", self._disconnect,
            "Sign out and remove the saved OpenDKP token")
        self.disconnect_button.hide()
        grid.addWidget(self.disconnect_button, 1, 5)
        grid.setColumnStretch(1, 1)
        self.content.addWidget(shell)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("OpenDkpTabs")
        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_standings(), "Standings")
        self.tabs.addTab(self._build_auctions(), "Auctions")
        self.tabs.addTab(self._build_loot(), "Loot")
        self.tabs.addTab(self._build_raids(), "Raids")
        self.tabs.addTab(self._build_adjustments(), "Adjustments")
        ensure_tab_tooltips(self.tabs, {
            "Overview": "Your selected character's DKP, attendance, loot, and raids",
            "Standings": "Search and sort every guild character's DKP and attendance",
            "Auctions": "Watch live auctions, bid manually, and review results",
            "Loot": "Search recorded loot and DKP prices",
            "Raids": "Browse recent guild raids and totals",
            "Adjustments": "Search DKP additions and deductions",
        })
        self.tabs.currentChanged.connect(self._tab_changed)
        self.content.addWidget(self.tabs, 1)

        footer = QFrame()
        footer.setObjectName("OpenDkpFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 3, 8, 4)
        self.result_status = QLabel("Public browsing requires no login")
        self.result_status.setObjectName("OpenDkpResultStatus")
        self.result_status.setAccessibleName(self.result_status.text())
        footer_layout.addWidget(self.result_status, 1)
        self.connection_status = QLabel("Public")
        self.connection_status.setObjectName("OpenDkpConnectionState")
        self.connection_status.setProperty("state", "public")
        self.connection_status.setAccessibleName("OpenDKP connection: Public")
        footer_layout.addWidget(self.connection_status)
        self.content.addWidget(footer)

    def _build_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(6)
        chooser = QFrame()
        chooser.setObjectName("OpenDkpCharacterBar")
        chooser_layout = QHBoxLayout(chooser)
        chooser_layout.setContentsMargins(7, 5, 7, 5)
        label = QLabel("Character")
        self.character_selector = QComboBox()
        self.character_selector.setEditable(True)
        self.character_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.character_selector.setAccessibleName("Overview character")
        self.character_selector.lineEdit().setPlaceholderText("Search character…")
        self.character_selector.setToolTip(
            "Choose the character whose DKP, attendance, loot, and raids you want to see")
        self.character_selector.lineEdit().setToolTip(
            "Type to find a character in this guild")
        self.character_selector.view().setToolTip("Choose a guild character")
        self.character_selector.currentIndexChanged.connect(
            self._character_selected)
        label.setBuddy(self.character_selector)
        chooser_layout.addWidget(label)
        chooser_layout.addWidget(self.character_selector, 1)
        self.character_identity = QLabel("Choose a character")
        self.character_identity.setObjectName("OpenDkpCharacterIdentity")
        chooser_layout.addWidget(self.character_identity)
        layout.addWidget(chooser)

        cards = QFrame()
        cards.setObjectName("OpenDkpMetricStrip")
        cards_layout = QGridLayout(cards)
        cards_layout.setContentsMargins(5, 5, 5, 5)
        cards_layout.setSpacing(5)
        self.metric_values = {}
        for column, (key, title) in enumerate((
                ("dkp", "Current DKP"), ("30", "30-day attendance"),
                ("60", "60-day attendance"), ("90", "90-day attendance"),
                ("life", "Lifetime attendance"))):
            card = QFrame()
            card.setObjectName("OpenDkpMetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(7, 5, 7, 5)
            title_label = QLabel(title)
            title_label.setObjectName("OpenDkpMetricLabel")
            value_label = QLabel("—")
            value_label.setObjectName("OpenDkpMetricValue")
            value_label.setAccessibleName(f"{title}: unavailable")
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            cards_layout.addWidget(card, 0, column)
            self.metric_values[key] = value_label
        layout.addWidget(cards)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.character_loot = self._table(
            ("Date", "Item", "DKP", "Raid"), "Selected character loot")
        self.character_raids = self._table(
            ("Date", "Raid", "Awarded", "Spent"), "Selected character raids")
        split.addWidget(self._titled_table("Recent loot", self.character_loot))
        split.addWidget(self._titled_table("Recent raids", self.character_raids))
        split.setSizes([480, 480])
        layout.addWidget(split, 1)
        return page

    def _build_standings(self):
        page, layout, self.standings_search = self._search_page(
            "Search character, class, or rank…", self._filter_standings)
        self.standings_table = self._table(
            ("Character", "Class", "Level", "Rank", "DKP", "30d", "60d", "90d", "Life"),
            "OpenDKP standings")
        layout.addWidget(self.standings_table, 1)
        return page

    def _build_auctions(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(5)
        self.auction_tabs = QTabWidget()
        self.auction_tabs.setObjectName("OpenDkpAuctionTabs")
        live = QWidget()
        live_layout = QVBoxLayout(live)
        live_layout.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        live_left = QWidget()
        left_layout = QVBoxLayout(live_left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        live_tables = QSplitter(Qt.Orientation.Vertical)
        self.active_table = self._table(
            ("Item", "Time", "Bids", "High", "My bid"), "Live OpenDKP auctions")
        self.active_table.itemSelectionChanged.connect(self._auction_selected)
        live_tables.addWidget(self.active_table)
        self.bid_table = self._table(
            ("Character", "Rank", "DKP", "Priority", "Time"),
            "Bids in the selected OpenDKP auction")
        live_tables.addWidget(self._titled_table("Selected auction bids", self.bid_table))
        live_tables.setSizes([260, 135])
        left_layout.addWidget(live_tables, 1)
        bid = QFrame()
        bid.setObjectName("OpenDkpBidBar")
        bid_layout = QHBoxLayout(bid)
        bid_layout.setContentsMargins(7, 5, 7, 5)
        self.bid_selection = QLabel("Select a live auction")
        self.bid_selection.setObjectName("OpenDkpBidSelection")
        bid_layout.addWidget(self.bid_selection, 1)
        char_label = QLabel("Bid as")
        self.bid_character = QComboBox()
        self.bid_character.setAccessibleName("Character for this bid")
        self.bid_character.setToolTip(
            "Choose one of the characters linked to your OpenDKP account")
        self.bid_character.view().setToolTip("Choose a linked bidding character")
        char_label.setBuddy(self.bid_character)
        bid_layout.addWidget(char_label)
        bid_layout.addWidget(self.bid_character)
        value_label = QLabel("DKP")
        self.bid_value = QSpinBox()
        self.bid_value.setRange(1, 999999)
        self.bid_value.setValue(1)
        self.bid_value.setAccessibleName("Bid amount in DKP")
        self.bid_value.setToolTip("Enter the DKP amount to bid")
        self.bid_value.lineEdit().setToolTip("Enter the DKP amount to bid")
        value_label.setBuddy(self.bid_value)
        bid_layout.addWidget(value_label)
        bid_layout.addWidget(self.bid_value)
        priority_label = QLabel("Priority")
        self.bid_priority = QSpinBox()
        self.bid_priority.setRange(1, 99)
        self.bid_priority.setValue(1)
        self.bid_priority.setAccessibleName("Bid priority")
        self.bid_priority.setToolTip(
            "Use the priority required by your guild's OpenDKP bid rules")
        self.bid_priority.lineEdit().setToolTip(self.bid_priority.toolTip())
        priority_label.setBuddy(self.bid_priority)
        bid_layout.addWidget(priority_label)
        bid_layout.addWidget(self.bid_priority)
        self.bid_button = self._make_button(
            "Place bid", "ph-gavel", self._place_or_update_bid,
            "Confirm and submit this manual bid to OpenDKP")
        self.withdraw_button = self._make_button(
            "Withdraw", "delete", self._withdraw_bid,
            "Confirm and remove your bid from this auction")
        self.bid_button.setEnabled(False)
        self.withdraw_button.setEnabled(False)
        bid_layout.addWidget(self.bid_button)
        bid_layout.addWidget(self.withdraw_button)
        left_layout.addWidget(bid)
        split.addWidget(live_left)

        watch = QFrame()
        watch.setObjectName("OpenDkpWatchPanel")
        watch_layout = QVBoxLayout(watch)
        watch_layout.setContentsMargins(7, 6, 7, 6)
        watch_title = QLabel("Auction watchlist")
        watch_title.setObjectName("OpenDkpPanelTitle")
        watch_layout.addWidget(watch_title)
        watch_help = QLabel(
            "Vantage alerts you when a matching item appears in this guild's live auctions.")
        watch_help.setWordWrap(True)
        watch_help.setObjectName("OpenDkpPanelHelp")
        watch_layout.addWidget(watch_help)
        self.watch_list = QListWidget()
        self.watch_list.setAccessibleName("Watched OpenDKP item phrases")
        self.watch_list.setAlternatingRowColors(True)
        self.watch_list.setToolTip(
            "All item phrases watched for the current guild; select one to remove it")
        watch_layout.addWidget(self.watch_list, 1)
        self.watch_entry = QLineEdit()
        self.watch_entry.setPlaceholderText("Item name or phrase…")
        self.watch_entry.setClearButtonEnabled(True)
        self.watch_entry.setAccessibleName("New auction watch phrase")
        self.watch_entry.setToolTip(
            "Enter an item name or distinctive phrase, then press Enter or Add")
        clear_watch = self.watch_entry.findChild(QToolButton)
        if clear_watch:
            clear_watch.setToolTip("Clear the new watch phrase")
        self.watch_entry.returnPressed.connect(self._add_watch)
        watch_layout.addWidget(self.watch_entry)
        watch_actions = QHBoxLayout()
        watch_actions.addWidget(self._make_button(
            "Add", "add", self._add_watch, "Add this phrase to the current guild watchlist"))
        watch_actions.addWidget(self._make_button(
            "Remove", "delete", self._remove_watch,
            "Remove the selected phrase from this guild watchlist"))
        watch_layout.addLayout(watch_actions)
        split.addWidget(watch)
        split.setSizes([720, 230])
        live_layout.addWidget(split)

        results, results_layout, self.auctions_search = self._search_page(
            "Search item or winner…", self._filter_auctions)
        self.auctions_table = self._table(
            ("Date", "Item", "Winner", "DKP", "Auction"),
            "OpenDKP auction results")
        results_layout.addWidget(self.auctions_table, 1)
        self.auction_tabs.addTab(live, "Live & bid")
        self.auction_tabs.addTab(results, "Results")
        ensure_tab_tooltips(self.auction_tabs, {
            "Live & bid": "Authenticated live auctions, watchlist, and manual bid controls",
            "Results": "Completed OpenDKP auctions and winning bids",
        })
        layout.addWidget(self.auction_tabs, 1)
        return page

    def _build_loot(self):
        page, layout, self.loot_search = self._search_page(
            "Search item, character, or raid…", self._filter_loot)
        self.loot_summary = QLabel("No loot loaded")
        self.loot_summary.setObjectName("OpenDkpInlineSummary")
        layout.addWidget(self.loot_summary)
        self.loot_table = self._table(
            ("Date", "Item", "Character", "DKP", "Raid"), "OpenDKP loot history")
        layout.addWidget(self.loot_table, 1)
        return page

    def _build_raids(self):
        page, layout, self.raids_search = self._search_page(
            "Search raid or pool…", self._filter_raids)
        self.raids_table = self._table(
            ("Date", "Raid", "Pool", "Items", "Awarded", "Spent", "Ticks"),
            "OpenDKP raid history")
        layout.addWidget(self.raids_table, 1)
        return page

    def _build_adjustments(self):
        page, layout, self.adjustments_search = self._search_page(
            "Search character, adjustment, or description…", self._filter_adjustments)
        self.adjustments_hint = QLabel(
            "Adjustments load only when this tab is opened to keep startup fast.")
        self.adjustments_hint.setObjectName("OpenDkpInlineSummary")
        layout.addWidget(self.adjustments_hint)
        self.adjustments_table = self._table(
            ("Date", "Character", "Value", "Adjustment", "Description"),
            "OpenDKP adjustments")
        layout.addWidget(self.adjustments_table, 1)
        return page

    def _search_page(self, placeholder, callback):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(5)
        search = QLineEdit()
        search.setPlaceholderText(placeholder)
        search.setClearButtonEnabled(True)
        search.setAccessibleName(placeholder.rstrip("…"))
        search.setToolTip(placeholder.rstrip("…"))
        clear_search = search.findChild(QToolButton)
        if clear_search:
            clear_search.setToolTip("Clear this filter")
        search.textChanged.connect(callback)
        layout.addWidget(search)
        return page, layout, search

    def _make_button(self, text, icon, callback, tooltip):
        button = QPushButton(text)
        button.setIcon(game_icon(icon))
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def _table(self, headers, accessible_name):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setMinimumSectionSize(44)
        table.setAccessibleName(accessible_name)
        table.setAccessibleDescription(
            "Sortable table. Click a heading to sort; drag heading dividers to resize columns.")
        table.setToolTip(
            "Click a heading to sort · drag heading dividers to resize columns")
        ensure_table_header_tooltips(table, accessible_name.casefold())
        return table

    def _titled_table(self, title, table):
        frame = QFrame()
        frame.setObjectName("OpenDkpTableCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        label = QLabel(title)
        label.setObjectName("OpenDkpPanelTitle")
        layout.addWidget(label)
        layout.addWidget(table, 1)
        return frame

    # ----- guild profiles and session ----------------------------------
    def _profiles(self):
        return config.data.get("opendkp", {}).get("guilds", [])

    def _fill_guild_profiles(self, selected_slug=""):
        if not hasattr(self, "guild_selector"):
            return
        current = selected_slug or normalize_guild_slug(self.guild_selector.currentText())
        self.guild_selector.blockSignals(True)
        self.guild_selector.clear()
        for profile in self._profiles():
            slug = profile.get("slug", "")
            name = profile.get("name") or slug
            self.guild_selector.addItem(f"{name} · {slug}", slug)
        self.guild_selector.blockSignals(False)
        if current:
            index = self.guild_selector.findData(current)
            if index >= 0:
                self.guild_selector.setCurrentIndex(index)
            else:
                self.guild_selector.setEditText(current)

    def _current_slug_input(self):
        index = self.guild_selector.currentIndex()
        selected = self.guild_selector.currentData()
        raw = (selected if selected and index >= 0 and
               self.guild_selector.currentText() ==
               self.guild_selector.itemText(index)
               else self.guild_selector.currentText())
        return normalize_guild_slug(raw)

    def _profile(self, slug=None):
        target = slug or self.client.slug
        return next((item for item in self._profiles()
                     if item.get("slug") == target), None)

    def _save_profile(self, **values):
        slug = self.client.slug
        if not slug:
            return
        profiles = self._profiles()
        profile = self._profile(slug)
        if profile is None:
            profile = {"slug": slug, "name": slug, "url": f"https://{slug}.opendkp.com",
                       "character_id": 0, "character_name": "", "username": "",
                       "watch_items": []}
            profiles.append(profile)
        profile.update(values)
        config.data["opendkp"]["active_guild"] = slug
        config.data["opendkp"]["guilds"] = profiles[:12]
        config.save()

    def _restore_active_guild(self):
        slug = config.data.get("opendkp", {}).get("active_guild", "")
        if slug:
            self._fill_guild_profiles(slug)
            self._load_guild(slug)

    def _load_guild(self, value=None):
        raw = value if isinstance(value, str) and value else self._current_slug_input()
        slug = normalize_guild_slug(raw)
        if not slug:
            self._set_status(
                "Enter a valid guild subdomain or guild.opendkp.com address", "error", announce=True)
            return False
        self._session_restore_slug = ""
        self._adjustments_loaded = False
        self._notified_auctions.clear()
        self._clear_views()
        self._set_status(f"Connecting to {slug}.opendkp.com…", "loading")
        self.client.load_guild(slug)
        self._load_watchlist()
        return True

    def _remove_guild(self):
        slug = self._current_slug_input()
        if not slug:
            return
        if QMessageBox.question(
                self, "Remove saved guild",
                f"Remove {slug} from Vantage? This does not change OpenDKP.") != \
                QMessageBox.StandardButton.Yes:
            return
        if slug == self.client.slug:
            self.client.logout()
            self.client.slug = ""
        config.data["opendkp"]["guilds"] = [
            item for item in self._profiles() if item.get("slug") != slug]
        if config.data["opendkp"].get("active_guild") == slug:
            config.data["opendkp"]["active_guild"] = ""
        config.save()
        self._fill_guild_profiles()
        self._clear_views()
        self._set_status("Saved guild removed", "idle", announce=True)

    def _refresh_all(self):
        if not self.client.slug:
            return self._load_guild()
        self.client.refresh_public()
        if self.client.authenticated:
            self.client.fetch_active_auctions()
        if self._adjustments_loaded:
            self.client.fetch_adjustments()
        self._set_status(f"Refreshing {self._guild_name()}…", "loading")
        return True

    def _open_site(self):
        if self.client.slug:
            webbrowser.open(f"https://{self.client.slug}.opendkp.com")

    def _sign_in(self):
        if not self.client.slug:
            return
        profile = self._profile() or {}
        dialog = OpenDkpLoginDialog(
            self._guild_name(), profile.get("username") or self.client.username, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            username = dialog.username.text().strip()
            password = dialog.password.text()
            if self.client.login(username, password):
                self._save_profile(username=username)

    def _disconnect(self):
        if QMessageBox.question(
                self, "Disconnect OpenDKP",
                "Sign out and remove this guild's saved secure token?") == \
                QMessageBox.StandardButton.Yes:
            self.client.logout()

    # ----- responses ----------------------------------------------------
    def _response(self, operation, payload):
        if operation == "client":
            self._guild_details = payload if isinstance(payload, dict) else {}
            name = _clean(self._guild_details.get("Name"), self.client.slug)
            self._save_profile(name=name, url=f"https://{self.client.slug}.opendkp.com")
            self._fill_guild_profiles(self.client.slug)
            self.site_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.sign_in_button.setEnabled(bool(self._guild_details.get("WebClientId")))
            self._set_status(f"{name} · loading public guild data…", "loading")
            self.client.refresh_public()
            if self.client._refresh_token and self._session_restore_slug != self.client.slug:
                self._session_restore_slug = self.client.slug
                self.client.restore_session()
            return
        if operation == "dkp":
            self._datasets[operation] = rows_from_payload(payload, "Models", "Dkp", "DKP")
            self._populate_standings()
            self._populate_characters()
        elif operation == "characters":
            self._datasets[operation] = rows_from_payload(payload, "Characters", "Models")
            self._populate_characters()
            self._update_eligible_characters()
        elif operation in ("raids", "items", "auctions", "adjustments"):
            keys = {
                "raids": ("Raids", "Models"), "items": ("Items", "Models"),
                "auctions": ("BidResults", "Auctions", "Models"),
                "adjustments": ("Adjustments", "Models")}[operation]
            self._datasets[operation] = rows_from_payload(payload, *keys)
            getattr(self, f"_populate_{operation}")()
            if operation in ("raids", "items"):
                self._update_overview()
        elif operation.startswith("character_"):
            operation_name, _, requested_id = operation.partition(":")
            if requested_id and int(requested_id) != int(
                    self.character_selector.currentData() or 0):
                return
            key = {
                "character_dkp": ("Models", "Dkp", "DKP"),
                "character_items": ("Items", "Models"),
                "character_adjustments": ("Adjustments", "Models"),
                "character_raids": ("Raids", "Models"),
            }[operation_name]
            rows = rows_from_payload(payload, *key)
            if not rows and isinstance(payload, dict):
                rows = [payload]
            self._datasets[operation_name] = rows
            self._update_overview()
        elif operation == "active_auctions":
            self._datasets[operation] = rows_from_payload(payload, "Auctions", "BidSessions")
            self._populate_active_auctions()
        elif operation in ("place_bid", "update_bid", "delete_bid"):
            message = {
                "place_bid": "Bid placed", "update_bid": "Bid updated",
                "delete_bid": "Bid withdrawn"}[operation]
            self._set_result(message, announce=True)
            self.client.fetch_active_auctions()
        elif operation == "login":
            self._set_result("Secure OpenDKP session connected", announce=True)
        if operation in {"dkp", "characters", "raids", "items", "auctions"}:
            self._set_status(f"{self._guild_name()} · public data ready", "ready")

    def _failed(self, operation, message, status):
        prefix = {
            "auth": "Sign-in required", "login": "Sign-in failed",
            "client": "Guild not found"}.get(operation, "OpenDKP request failed")
        detail = f"{prefix}: {_clean(message, f'HTTP {status}')}"
        self._set_status(detail, "error", announce=True)
        if operation in {"place_bid", "update_bid", "delete_bid"}:
            QMessageBox.warning(self, "OpenDKP bid not changed", detail)

    def _busy_changed(self, busy, operation):
        self._busy = bool(busy)
        self.progress.setVisible(self._busy)
        self.refresh_button.setEnabled(bool(self.client.slug) and not self._busy)
        self.progress.setAccessibleName(
            f"OpenDKP loading {operation}" if busy else "OpenDKP loading complete")

    def _auth_changed(self, state, username):
        connected = state == "connected"
        self.sign_in_button.setVisible(not connected)
        self.disconnect_button.setVisible(connected)
        labels = {
            "public": "Public", "saved": "Saved session", "connecting": "Connecting…",
            "connected": f"Secure · {username}", "required": "Sign-in required",
            "expired": "Session expired", "error": "Sign-in failed"}
        self.connection_status.setText(labels.get(state, state.title()))
        self.connection_status.setProperty("state", state)
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)
        self.connection_status.setAccessibleName(
            f"OpenDKP connection: {self.connection_status.text()}")
        self._update_eligible_characters()
        if connected:
            self._save_profile(username=username)
            self.client.fetch_active_auctions()
            self.client.start_live()
        else:
            self._datasets["active_auctions"] = []
            self._populate_active_auctions()

    def _live_changed(self, state):
        if state == "live":
            self.connection_status.setText(f"Live · {self.client.username}")
            self.connection_status.setProperty("state", "live")
        elif state in {"error", "reconnecting"}:
            self.connection_status.setText("Live reconnecting…")
            self.connection_status.setProperty("state", "reconnecting")
        self.connection_status.style().unpolish(self.connection_status)
        self.connection_status.style().polish(self.connection_status)
        self.connection_status.setAccessibleName(
            f"OpenDKP connection: {self.connection_status.text()}")

    def _auction_event(self, action, rows):
        if action != "update":
            return
        watches = self._watch_items()
        for auction in rows_from_payload(rows, "Auctions", "BidSessions"):
            matches = watch_matches(auction, watches)
            key = auction_id(auction) or (
                self.client.slug, auction_item_name(auction).casefold())
            if not matches or key in self._notified_auctions:
                continue
            self._notified_auctions.add(key)
            item = auction_item_name(auction)
            QApplication.instance().notify_event(
                "opendkp_auction",
                f"OpenDKP auction: {item} · {_remaining_text(auction)} remaining",
                title="OpenDKP", channel="opendkp", allow_hidden=True)

    # ----- data views ---------------------------------------------------
    def _set_rows(self, table, rows):
        sorting = table.isSortingEnabled()
        table.setSortingEnabled(False)
        table.setRowCount(min(len(rows), self.MAX_TABLE_ROWS))
        for row_index, cells in enumerate(rows[:self.MAX_TABLE_ROWS]):
            for column, cell in enumerate(cells):
                if isinstance(cell, QTableWidgetItem):
                    item = cell
                elif isinstance(cell, tuple):
                    text, source, sort_value = (cell + (None, None))[:3]
                    item = SortItem(text, source, sort_value)
                else:
                    item = SortItem(cell)
                table.setItem(row_index, column, item)
        table.setSortingEnabled(sorting)
        if table.columnCount() and table.columnWidth(0) < 150:
            table.setColumnWidth(0, 170)

    def _populate_standings(self):
        rows = []
        for entry in self._datasets["dkp"]:
            rows.append((
                (_clean(entry.get("CharacterName")), entry, _clean(entry.get("CharacterName")).casefold()),
                _clean(entry.get("CharacterClass")),
                (_number(entry.get("CharacterLevel")), None, float(entry.get("CharacterLevel") or 0)),
                _clean(entry.get("CharacterRank")),
                (_number(entry.get("CurrentDKP"), 1), None, float(entry.get("CurrentDKP") or 0)),
                (_percent(entry.get("Calculated_30")), None, float(entry.get("Calculated_30") or 0)),
                (_percent(entry.get("Calculated_60")), None, float(entry.get("Calculated_60") or 0)),
                (_percent(entry.get("Calculated_90")), None, float(entry.get("Calculated_90") or 0)),
                (_percent(entry.get("Calculated_Life")), None, float(entry.get("Calculated_Life") or 0)),
            ))
        self._set_rows(self.standings_table, rows)
        self._filter_standings()

    def _populate_characters(self):
        if not hasattr(self, "character_selector"):
            return
        preferred = int((self._profile() or {}).get("character_id") or 0)
        dkp_by_id = {int(row.get("CharacterId") or 0): row for row in self._datasets["dkp"]}
        choices = list(dkp_by_id.values())
        if not choices:
            choices = self._datasets["characters"]
        choices.sort(key=lambda row: _clean(
            row.get("CharacterName") or row.get("Name")).casefold())
        self.character_selector.blockSignals(True)
        self.character_selector.clear()
        self.character_selector.addItem("Choose a character…", 0)
        for row in choices:
            char_id = int(row.get("CharacterId") or row.get("Id") or 0)
            name = _clean(row.get("CharacterName") or row.get("Name"))
            self.character_selector.addItem(name, char_id)
            self.character_selector.setItemData(
                self.character_selector.count() - 1, row, Qt.ItemDataRole.UserRole + 1)
        index = self.character_selector.findData(preferred)
        self.character_selector.setCurrentIndex(max(0, index))
        self.character_selector.blockSignals(False)
        self._update_overview()

    def _character_selected(self):
        char_id = int(self.character_selector.currentData() or 0)
        name = self.character_selector.currentText() if char_id else ""
        self._save_profile(character_id=char_id, character_name=name)
        for key in ("character_dkp", "character_items",
                    "character_adjustments", "character_raids"):
            self._datasets[key] = []
        self._update_overview()
        if char_id:
            self.client.fetch_character_details(char_id)

    def _selected_dkp(self):
        char_id = int(self.character_selector.currentData() or 0)
        return next((row for row in self._datasets["dkp"]
                     if int(row.get("CharacterId") or 0) == char_id), {})

    def _update_overview(self):
        row = self._selected_dkp()
        char_id = int(self.character_selector.currentData() or 0)
        if not row:
            for label in self.metric_values.values():
                label.setText("—")
            self.character_identity.setText("Choose a character")
            self._set_rows(self.character_loot, [])
            self._set_rows(self.character_raids, [])
            return
        name = _clean(row.get("CharacterName"))
        identity = " · ".join(part for part in (
            _clean(row.get("CharacterClass"), ""),
            f"Level {_number(row.get('CharacterLevel'))}",
            _clean(row.get("CharacterRank"), "")) if part)
        self.character_identity.setText(identity)
        values = {
            "dkp": _number(row.get("CurrentDKP"), 1),
            "30": _percent(row.get("Calculated_30")),
            "60": _percent(row.get("Calculated_60")),
            "90": _percent(row.get("Calculated_90")),
            "life": _percent(row.get("Calculated_Life")),
        }
        for key, value in values.items():
            self.metric_values[key].setText(value)
            self.metric_values[key].setAccessibleName(f"{key} value: {value}")
        loot_source = self._datasets["character_items"] or self._datasets["items"]
        loot = [item for item in loot_source
                if int(item.get("CharacterId") or 0) == char_id or
                _clean(item.get("CharacterName"), "").casefold() == name.casefold()]
        loot.sort(key=lambda item: str(item.get("Timestamp") or ""), reverse=True)
        self._set_rows(self.character_loot, [
            (_date_text(item.get("Timestamp")), _clean(item.get("ItemName")),
             _number(item.get("DKP"), 1), _clean(item.get("Raid"))) for item in loot[:100]])
        raids = self._datasets["character_raids"][:100]
        if not raids:
            # Keep useful guild context visible when a tenant does not expose
            # the optional character-raids route.
            raids = self._datasets["raids"][:100]
        self._set_rows(self.character_raids, [
            (_date_text(raid.get("Timestamp")), _clean(raid.get("Name")),
             _number(raid.get("DKPAwarded"), 1), _number(raid.get("DKPSpent"), 1))
            for raid in raids])

    def _populate_items(self):
        items = sorted(self._datasets["items"],
                       key=lambda item: str(item.get("Timestamp") or ""), reverse=True)
        self._set_rows(self.loot_table, [
            (_date_text(item.get("Timestamp")),
             (_clean(item.get("ItemName")), item, _clean(item.get("ItemName")).casefold()),
             _clean(item.get("CharacterName")),
             (_number(item.get("DKP"), 1), None, float(item.get("DKP") or 0)),
             _clean(item.get("Raid"))) for item in items])
        prices = [float(item.get("DKP")) for item in items
                  if isinstance(item.get("DKP"), (int, float))]
        summary = f"{len(items):,} loot records"
        if prices:
            summary += f" · median {statistics.median(prices):,.1f} DKP"
        self.loot_summary.setText(summary)
        self._filter_loot()

    def _populate_raids(self):
        raids = sorted(self._datasets["raids"],
                       key=lambda raid: str(raid.get("Timestamp") or ""), reverse=True)
        self._set_rows(self.raids_table, [
            (_date_text(raid.get("Timestamp")),
             (_clean(raid.get("Name")), raid, _clean(raid.get("Name")).casefold()),
             _clean((raid.get("Pool") or {}).get("Name") if isinstance(raid.get("Pool"), dict)
                    else raid.get("PoolName")),
             (_number(raid.get("ItemCount")), None, float(raid.get("ItemCount") or 0)),
             (_number(raid.get("DKPAwarded"), 1), None, float(raid.get("DKPAwarded") or 0)),
             (_number(raid.get("DKPSpent"), 1), None, float(raid.get("DKPSpent") or 0)),
             (_number(raid.get("TotalTicks")), None, float(raid.get("TotalTicks") or 0)))
            for raid in raids])
        self._filter_raids()

    def _populate_auctions(self):
        rows = []
        for auction in self._datasets["auctions"]:
            winners = _wins(auction) or [("No winner", None)]
            for winner, value in winners:
                rows.append((
                    _date_text(auction.get("EndTimestamp") or auction.get("Timestamp")),
                    (auction_item_name(auction), auction, auction_item_name(auction).casefold()),
                    winner,
                    (_number(value), None, float(value or 0)),
                    (_number(auction_id(auction)), None, float(auction_id(auction))),
                ))
        self._set_rows(self.auctions_table, rows)
        self._filter_auctions()

    def _populate_adjustments(self):
        adjustments = sorted(
            self._datasets["adjustments"],
            key=lambda row: str(row.get("Timestamp") or ""), reverse=True)
        self._set_rows(self.adjustments_table, [
            (_date_text(row.get("Timestamp")),
             _clean((row.get("Character") or {}).get("Name")
                    if isinstance(row.get("Character"), dict)
                    else row.get("CharacterName")),
             (_number(row.get("Value"), 1), None, float(row.get("Value") or 0)),
             (_clean(row.get("Name")), row, _clean(row.get("Name")).casefold()),
             _clean(row.get("Description"))) for row in adjustments])
        suffix = ""
        if len(adjustments) > self.MAX_TABLE_ROWS:
            suffix = f" · showing newest {self.MAX_TABLE_ROWS:,}"
        self.adjustments_hint.setText(
            f"{len(adjustments):,} adjustment records{suffix}")
        self._filter_adjustments()

    def _populate_active_auctions(self):
        selected_id = auction_id(self._selected_auction())
        rows = []
        linked_ids = {int(row.get("CharacterId") or row.get("Id") or 0)
                      for row in self._eligible_characters}
        for auction in self._datasets["active_auctions"]:
            bids = auction_bids(auction)
            values = [int(bid.get("Value") or 0) for bid in bids if isinstance(bid, dict)]
            mine = [int(bid.get("Value") or 0) for bid in bids if isinstance(bid, dict)
                    and int(bid.get("CharacterId") or 0) in linked_ids]
            rows.append((
                (auction_item_name(auction), auction, auction_item_name(auction).casefold()),
                _remaining_text(auction),
                (_number(len(bids)), None, len(bids)),
                (_number(max(values) if values else 0), None, max(values) if values else 0),
                (_number(max(mine)) if mine else "—", None, max(mine) if mine else -1),
            ))
        self._set_rows(self.active_table, rows)
        if selected_id:
            for row_index in range(self.active_table.rowCount()):
                item = self.active_table.item(row_index, 0)
                source = item.data(Qt.ItemDataRole.UserRole) if item else None
                if auction_id(source) == selected_id:
                    self.active_table.selectRow(row_index)
                    break
        self._auction_selected()
        if not self.client.authenticated:
            self._set_result("Sign in to load live auctions and place manual bids")
        elif not rows:
            self._set_result("Connected · no active auctions")
        else:
            self._set_result(f"{len(rows)} live auction{'s' if len(rows) != 1 else ''}")

    def _refresh_active_countdowns(self):
        for row_index in range(self.active_table.rowCount()):
            source = self.active_table.item(row_index, 0)
            timer = self.active_table.item(row_index, 1)
            auction = source.data(Qt.ItemDataRole.UserRole) if source else None
            if timer is not None and isinstance(auction, dict):
                timer.setText(_remaining_text(auction))

    def _update_eligible_characters(self):
        username = self.client.username.casefold()
        self._eligible_characters = [row for row in self._datasets["characters"]
                                     if username and _clean(row.get("User"), "").casefold() == username]
        preferred = int((self._profile() or {}).get("character_id") or 0)
        self.bid_character.clear()
        for row in sorted(self._eligible_characters,
                          key=lambda entry: _clean(entry.get("Name")).casefold()):
            char_id = int(row.get("CharacterId") or row.get("Id") or 0)
            self.bid_character.addItem(
                f"{_clean(row.get('Name'))} · {_clean(row.get('Rank'))}", char_id)
            self.bid_character.setItemData(
                self.bid_character.count() - 1, row, Qt.ItemDataRole.UserRole + 1)
        index = self.bid_character.findData(preferred)
        if index >= 0:
            self.bid_character.setCurrentIndex(index)
        enabled = self.client.authenticated and bool(self._eligible_characters)
        self.bid_character.setEnabled(enabled)
        self.bid_button.setEnabled(enabled)
        self.withdraw_button.setEnabled(enabled)

    # ----- bids and watchlist ------------------------------------------
    def _selected_auction(self):
        row = self.active_table.currentRow()
        item = self.active_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, dict) else {}

    def _selected_bid_character(self):
        row = self.bid_character.currentData(Qt.ItemDataRole.UserRole + 1)
        return row if isinstance(row, dict) else {}

    def _my_bid(self, auction, character=None):
        character = character or self._selected_bid_character()
        char_id = int(character.get("CharacterId") or character.get("Id") or 0)
        mine = [bid for bid in auction_bids(auction) if isinstance(bid, dict)
                and int(bid.get("CharacterId") or 0) == char_id]
        return max(mine, key=lambda bid: int(bid.get("Value") or 0)) if mine else {}

    def _auction_selected(self):
        auction = self._selected_auction()
        if not auction:
            self.bid_selection.setText("Select a live auction")
            self._set_rows(self.bid_table, [])
            return
        details = [auction_item_name(auction), _remaining_text(auction)]
        bid_type = _clean(auction.get("BidType"), "")
        if bid_type:
            details.append(bid_type)
        quantity = int(auction.get("ItemQuantity") or 1)
        if quantity > 1:
            details.append(f"×{quantity}")
        minimum = auction.get("MinimumBid")
        if minimum not in (None, ""):
            details.append(f"min {_number(minimum)}")
        self.bid_selection.setText(" · ".join(details))
        bids = sorted(
            (bid for bid in auction_bids(auction) if isinstance(bid, dict)),
            key=lambda bid: int(bid.get("Value") or 0), reverse=True)
        self._set_rows(self.bid_table, [
            ((_clean(bid.get("CharacterName") or bid.get("Name")), bid,
              _clean(bid.get("CharacterName") or bid.get("Name")).casefold()),
             _clean(bid.get("Rank")),
             (_number(bid.get("Value")), None, float(bid.get("Value") or 0)),
             (_number(bid.get("Priority")), None, float(bid.get("Priority") or 0)),
             _date_text(bid.get("Timestamp") or bid.get("Date"), with_time=True))
            for bid in bids])
        existing = self._my_bid(auction)
        if existing:
            self.bid_value.setValue(max(1, int(existing.get("Value") or 1)))
            self.bid_button.setText("Update bid")
        else:
            self.bid_button.setText("Place bid")

    def _place_or_update_bid(self):
        auction = self._selected_auction()
        character = self._selected_bid_character()
        if not auction or not character:
            self._set_result("Select a live auction and linked character", announce=True)
            return
        amount = self.bid_value.value()
        existing = self._my_bid(auction, character)
        verb = "Update" if existing else "Place"
        prompt = (f"{verb} a {amount:,} DKP bid on {auction_item_name(auction)} "
                  f"as {_clean(character.get('Name'))}?")
        if QMessageBox.question(self, f"{verb} OpenDKP bid", prompt) != \
                QMessageBox.StandardButton.Yes:
            return
        if existing:
            self.client.update_bid(auction_id(auction), existing, amount)
        else:
            self.client.place_bid(
                auction_id(auction), character, amount, self.bid_priority.value())

    def _withdraw_bid(self):
        auction = self._selected_auction()
        character = self._selected_bid_character()
        existing = self._my_bid(auction, character)
        if not existing:
            self._set_result("The selected character has no bid to withdraw", announce=True)
            return
        if QMessageBox.question(
                self, "Withdraw OpenDKP bid",
                f"Withdraw {_clean(character.get('Name'))}'s bid on "
                f"{auction_item_name(auction)}?") == QMessageBox.StandardButton.Yes:
            self.client.delete_bid(auction_id(auction), existing)

    def _watch_items(self):
        return list((self._profile() or {}).get("watch_items", []))

    def _load_watchlist(self):
        self.watch_list.clear()
        self.watch_list.addItems(self._watch_items())

    def _add_watch(self):
        value = " ".join(self.watch_entry.text().split())[:96]
        watches = self._watch_items()
        if not value or value.casefold() in {item.casefold() for item in watches}:
            return
        watches.append(value)
        self._save_profile(watch_items=watches[:64])
        self.watch_entry.clear()
        self._load_watchlist()
        self._set_result(f"Watching for {value}", announce=True)

    def _remove_watch(self):
        current = self.watch_list.currentItem()
        if current is None:
            return
        value = current.text()
        watches = [item for item in self._watch_items()
                   if item.casefold() != value.casefold()]
        self._save_profile(watch_items=watches)
        self._load_watchlist()
        self._set_result(f"Stopped watching for {value}", announce=True)

    # ----- filtering and status ----------------------------------------
    def _filter_table(self, table, text):
        terms = str(text or "").casefold().split()
        visible = 0
        for row in range(table.rowCount()):
            haystack = " ".join(
                table.item(row, column).text()
                for column in range(table.columnCount())
                if table.item(row, column) is not None).casefold()
            show = all(term in haystack for term in terms)
            table.setRowHidden(row, not show)
            visible += int(show)
        self._set_result(f"{visible:,} matching row{'s' if visible != 1 else ''}")

    def _filter_standings(self):
        self._filter_table(self.standings_table, self.standings_search.text())

    def _filter_loot(self):
        self._filter_table(self.loot_table, self.loot_search.text())

    def _filter_raids(self):
        self._filter_table(self.raids_table, self.raids_search.text())

    def _filter_auctions(self):
        self._filter_table(self.auctions_table, self.auctions_search.text())

    def _filter_adjustments(self):
        self._filter_table(self.adjustments_table, self.adjustments_search.text())

    def _tab_changed(self, index):
        if self.tabs.tabText(index) == "Adjustments" and self.client.slug \
                and not self._adjustments_loaded:
            self._adjustments_loaded = True
            self.client.fetch_adjustments()

    def _guild_name(self):
        return _clean(self._guild_details.get("Name"), self.client.slug or "OpenDKP")

    def _set_status(self, text, state, announce=False):
        self.guild_status.setText(str(text))
        self.guild_status.setProperty("state", state)
        self.guild_status.style().unpolish(self.guild_status)
        self.guild_status.style().polish(self.guild_status)
        self.guild_status.setAccessibleName(str(text))
        if announce:
            self._announce(str(text), state == "error")

    def _set_result(self, text, announce=False):
        self.result_status.setText(str(text))
        self.result_status.setAccessibleName(str(text))
        if announce:
            self._announce(str(text))

    def _announce(self, text, assertive=False):
        if not QApplication.instance() or not text:
            return
        event = QAccessibleAnnouncementEvent(self, str(text))
        event.setPoliteness(
            QAccessible.AnnouncementPoliteness.Assertive if assertive else
            QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)

    def _clear_views(self):
        self._guild_details = {}
        for key in self._datasets:
            self._datasets[key] = []
        for table in (
                self.standings_table, self.active_table, self.auctions_table,
                self.bid_table,
                self.loot_table, self.raids_table, self.adjustments_table,
                self.character_loot, self.character_raids):
            table.setRowCount(0)
        self.character_selector.clear()
        self.bid_character.clear()
        self.site_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.sign_in_button.setEnabled(False)
