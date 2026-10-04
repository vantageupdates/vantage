"""Versioned first-launch Terms & Privacy acceptance for Vantage."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QLabel, QPushButton, QSizePolicy,
    QTextBrowser, QVBoxLayout)

from vantage.helpers import config, resource_path
from vantage.helpers.responsive import ResponsiveActionBar


TERMS_VERSION = "2026-09-15.1"
TERMS_FILENAME = "TERMS-AND-PRIVACY.md"


def _announce_status(widget, message):
    """Expose dynamic consent status through text and a polite live event."""
    message = str(message)
    widget.setText(message)
    widget.setAccessibleDescription(message)
    try:
        event = QAccessibleAnnouncementEvent(widget, message)
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)
    except (AttributeError, RuntimeError, TypeError):
        # The focused action also receives the status as a screen-reader
        # fallback in TermsDialog._accept_and_continue.
        pass


def load_terms_document():
    """Return the packaged notice and whether it was read successfully."""
    candidates = (
        Path(resource_path(f"legal/{TERMS_FILENAME}")),
        Path(resource_path(TERMS_FILENAME)),
    )
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if TERMS_VERSION in text and text.strip():
            return text, True
    return ((
        "# Vantage Terms & Privacy Notice\n\n"
        "The terms file is unavailable in this build. Exit Vantage and "
        "reinstall from a verified release."
    ), False)


def load_terms_text():
    """Read the notice for non-consent surfaces such as About Vantage."""
    return load_terms_document()[0]


def acceptance_is_current(settings=None):
    """Return true only for this notice version with a recorded UTC time."""
    settings = config.data if settings is None else settings
    legal = settings.get("legal", {}) if isinstance(settings, dict) else {}
    return (
        isinstance(legal, dict)
        and legal.get("terms_version") == TERMS_VERSION
        and config.valid_utc_timestamp(legal.get("accepted_at", ""))
    )


def _saved_acceptance_matches(accepted_at):
    """Re-read the durable file; an in-memory update is not acceptance."""
    if not config._filename:
        return False
    try:
        with open(config._filename, encoding="utf-8") as source:
            persisted = json.load(source)
        legal = persisted.get("legal", {})
        return (
            isinstance(legal, dict)
            and legal.get("terms_version") == TERMS_VERSION
            and legal.get("accepted_at") == accepted_at
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def record_acceptance():
    """Persist and verify acceptance, rolling memory back on any failure."""
    missing = object()
    previous = copy.deepcopy(config.data.get("legal", missing))
    accepted_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    config.data["legal"] = {
        "terms_version": TERMS_VERSION,
        "accepted_at": accepted_at,
    }
    try:
        config.save()
        if not _saved_acceptance_matches(accepted_at):
            raise OSError("the saved acceptance could not be verified")
    except Exception as error:
        if previous is missing:
            config.data.pop("legal", None)
        else:
            config.data["legal"] = previous
        return False, (
            "Vantage could not save your acceptance. Check that its data "
            f"folder is writable, then try again. ({error})"
        )
    return True, ""


class TermsDialog(QDialog):
    """Keyboard-accessible consent dialog with an explicit acceptance gate."""

    def __init__(self, parent=None, terms_text=None, save_acceptance=None):
        super().__init__(parent)
        self.setObjectName("TermsDialog")
        self.setWindowTitle("Vantage Terms & Privacy")
        self.setModal(True)
        self.resize(760, 620)
        self.setAccessibleName("Vantage Terms and Privacy notice")
        self.setAccessibleDescription(
            "Review the notice, confirm acceptance, or exit Vantage.")
        self._save_acceptance = save_acceptance or record_acceptance
        if terms_text is None:
            terms_text, self._notice_available = load_terms_document()
        else:
            self._notice_available = True

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        heading = QLabel("Terms & Privacy")
        heading.setObjectName("TermsHeading")
        heading.setAccessibleName("Terms and Privacy")
        root.addWidget(heading)

        introduction = QLabel(
            "Please review this notice. Vantage will start only after you "
            "explicitly accept the current version.")
        introduction.setWordWrap(True)
        introduction.setAccessibleName("Acceptance instructions")
        root.addWidget(introduction)

        self.notice = QTextBrowser()
        self.notice.setObjectName("TermsNotice")
        self.notice.setReadOnly(True)
        self.notice.setOpenExternalLinks(False)
        self.notice.setTabChangesFocus(True)
        self.notice.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.notice.setAccessibleName("Vantage Terms and Privacy notice text")
        self.notice.setAccessibleDescription(
            "Scrollable notice text. Use arrow keys, Page Up, or Page Down "
            "to read it.")
        self.notice.setMarkdown(terms_text)
        root.addWidget(self.notice, 1)

        self.confirm = QCheckBox("I have read and accept this notice")
        self.confirm.setObjectName("TermsAcceptanceCheckbox")
        self.confirm.setAccessibleName(
            "Accept the current Vantage Terms and Privacy notice")
        self.confirm.setAccessibleDescription(
            "Select this checkbox to enable Accept and Continue.")
        self.confirm.setEnabled(self._notice_available)
        root.addWidget(self.confirm)

        self.status = QLabel("")
        self.status.setObjectName("TermsStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Terms acceptance status")
        self.status.setAccessibleDescription("")
        root.addWidget(self.status)

        self.exit_button = QPushButton("Exit Vantage")
        self.exit_button.setObjectName("TermsExit")
        self.exit_button.setAccessibleName("Exit Vantage without accepting")
        self.exit_button.setAccessibleDescription(
            "Close Vantage without starting services.")
        self.exit_button.clicked.connect(self.reject)
        self.accept_button = QPushButton("Accept & Continue")
        self.accept_button.setObjectName("TermsAccept")
        self.accept_button.setEnabled(False)
        self.accept_button.setDefault(True)
        self.accept_button.setAccessibleName(
            "Accept the notice and continue to Vantage")
        self.accept_button.setAccessibleDescription(
            "Available after the acceptance checkbox is selected.")
        self.accept_button.clicked.connect(self._accept_and_continue)
        for button in (self.exit_button, self.accept_button):
            button.ensurePolished()
            button.setMinimumWidth(button.sizeHint().width())
        action_width = max(
            self.exit_button.minimumWidth(),
            self.accept_button.minimumWidth())
        self.actions = ResponsiveActionBar(action_width, spacing=8)
        self.actions.setObjectName("TermsActions")
        self.actions.addWidget(self.exit_button)
        self.actions.addWidget(self.accept_button)
        root.addWidget(self.actions)

        self.confirm.toggled.connect(self._update_accept_enabled)
        self.setTabOrder(self.notice, self.confirm)
        self.setTabOrder(self.confirm, self.exit_button)
        self.setTabOrder(self.exit_button, self.accept_button)
        self.notice.setFocus(Qt.FocusReason.OtherFocusReason)

        if not self._notice_available:
            _announce_status(
                self.status,
                "The Terms & Privacy notice is unavailable in this build. "
                "Vantage cannot record acceptance; exit and reinstall from "
                "a verified release.")
            self.confirm.setAccessibleDescription(
                "Acceptance is unavailable because the notice could not be read.")

        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry().adjusted(16, 16, -16, -16)
            self.setMinimumSize(
                min(480, available.width()), min(420, available.height()))
            self.resize(
                min(self.width(), available.width()),
                min(self.height(), available.height()))
        else:
            self.setMinimumSize(480, 420)

    def _update_accept_enabled(self, checked):
        self.accept_button.setEnabled(bool(checked and self._notice_available))

    def _accept_and_continue(self):
        if not self._notice_available or not self.confirm.isChecked():
            return
        self.accept_button.setEnabled(False)
        saving = "Saving your acceptance…"
        self.accept_button.setAccessibleDescription(
            saving + " Please wait while Vantage verifies the saved setting.")
        _announce_status(self.status, saving)
        QApplication.processEvents()
        saved, error = self._save_acceptance()
        if saved:
            self.accept()
            return
        message = error or "Vantage could not save your acceptance."
        self._update_accept_enabled(self.confirm.isChecked())
        self.accept_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self.accept_button.setAccessibleDescription(
            message + " Fix the storage problem, then choose Accept and "
            "Continue to try again.")
        _announce_status(self.status, message)


def ensure_terms_accepted(parent=None):
    """Skip an accepted version or synchronously request current consent."""
    _notice, available = load_terms_document()
    if not available:
        # Fail closed even when config claims this version was accepted. A
        # build that cannot present its notice must not silently start.
        dialog = TermsDialog(parent)
        return dialog.exec() == QDialog.DialogCode.Accepted
    if acceptance_is_current():
        return True
    dialog = TermsDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
