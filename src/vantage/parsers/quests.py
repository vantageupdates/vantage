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
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

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
NETWORK_RETRY_LIMIT = 1
MAX_CATALOG_PAGES = 10
MAX_QUEST_STEPS = 180

ACTION_VERBS = (
    "acquire", "ask", "bring", "buy", "camp", "cast", "collect",
    "combine", "create", "deliver", "equip", "find", "follow", "forage",
    "get", "give", "go", "hail", "hand", "head", "kill", "loot", "make",
    "obtain", "purchase", "receive", "return", "run", "say", "show",
    "slay", "spawn", "speak", "take", "talk", "trade", "travel",
    "trigger", "turn in", "use", "wait", "zone")
ACTION_VERB_PATTERN = "|".join(
    re.escape(verb) for verb in sorted(ACTION_VERBS, key=len, reverse=True))


def _clean_template_value(value):
    text = str(value or "").strip()
    text = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]",
                  lambda match: match.group(2), text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda match: match.group(1), text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(re.sub(r"'{2,5}", "", text)).strip()


def _render_wiki_template(match):
    """Preserve useful template parameters instead of silently erasing them."""
    parts = [part.strip() for part in match.group(1).split("|")]
    name = parts[0].strip()
    if name.startswith(":"):
        return _clean_template_value(name[1:])
    folded = name.casefold().replace("_", " ").strip()
    if folded in {
            "checkboxlist", "end", "classic era", "kunark era",
            "velious era", "nerfed", "yougainexperience"}:
        return "Experience reward" if folded == "yougainexperience" else ""

    positional = []
    named = {}
    for raw in parts[1:]:
        if "=" in raw:
            key, value = raw.split("=", 1)
            key = _clean_template_value(key).casefold().strip()
            value = _clean_template_value(value)
            if key and value:
                named[key] = value
        else:
            value = _clean_template_value(raw)
            if value:
                positional.append(value)

    if folded in {"loc", "location"}:
        coordinates = []
        for key in ("x", "y", "z"):
            if named.get(key):
                coordinates.append(named[key])
        coordinates.extend(positional)
        return ", ".join(dict.fromkeys(coordinates)) or "location on Wiki page"

    if folded in {"npc", "item", "zone"}:
        display = (named.pop("name", "") or named.pop("display", "") or
                   (positional.pop(0) if positional else name.title()))
        context = positional + [
            f"{key.replace('_', ' ')}: {value}"
            for key, value in named.items()]
        return display + (f" ({'; '.join(context)})" if context else "")

    readable = positional + [
        f"{key.replace('_', ' ')}: {value}" for key, value in named.items()]
    if readable:
        return f"{name}: " + "; ".join(readable)
    return f"[Wiki template: {name}; open the full Wiki page]"


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
    # Resolve innermost templates repeatedly so nested meaningful values are
    # retained. A small cap prevents malformed cyclic-looking markup from
    # consuming unbounded work.
    for _ in range(8):
        updated = re.sub(r"\{\{([^{}]*)\}\}", _render_wiki_template, text)
        if updated == text:
            break
        text = updated
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,5}", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines()
                     if line.strip())


def _section(source, names):
    """Return a section including subsections until a peer/parent heading."""
    source = str(source or "")
    wanted = {str(name).strip().casefold() for name in names}
    headings = list(re.finditer(
        r"^(?P<marks>={2,6})\s*(?P<title>.*?)\s*(?P=marks)\s*$",
        source, re.MULTILINE))
    for index, heading in enumerate(headings):
        if _plain_wiki(heading.group("title")).casefold() not in wanted:
            continue
        level = len(heading.group("marks"))
        end = len(source)
        for following in headings[index + 1:]:
            if len(following.group("marks")) <= level:
                end = following.start()
                break
        return source[heading.end():end].strip()
    return ""


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


