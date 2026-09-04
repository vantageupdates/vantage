"""Compact Vantage identity, support, and legal-notice dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget)

from vantage.helpers import resource_path
from vantage.helpers.icons import game_icon
from vantage.helpers.scaled_dialog import UniformScaleDialog


SOURCE_URL = "https://github.com/vantageupdates/vantage"
SUPPORT_URL = "https://buymeacoffee.com/vantagecompanion"
CONTACT_EMAIL = "vantagecompanion@gmail.com"
CONTACT_URL = f"mailto:{CONTACT_EMAIL}"


CREDITS_HTML = """
<h2>Credits &amp; Acknowledgments</h2>
<p>Vantage is made possible by open-source software and years of work by the
EverQuest and Project 1999 community.</p>
<ul>
  <li><a href="https://github.com/nomns/nparse">nParse project and
  contributors</a> — Vantage contains extensively modified GPL-3.0 code
  derived from nParse.</li>
  <li><a href="https://github.com/smasherprog/EqTool">PigParse / EqTool</a>
  — market-data reference used by Vantage.</li>
  <li><a href="https://wiki.project1999.com/">Project 1999 Wiki</a> and
  <a href="https://p99planner.com/">P99 Planner</a> communities — factual
  game references and community-maintained metadata.</li>
  <li><a href="https://github.com/RedGuides/brewall-maps">Brewall mapping
  community</a> — classic community map resources.</li>
  <li><a href="https://github.com/perotan/respawntimer">respawntimer community
  data</a> — a reference for zone respawn facts.</li>
  <li>GINA and GamParse — acknowledged only as community inspiration and for
  compatibility with familiar workflows. Vantage does not claim that their
  creators supplied code or endorsed this project.</li>
  <li><a href="https://github.com/coreui/coreui-icons">CoreUI Icons</a>,
  <a href="https://github.com/phosphor-icons/core">Phosphor Icons</a>, and
  <a href="https://github.com/notofonts/latin-greek-cyrillic">Noto Sans</a>
  — interface resources under their respective licenses.</li>
</ul>
<p>The complete runtime dependency and license list is available in the
<b>Open Source Licenses</b> tab.</p>
<p>Official contact: <a href="mailto:vantagecompanion@gmail.com">email the
Vantage project at vantagecompanion@gmail.com</a>.</p>
<p><b>Independent project.</b> Vantage is not affiliated with, endorsed by, or
sponsored by Daybreak Game Company, EverQuest, Project 1999, or any community
project named above. Names and trademarks remain the property of their
respective owners.</p>
"""


def _legal_text(filename):
    """Read a packaged legal file, with a source-tree fallback for tests."""
    candidates = (
        Path(resource_path(f"legal/{filename}")),
        Path(resource_path(filename)),
    )
    for candidate in candidates:
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return f"{filename} is unavailable in this build."


def open_external_url(url):
    """Open a fixed HTTPS destination without embedding a payment browser."""
    parsed = QUrl(str(url or ""))
    if parsed.scheme().casefold() != "https" or not parsed.host():
        return False
    return QDesktopServices.openUrl(parsed)


def open_contact_url(url):
    """Open only the project's fixed email destination."""
    parsed = QUrl(str(url or ""))
    if parsed.toString() != CONTACT_URL:
        return False
    return QDesktopServices.openUrl(parsed)


