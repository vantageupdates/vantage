"""On-demand Project 1999 quest catalog and persistent quest checklist."""

from __future__ import annotations

import hashlib
import html
import json
import re
import webbrowser
from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTabWidget,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir
from vantage.helpers.responsive import ensure_tab_tooltips, scrollable
from vantage.parsers.market import _announce_accessible


P99_WIKI_API_ROOT = "https://wiki.project1999.com/api.php"
P99_WIKI_PAGE_ROOT = "https://wiki.project1999.com/"
QUEST_CATEGORY = "Category:Quests"
QUEST_CATALOG_CACHE_VERSION = 1
NETWORK_TIMEOUT_MS = 15000
MAX_CATALOG_PAGES = 10


def _plain_wiki(value):
    """Return readable text for the small subset of MediaWiki used in quests."""
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[https?://[^\s\]]+(?:\s+([^\]]+))?\]",
                  lambda match: match.group(1) or "", text)
    text = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]",
                  lambda match: match.group(2), text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda match: match.group(1), text)
    text = re.sub(r"\{\{YouGainExperience\}\}", "Experience reward", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"\{\{:[^{}]+\}\}", "", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,5}", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines()
                     if line.strip())


def _section(source, names):
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"^==+\s*(?:{alternatives})\s*==+\s*$\n?(.*?)(?=^==+[^=].*?==+\s*$|\Z)",
        str(source or ""), re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _quest_metadata(source):
    table = re.search(
        r"\{\|[^\n]*questTopTable.*?\n\|\}", str(source or ""),
        re.IGNORECASE | re.DOTALL)
    if not table:
        return {}
    result = {}
    for label, value in re.findall(
            r"!\s*'{0,5}\s*([^\n']+?)\s*:?[ \t]*'{0,5}\s*\n"
            r"\|\s*(.*?)(?=\n\|-|\n\|\})",
            table.group(0), re.DOTALL):
        clean_label = _plain_wiki(label).rstrip(":").strip()
        clean_value = _plain_wiki(value).replace("\n", ", ").strip()
        if clean_label and clean_value:
            result[clean_label] = clean_value
    return result


def _quest_steps(source):
    body = _section(source, (
        "TLDR; Walkthrough", "TLDR Walkthrough", "Short Walkthrough",
        "Walkthrough", "Quest Walkthrough"))
    if not body:
        body = str(source or "")
    steps = []
    for raw in body.splitlines():
        match = re.match(r"^\s*([*#]+)\s+(.+)$", raw)
        if not match:
            continue
        text = _plain_wiki(match.group(2)).replace("\n", " ").strip(" -")
        if not text or text.casefold().startswith(("your faction", "category:")):
            continue
        depth = max(0, len(match.group(1)) - 1)
        prefix = "↳ " if depth else ""
        candidate = (prefix + text)[:360]
        if candidate.casefold() not in {item.casefold() for item in steps}:
            steps.append(candidate)
        if len(steps) >= 96:
            break
    if steps:
        return steps

    for raw in body.splitlines():
        clean = _plain_wiki(raw).replace("\n", " ")
        if re.match(r"^(?:Step|Stage|The Final Stage)\b", clean,
                    re.IGNORECASE):
            steps.append(clean[:360])
    return steps[:96]


def _wiki_links(value):
    found = []
    for target, label in re.findall(
            r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]",
            str(value or "")):
        name = _plain_wiki(label or target)
        if name and name.casefold() not in {item.casefold() for item in found}:
            found.append(name)
    return found


