import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QUrl

from vantage.helpers import about


ROOT = Path(__file__).resolve().parents[1]


ABOUT_SCRIPT = r"""
import json
from PySide6.QtWidgets import (
    QApplication, QLabel, QPlainTextEdit, QPushButton, QTextBrowser)
from vantage.helpers.about import AboutDialog

app = QApplication([])
dialog = AboutDialog("1.44.44")
dialog.show()
app.processEvents()
support = dialog.scaled_surface.findChild(QPushButton, "SupportAction")
notices = dialog.scaled_surface.findChild(QPlainTextEdit, "LegalNotices")
credits = dialog.scaled_surface.findChild(QTextBrowser, "CreditsAcknowledgments")
creator = dialog.scaled_surface.findChild(QLabel, "AboutCreator")
contact = dialog.scaled_surface.findChild(QLabel, "AboutContact")
print(json.dumps({
    "title": dialog.windowTitle(),
    "support": support.text(),
    "support_tooltip": support.toolTip(),
    "source_notice": "nomns/nparse" in notices.toPlainText(),
    "gpl": "GNU GENERAL PUBLIC LICENSE" in notices.toPlainText(),
    "credits": "nParse project and contributors" in credits.toPlainText(),
    "non_affiliation": "not affiliated with" in credits.toPlainText(),
    "creator": creator.text(),
    "contact": contact.text(),
    "minimum": [dialog.minimumWidth(), dialog.minimumHeight()],
}))
dialog.close()
"""


def test_public_funding_and_legal_files_are_present():
    assert about.SOURCE_URL == "https://github.com/vantageupdates/vantage"
    assert about.SUPPORT_URL == "https://buymeacoffee.com/vantagecompanion"
    assert about.CONTACT_EMAIL == "vantagecompanion@gmail.com"
    assert about.SUPPORT_URL in (ROOT / ".github" / "FUNDING.yml").read_text(
        encoding="utf-8")
    assert "GPL-3.0" in (ROOT / "SOURCE-NOTICE.md").read_text(
        encoding="utf-8")
    assert "PySide6" in (ROOT / "THIRD-PARTY-NOTICES.md").read_text(
        encoding="utf-8")


def test_external_url_helper_accepts_only_https(monkeypatch):
    opened = []
    monkeypatch.setattr(
        about.QDesktopServices, "openUrl",
        lambda url: opened.append(url) or True)
    assert about.open_external_url("http://example.com") is False
    assert about.open_external_url("file:///tmp/x") is False
    assert about.open_external_url(about.SUPPORT_URL) is True
    assert about.open_contact_url("mailto:someone@example.com") is False
    assert about.open_contact_url(about.CONTACT_URL) is True
    assert opened == [QUrl(about.SUPPORT_URL), QUrl(about.CONTACT_URL)]


def test_about_dialog_keeps_branding_primary_and_legal_notice_discoverable(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", ABOUT_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "title": "About Vantage",
        "support": "Buy me a coffee",
        "support_tooltip": (
            "Open the Vantage Buy Me a Coffee page in your default browser"),
        "source_notice": True,
        "gpl": True,
        "credits": True,
        "non_affiliation": True,
        "creator": (
            "Created by Mindflux / Harmflux · P99 Green Server · "
            "Discord: mindflux99"),
        "contact": (
            'Official contact: <a href="mailto:vantagecompanion@gmail.com">'
            'vantagecompanion@gmail.com</a>'),
        "minimum": [420, 260],
    }