def _action_match(text):
    clean = str(text or "").strip()
    if not clean:
        return None
    folded = clean.casefold()
    if folded.startswith(("your faction ", "category:", "experience reward")):
        return None
    direct = re.match(
        rf"^(?:(?:then|next|finally)\s+)?(?:you\s+)?"
        rf"(?:(?:must|should|need to|can)\s+)?({ACTION_VERB_PATTERN})\b",
        clean, re.IGNORECASE)
    temporal = re.match(
        rf"^(?:once|when|after)\b.*?(?:,\s*|\byou\s+"
        rf"(?:must|should|need to|can)\s+)({ACTION_VERB_PATTERN})\b",
        clean, re.IGNORECASE)
    spoken = re.match(r"^You\s+say\b", clean, re.IGNORECASE)
    after_alert = re.search(
        rf":\s*(?:you\s+)?({ACTION_VERB_PATTERN})\b", clean,
        re.IGNORECASE)
    if folded.startswith(("warning", "note", "be careful", "do not", "never")):
        return after_alert
    return direct or temporal or spoken or after_alert


def _record(text, depth=0, kind="action", group=""):
    return {
        "text": str(text).strip(),
        "depth": max(0, int(depth)),
        "kind": "group" if kind == "group" else "action",
        "group": str(group or "").strip(),
    }


def _split_action_sentences(text):
    """Keep actionable sentences complete instead of truncating long prose."""
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    pieces = re.split(r"(?<=[.!?])\s+(?=(?:['\"]?[A-Z]))", clean)
    actions = []
    for piece in pieces:
        piece = piece.strip()
        if _action_match(piece):
            actions.append(piece)
            continue
        if actions and piece.startswith("(") and piece.endswith(")"):
            actions[-1] += " " + piece
            continue
        # One Wiki line frequently combines context followed by multiple
        # imperative clauses without reliable sentence punctuation.
        embedded = re.search(
            rf"\b((?:{ACTION_VERB_PATTERN})\b.*)$", piece, re.IGNORECASE)
        if embedded and re.search(r"[.;:]\s*$", piece[:embedded.start()]):
            action = embedded.group(1).strip()
            if _action_match(action):
                actions.append(action)
    return actions