def parse_quest_wikitext(source, fallback_title=""):
    """Build a deterministic summary and checklist from a P99 quest page."""
    source = str(source or "")
    metadata = _quest_metadata(source)
    steps = _quest_steps(source)
    reward_source = _section(source, ("Reward", "Rewards"))
    rewards = _wiki_links(reward_source)[:12]
    title = str(fallback_title or "Quest").replace("_", " ").strip()

    lead_source = re.split(r"^==+", source, maxsplit=1,
                           flags=re.MULTILINE)[0]
    lead_source = re.sub(r"\{\|.*?\|\}", "", lead_source, flags=re.DOTALL)
    lead = _plain_wiki(lead_source)
    lead = " ".join(lead.split())[:560]
    facts = []
    for wanted in ("Start Zone", "Quest Giver", "Minimum Level", "Classes"):
        value = next((value for key, value in metadata.items()
                      if key.casefold() == wanted.casefold()), "")
        if value:
            facts.append(f"{wanted}: {value}")
    summary_parts = facts
    if rewards:
        summary_parts.append("Rewards: " + ", ".join(rewards))
    if lead:
        summary_parts.append(lead)
    if not summary_parts and steps:
        summary_parts.append("First steps: " + "; ".join(
            step.removeprefix("↳ ") for step in steps[:3]))
    return {
        "title": title,
        "metadata": metadata,
        "rewards": rewards,
        "summary": "\n\n".join(summary_parts) or
                   "No concise summary was available on this Wiki page.",
        "steps": steps,
        "wiki_url": P99_WIKI_PAGE_ROOT + quote(
            title.replace(" ", "_"), safe="()'"),
    }


def parse_quest_catalog_payload(payload):
    """Extract quest titles and continuation from a MediaWiki API response."""
    if not isinstance(payload, dict):
        return [], ""
    members = payload.get("query", {}).get("categorymembers", [])
    titles = [str(member.get("title", "")).strip() for member in members
              if isinstance(member, dict) and str(member.get("title", "")).strip()]
    continuation = str(
        payload.get("continue", {}).get("cmcontinue") or
        payload.get("query-continue", {}).get("categorymembers", {}).get(
            "cmcontinue") or "")
    return titles, continuation


def _step_key(text):
    return hashlib.sha256(str(text).strip().casefold().encode("utf-8")).hexdigest()[:16]