class AboutDialog(UniformScaleDialog):
    """Keep product identity prominent and legal attribution discoverable."""

    def __init__(self, version, parent=None):
        super().__init__(
            QSize(640, 380), parent,
            minimum_size=QSize(420, 260), initial_size=QSize(640, 380))
        self.setObjectName("AboutDialog")
        self.setWindowTitle("About Vantage")
        self.setModal(False)

        root = QVBoxLayout(self.scaled_surface)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(9)

        identity = QHBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(12)
        emblem = QLabel()
        emblem.setPixmap(QIcon(resource_path("data/ui/icon.png")).pixmap(
            QSize(46, 46), max(1.0, self.devicePixelRatioF())))
        emblem.setAccessibleName("")
        identity.addWidget(emblem)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        title = QLabel("VANTAGE")
        title.setObjectName("AboutTitle")
        subtitle = QLabel(f"FREE P99 COMPANION  ·  VERSION {version}")
        subtitle.setObjectName("AboutSubtitle")
        copy.addWidget(title)
        copy.addWidget(subtitle)
        creator = QLabel(
            "Created by Mindflux / Harmflux · P99 Green Server · "
            "Discord: mindflux99")
        creator.setObjectName("AboutCreator")
        copy.addWidget(creator)
        contact = QLabel(
            f'Official contact: <a href="{CONTACT_URL}">{CONTACT_EMAIL}</a>')
        contact.setObjectName("AboutContact")
        contact.setTextFormat(Qt.TextFormat.RichText)
        contact.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse |
            Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        contact.setAccessibleName(
            f"Email the Vantage project at {CONTACT_EMAIL}")
        contact.linkActivated.connect(open_contact_url)
        copy.addWidget(contact)
        identity.addLayout(copy, 1)
        root.addLayout(identity)

        tabs = QTabWidget()
        tabs.setObjectName("AboutTabs")
        tabs.setDocumentMode(True)
        tabs.setAccessibleName("About Vantage information")

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(10)
        summary = QLabel(
            "<b>Vantage is an independent, community-developed companion "
            "distributed free of charge and built around user-enabled "
            "EverQuest text logs.</b><br><br>"
            "Gameplay parsing, timers, maps, and alerts use log text or files "
            "the player explicitly exports with <code>/outputfile</code>. "
            "Vantage does not read game process memory, inject code, send "
            "keystrokes, or automate character actions.<br><br>"
            "It is an independent portable Windows application, not endorsed "
            "by Project 1999 or the EverQuest rights holders. Voluntary support "
            "never unlocks or restricts features.")
        summary.setWordWrap(True)
        summary.setTextFormat(Qt.TextFormat.RichText)
        summary.setAccessibleName("Vantage product summary")
        overview_layout.addWidget(summary)
        overview_layout.addStretch(1)

        support = QPushButton("Buy me a coffee")
        support.setObjectName("SupportAction")
        support.setIcon(game_icon("ph-coffee"))
        support.setAccessibleName("Buy me a coffee to support Vantage")
        support.setToolTip(
            "Open the Vantage Buy Me a Coffee page in your default browser")
        support.clicked.connect(lambda: open_external_url(SUPPORT_URL))
        overview_layout.addWidget(support)
        source = QPushButton("View source code")
        source.setIcon(game_icon("export"))
        source.setToolTip(
            "Open the official Vantage source repository in your browser")
        source.clicked.connect(lambda: open_external_url(SOURCE_URL))
        overview_layout.addWidget(source)
        tabs.addTab(overview, "About")

        credits = QTextBrowser()
        credits.setObjectName("CreditsAcknowledgments")
        credits.setOpenExternalLinks(False)
        credits.setOpenLinks(False)
        credits.setAccessibleName("Credits and acknowledgments")
        credits.setHtml(CREDITS_HTML)
        credits.anchorClicked.connect(
            lambda url: (
                open_contact_url(url.toString())
                if url.scheme().casefold() == "mailto"
                else open_external_url(url.toString())))
        tabs.addTab(credits, "Credits & Acknowledgments")

        notices = QPlainTextEdit()
        notices.setObjectName("LegalNotices")
        notices.setReadOnly(True)
        notices.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        notices.setAccessibleName("Open source licenses and legal notices")
        notices.setPlainText("\n\n".join((
            _legal_text("SOURCE-NOTICE.md").strip(),
            _legal_text("THIRD-PARTY-NOTICES.md").strip(),
            "GNU GENERAL PUBLIC LICENSE VERSION 3\n\n" +
            _legal_text("LICENSE").strip(),
        )))
        tabs.addTab(notices, "Open Source Licenses")
        root.addWidget(tabs, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Close")
        close.setAccessibleName("Close About Vantage")
        close.setToolTip("Close this information window")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)