def _quest_steps(source):
    """Extract ordered, hierarchical actions from varied community markup."""
    body = ""
    for name in (
            "Checklist", "TLDR; Walkthrough", "TLDR Walkthrough",
            "Short Walkthrough", "Walkthrough", "Quest Walkthrough"):
        body = _section(source, (name,))
        if body:
            break
    if not body:
        body = str(source or "")

    tokens = []
    pending = None
    current_heading = ""

    def flush_pending():
        nonlocal pending
        if pending:
            tokens.append(pending)
            pending = None

    for raw in body.splitlines():
        heading = re.match(
            r"^={2,6}\s*(.*?)\s*={2,6}\s*$", raw.strip())
        if heading:
            flush_pending()
            current_heading = _plain_wiki(heading.group(1))
            continue
        bullet = re.match(r"^\s*([:*#;]+)\s*(.+)$", raw)
        if bullet and any(mark in bullet.group(1) for mark in "*#"):
            flush_pending()
            pending = {
                "type": "list", "marker": bullet.group(1),
                "text": bullet.group(2).strip(), "heading": current_heading}
            continue
        stripped = raw.strip()
        if stripped.startswith(":"):
            flush_pending()
            continue
        if (pending and raw[:1].isspace() and stripped and not stripped.startswith(
                ("{{", "[[Category:", "<div", "</div", ":"))):
            # Wrapped Wiki bullets often continue on the next physical line.
            pending["text"] += " " + stripped
            continue
        flush_pending()
        if stripped:
            tokens.append({
                "type": "plain", "text": stripped,
                "heading": current_heading})
    flush_pending()

    list_tokens = [token for token in tokens if token["type"] == "list"]
    records = []
    seen = set()
    contexts = {}
    active_heading = ""

    def append_record(record):
        text_key = record["text"].casefold()
        key = (record["kind"], text_key)
        if not record["text"] or key in seen or len(records) >= MAX_QUEST_STEPS:
            return
        seen.add(key)
        records.append(record)

    for index, token in enumerate(tokens):
        clean = _plain_wiki(token["text"]).replace("\n", " ").strip(" -")
        if not clean or clean.casefold().startswith(
                ("your faction", "category:", "experience reward")):
            continue
        if token["type"] == "list":
            marker = token["marker"]
            depth = max(0, len(marker) - 1)
            future_depth = -1
            try:
                list_index = list_tokens.index(token)
                if list_index + 1 < len(list_tokens):
                    future_depth = max(
                        0, len(list_tokens[list_index + 1]["marker"]) - 1)
            except ValueError:
                pass
            has_children = future_depth > depth
            match = _action_match(clean)
            if has_children:
                append_record(_record(clean, depth, "group", clean))
                contexts[depth] = clean
                for deeper in [key for key in contexts if key > depth]:
                    contexts.pop(deeper, None)
                continue
            if match:
                group = contexts.get(max((key for key in contexts if key < depth),
                                         default=-1), "")
                append_record(_record(clean, depth, "action", group))
                continue
            # A child such as "Chilled Tundra Root from Everfrost" inherits
            # the actionable verb from "Forage the following four items".
            parent = contexts.get(max((key for key in contexts if key < depth),
                                      default=-1), "")
            parent_action = _action_match(parent)
            if parent_action:
                inferred = f"{parent_action.group(1).capitalize()} {clean}"
                append_record(_record(inferred, depth, "action", parent))
            continue

        heading_name = token.get("heading", "")
        for action in _split_action_sentences(clean):
            if heading_name and heading_name != active_heading:
                append_record(_record(heading_name, 0, "group", heading_name))
                active_heading = heading_name
            append_record(_record(action, 1 if heading_name else 0,
                                  "action", heading_name))

    if not any(record["kind"] == "action" for record in records):
        return []
    # Do not leave section headers with no action underneath them.
    return [record for index, record in enumerate(records)
            if record["kind"] == "action" or any(
                later["kind"] == "action" and later["group"] == record["text"]
                for later in records[index + 1:])][:MAX_QUEST_STEPS]


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
        first_actions = [step["text"] for step in steps
                         if step.get("kind") == "action"][:3]
        summary_parts.append("First steps: " + "; ".join(first_actions))
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


def _normalize_step_records(steps):
    records = []
    for value in steps or ():
        record = value
        if isinstance(value, str) and value.lstrip().startswith("{"):
            try:
                record = json.loads(value)
            except (TypeError, ValueError):
                record = value
        if isinstance(record, dict):
            text = str(record.get("text", "")).strip()
            if text:
                records.append(_record(
                    text, record.get("depth", 0), record.get("kind", "action"),
                    record.get("group", "")))
        else:
            text = str(record or "").strip()
            if text:
                records.append(_record(text.removeprefix("↳ "),
                                       int(text.startswith("↳ "))))
    return records