class QuestChecklistWindow(QWidget):
    """Small always-on-top, independently movable checklist."""

    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Tool |
                        Qt.WindowType.WindowStaysOnTopHint |
                        Qt.WindowType.WindowCloseButtonHint)
        self.owner = owner
        self.setObjectName("QuestChecklistWindow")
        self.setWindowTitle("Quest Checklist · Vantage")
        self.setWindowIcon(game_icon("ph-quest-scroll"))
        self.setMinimumSize(300, 220)
        state = config.data["quests"].get("checklist", {})
        geometry = state.get("geometry", [80, 80, 380, 480])
        self.setGeometry(*geometry)
        self._boxes = []
        self._progress_announce_timer = QTimer(self)
        self._progress_announce_timer.setSingleShot(True)
        self._progress_announce_timer.setInterval(220)
        self._progress_announce_timer.timeout.connect(
            self._announce_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title = QLabel("No quest selected")
        self.title.setObjectName("QuestChecklistTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.progress = QLabel("Choose a quest in the Quests window.")
        self.progress.setObjectName("QuestChecklistProgress")
        self.progress.setAccessibleName("Quest checklist progress")
        layout.addWidget(self.progress)

        self.steps_body = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_body)
        self.steps_layout.setContentsMargins(2, 2, 2, 2)
        self.steps_layout.setSpacing(4)
        self.steps_layout.addStretch(1)
        layout.addWidget(scrollable(self.steps_body, "QuestChecklistScroll"), 1)

        actions = QHBoxLayout()
        reset = QPushButton("Reset checks")
        reset.setIcon(game_icon("refresh"))
        reset.setToolTip("Uncheck every step after confirmation")
        reset.setAccessibleName("Reset all quest checklist steps")
        reset.clicked.connect(self._confirm_reset)
        actions.addWidget(reset)
        clear = QPushButton("Clear quest")
        clear.setIcon(game_icon("trash"))
        clear.setToolTip("Remove the active floating checklist after confirmation")
        clear.setAccessibleName("Clear the active quest checklist")
        clear.clicked.connect(self._confirm_clear)
        actions.addWidget(clear)
        layout.addLayout(actions)
        self.restore()

    def restore(self):
        state = config.data["quests"].get("checklist", {})
        title = str(state.get("title", "") or "")
        steps = state.get("steps", [])
        checked = set(state.get("checked", []))
        self.set_quest(title, steps, checked, save=False)

    def set_quest(self, title, steps, checked=(), save=True):
        while self.steps_layout.count() > 1:
            item = self.steps_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._boxes = []
        checked = set(checked)
        for number, text in enumerate(steps, 1):
            box = QCheckBox(f"{number}. {text}")
            box.setProperty("step_key", _step_key(text))
            box.setChecked(box.property("step_key") in checked)
            box.setAccessibleName(f"Quest step {number}: {text}")
            box.stateChanged.connect(self._changed)
            self.steps_layout.insertWidget(self.steps_layout.count() - 1, box)
            self._boxes.append(box)
        self.title.setText(title or "No quest selected")
        self._update_progress()
        if save:
            self._save_state()

    def _changed(self, _state):
        self._update_progress()
        self._save_state()
        self._progress_announce_timer.start()

    def _announce_progress(self):
        _announce_accessible(self.progress, self.progress.text())

    def _update_progress(self):
        total = len(self._boxes)
        done = sum(box.isChecked() for box in self._boxes)
        if total:
            message = f"{done} of {total} steps complete"
        else:
            message = "This Wiki page has no structured walkthrough steps."
        self.progress.setText(message)
        self.progress.setAccessibleDescription(message)

    def _save_state(self):
        if not hasattr(self, "title") or not hasattr(self, "_boxes"):
            return
        state = config.data["quests"].setdefault("checklist", {})
        state["title"] = self.title.text() if self._boxes else ""
        state["steps"] = [box.text().split(". ", 1)[-1] for box in self._boxes]
        state["checked"] = [box.property("step_key") for box in self._boxes
                            if box.isChecked()]
        state["geometry"] = [self.x(), self.y(), self.width(), self.height()]
        config.save()

    def _confirm_reset(self):
        if not self._boxes:
            return
        answer = QMessageBox.question(
            self, "Reset quest progress?",
            "Uncheck every step in this quest checklist?",
            QMessageBox.StandardButton.Reset | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Reset:
            for box in self._boxes:
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
            self._update_progress()
            self._save_state()
            self._progress_announce_timer.stop()
            _announce_accessible(self.progress, "Quest progress reset; no steps complete")

    def _confirm_clear(self):
        if not self._boxes:
            return
        answer = QMessageBox.question(
            self, "Clear quest checklist?",
            "Remove this quest and its saved progress from the floating checklist?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.set_quest("", [])
            self._progress_announce_timer.stop()
            _announce_accessible(self.progress, "Floating quest checklist cleared")

    def focus_first_unchecked(self):
        target = next(
            (box for box in self._boxes if not box.isChecked()),
            self._boxes[0] if self._boxes else None)
        if target:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _return_focus(self):
        button = getattr(self.owner, "checklist_button", None)
        if button is not None and self.owner.isVisible():
            self.owner.raise_()
            self.owner.activateWindow()
            button.setFocus(Qt.FocusReason.OtherFocusReason)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._save_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._save_state()

    def closeEvent(self, event):
        self._save_state()
        QTimer.singleShot(0, self._return_focus)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            QTimer.singleShot(0, self._return_focus)
            event.accept()
            return
        super().keyPressEvent(event)


class Quests(ParserWindow):
    """Independent P99 quest catalog; network work starts on first use."""

    name = "quests"
    _allow_clickthrough = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quests · Project 1999")
        self._title.setText("Quests")
        self._network = QNetworkAccessManager(self)
        self._catalog = []
        self._catalog_loading = False
        self._catalog_seen = set()
        self._catalog_pages = 0
        self._catalog_reply = None
        self._quest_reply = None
        self._current_quest = None
        self._checklist = QuestChecklistWindow(self)
        self._filter_announce_timer = QTimer(self)
        self._filter_announce_timer.setSingleShot(True)
        self._filter_announce_timer.setInterval(260)
        self._filter_announce_timer.timeout.connect(
            self._announce_filter_count)
        self._build_ui()
        self._load_cached_catalog()

    def _build_ui(self):
        controls = QFrame()
        controls.setObjectName("QuestControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(7, 6, 7, 6)
        controls_layout.setSpacing(5)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search all Project 1999 quests…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search Project 1999 quests")
        self.search.setToolTip("Filter the cached Project 1999 quest catalog")
        clear_button = self.search.findChild(QToolButton)
        if clear_button:
            clear_button.setAccessibleName("Clear quest search")
            clear_button.setToolTip("Show every cached quest")
        self.search.textChanged.connect(self._filter_catalog)
        controls_layout.addWidget(self.search, 1)
        refresh = QPushButton("Refresh catalog")
        refresh.setIcon(game_icon("refresh"))
        refresh.setAccessibleName("Refresh Project 1999 quest catalog")
        refresh.setToolTip("Download the current quest title catalog from the Wiki")
        refresh.clicked.connect(lambda: self._fetch_catalog(force=True))
        controls_layout.addWidget(refresh)
        self.content.addWidget(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 4, 3, 6)
        self.catalog_status = QLabel("Quest catalog loads when this window opens.")
        self.catalog_status.setWordWrap(True)
        self.catalog_status.setAccessibleName("Quest catalog status")
        left_layout.addWidget(self.catalog_status)
        self.match_count = QLabel("0 matching quests")
        self.match_count.setObjectName("QuestMatchCount")
        self.match_count.setAccessibleName("Quest search result count")
        left_layout.addWidget(self.match_count)
        self.quest_list = QListWidget()
        self.quest_list.setAccessibleName("Project 1999 quest results")
        self.quest_list.setToolTip("Select a quest to load its summary and steps")
        self.quest_list.currentItemChanged.connect(self._quest_selected)
        left_layout.addWidget(self.quest_list, 1)
        splitter.addWidget(left)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(3, 4, 6, 6)
        self.quest_title = QLabel("Choose a quest")
        self.quest_title.setObjectName("QuestDetailTitle")
        self.quest_title.setWordWrap(True)
        right_layout.addWidget(self.quest_title)
        self.tabs = QTabWidget()
        self.summary = QTextBrowser()
        self.summary.setAccessibleName("Selected quest summary")
        self.summary.setToolTip(
            "Concise quest details extracted from the Project 1999 Wiki page")
        self.summary.setOpenExternalLinks(True)
        self.summary.setText(
            "Select a quest to load a concise summary from Project 1999 Wiki.")
        self.steps = QListWidget()
        self.steps.setAccessibleName("Selected quest walkthrough steps")
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.steps, "Steps")
        ensure_tab_tooltips(self.tabs, {
            "Summary": "Quest giver, zone, level, rewards, and concise Wiki summary",
            "Steps": "Structured steps extracted from the Wiki walkthrough",
        })
        right_layout.addWidget(self.tabs, 1)
        detail_actions = QHBoxLayout()
        self.wiki_button = QPushButton("Open Wiki page")
        self.wiki_button.setIcon(game_icon("ph-file-search"))
        self.wiki_button.setEnabled(False)
        self.wiki_button.setAccessibleName("Open selected quest on Project 1999 Wiki")
        self.wiki_button.setToolTip("Open the full source page in your browser")
        self.wiki_button.clicked.connect(self._open_wiki)
        detail_actions.addWidget(self.wiki_button)
        self.checklist_button = QPushButton("Floating checklist")
        self.checklist_button.setIcon(game_icon("check"))
        self.checklist_button.setEnabled(False)
        self.checklist_button.setAccessibleName(
            "Open selected quest as a floating checklist")
        self.checklist_button.setToolTip(
            "Keep the selected quest steps always on top and save progress")
        self.checklist_button.clicked.connect(self._open_checklist)
        detail_actions.addWidget(self.checklist_button)
        right_layout.addLayout(detail_actions)
        self.source_note = QLabel(
            "Community Wiki data can be incomplete or inaccurate; verify critical turn-ins.")
        self.source_note.setWordWrap(True)
        self.source_note.setObjectName("QuestSourceNote")
        right_layout.addWidget(self.source_note)
        splitter.addWidget(right)
        splitter.setSizes([300, 590])
        self.content.addWidget(splitter, 1)

    @property
    def _catalog_cache_path(self):
        return data_dir("cache", "wiki-quests") / "catalog.json"

    def _quest_cache_path(self, title):
        digest = hashlib.sha256(title.casefold().encode("utf-8")).hexdigest()[:20]
        return data_dir("cache", "wiki-quests") / f"{digest}.json"

    def _load_cached_catalog(self):
        try:
            payload = json.loads(self._catalog_cache_path.read_text("utf-8"))
            if payload.get("version") == QUEST_CATALOG_CACHE_VERSION:
                self._set_catalog(payload.get("titles", []), "cached")
        except (OSError, ValueError, TypeError):
            pass

    def _set_catalog(self, titles, source, announce=False):
        unique = sorted({str(title).strip() for title in titles if str(title).strip()},
                        key=str.casefold)
        self._catalog = unique
        self._filter_catalog()
        self.catalog_status.setText(
            f"{len(unique):,} quests · {source} · select one for details")
        self.catalog_status.setAccessibleDescription(self.catalog_status.text())
        if announce:
            _announce_accessible(self.catalog_status, self.catalog_status.text())

    def _filter_catalog(self, _text=None):
        needle = self.search.text().strip().casefold() if hasattr(self, "search") else ""
        selected = self.quest_list.currentItem().text() \
            if self.quest_list.currentItem() else ""
        self.quest_list.blockSignals(True)
        self.quest_list.clear()
        for title in self._catalog:
            if needle and needle not in title.casefold():
                continue
            self.quest_list.addItem(title)
        matches = self.quest_list.findItems(selected, Qt.MatchFlag.MatchExactly)
        if matches:
            self.quest_list.setCurrentItem(matches[0])
        self.quest_list.blockSignals(False)
        count = self.quest_list.count()
        count_text = f"{count:,} matching quest" + ("" if count == 1 else "s")
        self.match_count.setText(count_text)
        self.match_count.setAccessibleDescription(count_text)
        if _text is not None:
            self._filter_announce_timer.start()

    def _announce_filter_count(self):
        _announce_accessible(self.match_count, self.match_count.text())

    def _api_url(self, parameters):
        url = QUrl(P99_WIKI_API_ROOT)
        query = QUrlQuery()
        for key, value in parameters.items():
            if value:
                query.addQueryItem(key, str(value))
        url.setQuery(query)
        return url

    def _request(self, url):
        request = QNetworkRequest(url)
        request.setTransferTimeout(NETWORK_TIMEOUT_MS)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                          "Vantage/1.44.48 (vantagecompanion@gmail.com)")
        return self._network.get(request)

    def _fetch_catalog(self, force=False):
        if self._catalog_loading:
            return
        if self._catalog and not force:
            return
        self._catalog_loading = True
        self._catalog_seen = set()
        self._catalog_pages = 0
        self.catalog_status.setText("Loading quest catalog from Project 1999 Wiki…")
        _announce_accessible(self.catalog_status, self.catalog_status.text())
        self._fetch_catalog_page("")

    def _fetch_catalog_page(self, continuation):
        self._catalog_pages += 1
        self._catalog_reply = self._request(self._api_url({
            "action": "query", "list": "categorymembers",
            "cmtitle": QUEST_CATEGORY, "cmnamespace": "0", "cmlimit": "max",
            "cmcontinue": continuation, "format": "json",
        }))
        self._catalog_reply.finished.connect(self._catalog_page_finished)

    def _catalog_page_finished(self):
        reply = self.sender()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._catalog_loading = False
            self.catalog_status.setText(
                "Wiki unavailable · using the offline quest catalog" if self._catalog
                else "Wiki unavailable · no offline quest catalog yet")
            _announce_accessible(
                self.catalog_status, self.catalog_status.text(), assertive=True)
            reply.deleteLater()
            return
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            titles, continuation = parse_quest_catalog_payload(payload)
            self._catalog_seen.update(titles)
        except (UnicodeDecodeError, ValueError, TypeError):
            titles, continuation = [], ""
        reply.deleteLater()
        if continuation and self._catalog_pages < MAX_CATALOG_PAGES:
            self.catalog_status.setText(
                f"Loading quest catalog… {len(self._catalog_seen):,} found")
            self._fetch_catalog_page(continuation)
            return
        self._catalog_loading = False
        if self._catalog_seen:
            self._set_catalog(self._catalog_seen, "updated now", announce=True)
            cache = self._catalog_cache_path
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({
                    "version": QUEST_CATALOG_CACHE_VERSION,
                    "titles": self._catalog,
                }, ensure_ascii=False, indent=2), "utf-8")
            except OSError:
                # The in-memory catalog remains fully usable if a locked-down
                # profile prevents offline caching.
                pass
        else:
            self.catalog_status.setText(
                "Wiki returned no quest titles · using the offline catalog"
                if self._catalog else
                "Wiki returned no quest titles · try Refresh catalog again")
            _announce_accessible(
                self.catalog_status, self.catalog_status.text(), assertive=True)

    def _quest_selected(self, current, _previous):
        if current is None:
            return
        self._load_quest(current.text())

    def _load_quest(self, title):
        cache = self._quest_cache_path(title)
        try:
            cached = json.loads(cache.read_text("utf-8"))
            if cached.get("wikitext"):
                self._show_quest(parse_quest_wikitext(
                    cached["wikitext"], cached.get("title", title)))
                return
        except (OSError, ValueError, TypeError):
            pass
        self.quest_title.setText(title)
        self.summary.setText("Loading this quest from Project 1999 Wiki…")
        _announce_accessible(
            self.summary, f"Loading quest: {title}")
        self.steps.clear()
        self.wiki_button.setEnabled(False)
        self.checklist_button.setEnabled(False)
        if self._quest_reply and self._quest_reply.isRunning():
            self._quest_reply.abort()
        self._quest_reply = self._request(self._api_url({
            "action": "parse", "page": title, "prop": "wikitext",
            "format": "json",
        }))
        self._quest_reply.setProperty("quest_title", title)
        self._quest_reply.finished.connect(self._quest_finished)

    def _quest_finished(self):
        reply = self.sender()
        if reply is not self._quest_reply:
            reply.deleteLater()
            return
        title = str(reply.property("quest_title") or "Quest")
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.summary.setText(
                "This quest could not be loaded. Check the connection and select it again.")
            _announce_accessible(
                self.summary, f"Could not load {title} from the Wiki", assertive=True)
            reply.deleteLater()
            return
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse", {})
            wikitext = parsed.get("wikitext", {}).get("*", "")
            resolved_title = parsed.get("title", title)
            quest = parse_quest_wikitext(wikitext, resolved_title)
            cache = self._quest_cache_path(title)
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({
                    "title": resolved_title, "wikitext": wikitext,
                }, ensure_ascii=False), "utf-8")
            except OSError:
                pass
            self._show_quest(quest)
        except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
            self.summary.setText("The Wiki returned quest data Vantage could not read.")
            _announce_accessible(
                self.summary, f"Could not read Wiki data for {title}", assertive=True)
        reply.deleteLater()

    def _show_quest(self, quest):
        self._current_quest = quest
        self.quest_title.setText(quest["title"])
        self.quest_title.setAccessibleName(f"Selected quest: {quest['title']}")
        self.summary.setPlainText(quest["summary"])
        self.steps.clear()
        for number, step in enumerate(quest["steps"], 1):
            item = QListWidgetItem(f"{number}. {step}")
            item.setToolTip(step)
            self.steps.addItem(item)
        if not quest["steps"]:
            self.steps.addItem(
                "No structured walkthrough was found. Open the full Wiki page for details.")
        self.wiki_button.setEnabled(True)
        self.checklist_button.setEnabled(bool(quest["steps"]))
        _announce_accessible(
            self.quest_title,
            f"Loaded {quest['title']}; {len(quest['steps'])} checklist steps")

    def _open_wiki(self):
        if self._current_quest:
            webbrowser.open(self._current_quest["wiki_url"])

    def _open_checklist(self):
        if not self._current_quest or not self._current_quest["steps"]:
            return
        state = config.data["quests"].get("checklist", {})
        checked = state.get("checked", []) \
            if state.get("title") == self._current_quest["title"] else []
        self._checklist.set_quest(
            self._current_quest["title"], self._current_quest["steps"], checked)
        self._checklist.show()
        self._checklist.raise_()
        self._checklist.activateWindow()
        QTimer.singleShot(0, self._checklist.focus_first_unchecked)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(
            0, lambda: self.search.setFocus(Qt.FocusReason.OtherFocusReason))
        if not self._catalog:
            self._fetch_catalog()

    def parse(self, _timestamp, _text):
        """Quests is reference-only and does not inspect EverQuest logs."""