class _ClickableStepLabel(QLabel):
    """Word-wrapped checkbox label that keeps the native checkbox control."""

    def __init__(self, text, checkbox, parent=None):
        super().__init__(text, parent)
        self.checkbox = checkbox
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setAccessibleName("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.toggle()
            self.checkbox.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _ChecklistStepRow(QWidget):
    def __init__(self, number, record, parent=None):
        super().__init__(parent)
        self.setObjectName("QuestChecklistStepRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(min(36, record["depth"] * 12), 2, 2, 2)
        layout.setSpacing(6)
        self.checkbox = QCheckBox()
        if record["depth"] and record["group"]:
            accessible_name = (
                f"Under {record['group']}, substep {number}: {record['text']}")
            accessible_description = (
                f"Checklist hierarchy depth {record['depth']}; "
                f"parent group {record['group']}")
        elif record["depth"]:
            accessible_name = f"Substep {number}: {record['text']}"
            accessible_description = (
                f"Checklist hierarchy depth {record['depth']}")
        else:
            accessible_name = f"Quest step {number}: {record['text']}"
            accessible_description = "Top-level quest checklist step"
        self.checkbox.setAccessibleName(accessible_name)
        self.checkbox.setAccessibleDescription(accessible_description)
        self.checkbox.setToolTip(record["text"])
        self.checkbox.setProperty("step_key", _step_key(record["text"]))
        self.checkbox.setProperty("step_text", record["text"])
        layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignTop)
        self.label = _ClickableStepLabel(
            f"{number}. {record['text']}", self.checkbox, self)
        layout.addWidget(self.label, 1)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)


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
        self.steps_scroll = scrollable(
            self.steps_body, "QuestChecklistScroll")
        self.steps_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.steps_scroll, 1)

        actions = QHBoxLayout()
        self.reset_button = QPushButton("Reset checks")
        self.reset_button.setIcon(game_icon("refresh"))
        self.reset_button.setToolTip("Uncheck every step after confirmation")
        self.reset_button.setAccessibleName("Reset all quest checklist steps")
        self.reset_button.clicked.connect(self._confirm_reset)
        actions.addWidget(self.reset_button)
        self.clear_button = QPushButton("Clear quest")
        self.clear_button.setIcon(game_icon("trash"))
        self.clear_button.setToolTip(
            "Remove the active floating checklist after confirmation")
        self.clear_button.setAccessibleName("Clear the active quest checklist")
        self.clear_button.clicked.connect(self._confirm_clear)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)
        self.restore()

    def restore(self):
        state = config.data["quests"].get("checklist", {})
        title = str(state.get("title", "") or "")
        steps = state.get("steps", [])
        checked = set(state.get("checked", []))
        self.set_quest(title, steps, checked, save=False)

    def set_quest(self, title, steps, checked=(), save=True):
        focused_index = next((index for index, box in enumerate(self._boxes)
                              if box.hasFocus()), None)
        focused_key = (self._boxes[focused_index].property("step_key")
                       if focused_index is not None else None)
        while self.steps_layout.count() > 1:
            item = self.steps_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._boxes = []
        self._step_records = _normalize_step_records(steps)
        checked = set(checked)
        action_number = 0
        for record in self._step_records:
            if record["kind"] == "group":
                heading = QLabel(record["text"])
                heading.setObjectName("QuestChecklistGroup")
                heading.setWordWrap(True)
                heading.setAccessibleName(f"Quest section: {record['text']}")
                self.steps_layout.insertWidget(
                    self.steps_layout.count() - 1, heading)
                continue
            action_number += 1
            row = _ChecklistStepRow(action_number, record, self.steps_body)
            box = row.checkbox
            box.setChecked(box.property("step_key") in checked)
            box.stateChanged.connect(self._changed)
            self.steps_layout.insertWidget(self.steps_layout.count() - 1, row)
            self._boxes.append(box)
        self.title.setText(title or "No quest selected")
        self._update_progress()
        if save:
            self._save_state()
            _announce_accessible(
                self.title,
                f"Checklist updated for {title}; {len(self._boxes)} actionable steps")
        if focused_index is not None:
            restored = next((box for box in self._boxes
                             if box.property("step_key") == focused_key), None)
            if restored is None and self._boxes:
                # Same index is the next action after a deletion/rewording;
                # the final previous action is the fallback at list end.
                restored = self._boxes[min(focused_index, len(self._boxes) - 1)]
            if restored is None:
                restored = self.reset_button
            QTimer.singleShot(
                0, lambda target=restored: target.setFocus(
                    Qt.FocusReason.OtherFocusReason))

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
        state["steps"] = [json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                          for record in self._step_records]
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
    _minimum_scale = 0.80

    def _set_scaled_minimum_size(self):
        """Keep enough vertical room for details, actions, and Wiki notice."""
        super()._set_scaled_minimum_size()
        if not self._collapsed:
            self.setMinimumHeight(580)

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
        self._catalog_generation = 0
        self._quest_generation = 0
        self._catalog_continuation = ""
        self._catalog_attempt = 0
        self._quest_attempt = 0
        self._pending_quest_title = ""
        self._catalog_watchdog = QTimer(self)
        self._catalog_watchdog.setSingleShot(True)
        self._quest_watchdog = QTimer(self)
        self._quest_watchdog.setSingleShot(True)
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
        self.refresh_button = QPushButton("Refresh catalog")
        self.refresh_button.setIcon(game_icon("refresh"))
        self.refresh_button.setAccessibleName("Refresh Project 1999 quest catalog")
        self.refresh_button.setToolTip(
            "Download the current quest title catalog from the Wiki; click again to restart a stuck refresh")
        self.refresh_button.clicked.connect(lambda: self._fetch_catalog(force=True))
        controls_layout.addWidget(self.refresh_button)
        self.content.addWidget(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        splitter.setChildrenCollapsible(False)
        left = QFrame()
        left.setMinimumWidth(270)
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
        right.setMinimumWidth(520)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(3, 4, 6, 6)
        self.quest_title = QLabel("Choose a quest")
        self.quest_title.setObjectName("QuestDetailTitle")
        self.quest_title.setWordWrap(True)
        right_layout.addWidget(self.quest_title)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(300)
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
        self.wiki_button.setMinimumWidth(145)
        self.wiki_button.setIcon(game_icon("ph-file-search"))
        self.wiki_button.setEnabled(False)
        self.wiki_button.setAccessibleName("Open selected quest on Project 1999 Wiki")
        self.wiki_button.setToolTip("Open the full source page in your browser")
        self.wiki_button.clicked.connect(self._open_wiki)
        detail_actions.addWidget(self.wiki_button)
        self.checklist_button = QPushButton("Floating checklist")
        self.checklist_button.setMinimumWidth(165)
        self.checklist_button.setIcon(game_icon("check"))
        self.checklist_button.setEnabled(False)
        self.checklist_button.setAccessibleName(
            "Open selected quest as a floating checklist")
        self.checklist_button.setToolTip(
            "Keep the selected quest steps always on top and save progress")
        self.checklist_button.clicked.connect(self._open_checklist)
        detail_actions.addWidget(self.checklist_button)
        self.retry_quest_button = QPushButton("Retry quest")
        self.retry_quest_button.setIcon(game_icon("refresh"))
        self.retry_quest_button.setAccessibleName("Retry loading selected quest")
        self.retry_quest_button.setToolTip(
            "Try loading this quest from Project 1999 Wiki again")
        self.retry_quest_button.clicked.connect(self._retry_pending_quest)
        self.retry_quest_button.hide()
        detail_actions.addWidget(self.retry_quest_button)
        right_layout.addLayout(detail_actions)
        self.source_note = QLabel(
            "Community Wiki data can be incomplete or inaccurate; verify critical turn-ins.")
        self.source_note.setWordWrap(True)
        self.source_note.setObjectName("QuestSourceNote")
        self.source_note.setMinimumHeight(34)
        right_layout.addWidget(self.source_note)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([280, 620])
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
                          "Vantage/1.44.60 (vantagecompanion@gmail.com)")
        return self._network.get(request)

    @staticmethod
    def _dispose_reply(reply):
        if reply is not None and hasattr(reply, "deleteLater"):
            reply.deleteLater()

    @staticmethod
    def _abort_reply(reply):
        if reply is not None and hasattr(reply, "abort"):
            reply.abort()

    @staticmethod
    def _arm_watchdog(timer, callback):
        timer.stop()
        try:
            timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        timer.timeout.connect(callback)
        timer.start(NETWORK_TIMEOUT_MS)

    def _cancel_catalog_request(self):
        self._catalog_watchdog.stop()
        reply, self._catalog_reply = self._catalog_reply, None
        self._abort_reply(reply)
        self._dispose_reply(reply)

    def _cancel_quest_request(self):
        self._quest_watchdog.stop()
        reply, self._quest_reply = self._quest_reply, None
        self._abort_reply(reply)
        self._dispose_reply(reply)

    def _fetch_catalog(self, force=False):
        if self._catalog_loading and not force:
            return
        if self._catalog and not force:
            return
        self._catalog_generation += 1
        self._cancel_catalog_request()
        self._catalog_loading = True
        self._catalog_seen = set()
        self._catalog_pages = 0
        self.catalog_status.setText("Loading quest catalog from Project 1999 Wiki…")
        _announce_accessible(self.catalog_status, self.catalog_status.text())
        self._fetch_catalog_page("", 0, self._catalog_generation)

    def _fetch_catalog_page(self, continuation, attempt=0, generation=None):
        generation = self._catalog_generation if generation is None else generation
        if generation != self._catalog_generation:
            return
        if attempt == 0:
            self._catalog_pages += 1
        self._catalog_continuation = continuation
        self._catalog_attempt = attempt
        reply = self._request(self._api_url({
            "action": "query", "list": "categorymembers",
            "cmtitle": QUEST_CATEGORY, "cmnamespace": "0", "cmlimit": "max",
            "cmcontinue": continuation, "format": "json",
        }))
        self._catalog_reply = reply
        reply.finished.connect(
            lambda r=reply, g=generation: self._catalog_page_finished(r, g))
        self._arm_watchdog(
            self._catalog_watchdog,
            lambda r=reply, g=generation: self._catalog_page_timed_out(r, g))

    def _catalog_page_timed_out(self, reply, generation):
        if reply is not self._catalog_reply or generation != self._catalog_generation:
            return
        self._catalog_reply = None
        self._abort_reply(reply)
        self._dispose_reply(reply)
        self._catalog_request_failed("The Wiki took too long to respond", generation)

    def _catalog_request_failed(self, reason, generation):
        if generation != self._catalog_generation:
            return
        if self._catalog_attempt < NETWORK_RETRY_LIMIT:
            self._catalog_attempt += 1
            self.catalog_status.setText(
                f"{reason} · retrying catalog ({self._catalog_attempt + 1} of {NETWORK_RETRY_LIMIT + 1})…")
            self._fetch_catalog_page(
                self._catalog_continuation, self._catalog_attempt, generation)
            return
        self._catalog_loading = False
        self.catalog_status.setText(
            ("Wiki unavailable · using the offline quest catalog · Refresh catalog to retry"
             if self._catalog else
             "Wiki unavailable · no offline quest catalog yet · Refresh catalog to retry"))
        _announce_accessible(
            self.catalog_status, self.catalog_status.text(), assertive=True)

    def _catalog_page_finished(self, reply=None, generation=None):
        reply = reply or self.sender()
        generation = self._catalog_generation if generation is None else generation
        if reply is not self._catalog_reply or generation != self._catalog_generation:
            self._dispose_reply(reply)
            return
        self._catalog_watchdog.stop()
        self._catalog_reply = None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            reason = str(reply.errorString() or "Wiki unavailable") \
                if hasattr(reply, "errorString") else "Wiki unavailable"
            self._dispose_reply(reply)
            self._catalog_request_failed(reason, generation)
            return
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            titles, continuation = parse_quest_catalog_payload(payload)
            self._catalog_seen.update(titles)
        except (UnicodeDecodeError, ValueError, TypeError):
            self._dispose_reply(reply)
            self._catalog_request_failed(
                "The Wiki returned unreadable catalog data", generation)
            return
        self._dispose_reply(reply)
        if continuation and self._catalog_pages < MAX_CATALOG_PAGES:
            self.catalog_status.setText(
                f"Loading quest catalog… {len(self._catalog_seen):,} found")
            self._fetch_catalog_page(continuation, 0, generation)
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
        self.retry_quest_button.hide()
        self._pending_quest_title = title
        self._quest_generation += 1
        self._cancel_quest_request()
        self._start_quest_request(title, 0, self._quest_generation)

    def _start_quest_request(self, title, attempt, generation):
        if generation != self._quest_generation:
            return
        self._quest_attempt = attempt
        reply = self._request(self._api_url({
            "action": "parse", "page": title, "prop": "wikitext",
            "format": "json",
        }))
        self._quest_reply = reply
        reply.setProperty("quest_title", title)
        reply.finished.connect(
            lambda r=reply, g=generation: self._quest_finished(r, g))
        self._arm_watchdog(
            self._quest_watchdog,
            lambda r=reply, g=generation: self._quest_timed_out(r, g))

    def _quest_timed_out(self, reply, generation):
        if reply is not self._quest_reply or generation != self._quest_generation:
            return
        title = str(reply.property("quest_title") or "Quest")
        self._quest_reply = None
        self._abort_reply(reply)
        self._dispose_reply(reply)
        self._quest_request_failed(title, "The Wiki took too long to respond", generation)

    def _quest_request_failed(self, title, reason, generation):
        if generation != self._quest_generation:
            return
        if self._quest_attempt < NETWORK_RETRY_LIMIT:
            self._quest_attempt += 1
            self.summary.setText(
                f"{reason}. Retrying {title} ({self._quest_attempt + 1} of {NETWORK_RETRY_LIMIT + 1})…")
            self._start_quest_request(title, self._quest_attempt, generation)
            return
        self.summary.setText(
            f"{title} could not be loaded. Check the connection, then choose Retry quest.")
        self.retry_quest_button.show()
        self.retry_quest_button.setEnabled(True)
        _announce_accessible(
            self.summary, f"Could not load {title}. Retry quest is available.",
            assertive=True)

    def _retry_pending_quest(self):
        if self._pending_quest_title:
            self._load_quest(self._pending_quest_title)

    def _quest_finished(self, reply=None, generation=None):
        reply = reply or self.sender()
        generation = self._quest_generation if generation is None else generation
        if reply is not self._quest_reply or generation != self._quest_generation:
            self._dispose_reply(reply)
            return
        self._quest_watchdog.stop()
        self._quest_reply = None
        title = str(reply.property("quest_title") or "Quest")
        if reply.error() != QNetworkReply.NetworkError.NoError:
            reason = str(reply.errorString() or "Wiki unavailable") \
                if hasattr(reply, "errorString") else "Wiki unavailable"
            self._dispose_reply(reply)
            self._quest_request_failed(title, reason, generation)
            return
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsed = payload.get("parse", {})
            wikitext = parsed.get("wikitext", {}).get("*", "")
            if not isinstance(wikitext, str) or not wikitext.strip():
                raise ValueError("missing quest wikitext")
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
            self._dispose_reply(reply)
            self._quest_request_failed(
                title, "The Wiki returned quest data Vantage could not read",
                generation)
            return
        self._dispose_reply(reply)

    def _show_quest(self, quest):
        self._current_quest = quest
        self.quest_title.setText(quest["title"])
        self.quest_title.setAccessibleName(f"Selected quest: {quest['title']}")
        self.summary.setPlainText(quest["summary"])
        self.steps.clear()
        action_number = 0
        for step in _normalize_step_records(quest["steps"]):
            if step["kind"] == "group":
                item = QListWidgetItem(step["text"])
                item.setData(Qt.ItemDataRole.UserRole, "group")
            else:
                action_number += 1
                indent = "  " * min(3, step["depth"])
                item = QListWidgetItem(
                    f"{indent}{action_number}. {step['text']}")
                item.setData(Qt.ItemDataRole.UserRole, "action")
            item.setToolTip(step["text"])
            self.steps.addItem(item)
        if not quest["steps"]:
            self.steps.addItem(
                "No structured walkthrough was found. Open the full Wiki page for details.")
        self.wiki_button.setEnabled(True)
        self.checklist_button.setEnabled(bool(quest["steps"]))
        self.retry_quest_button.hide()
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
