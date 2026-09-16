import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QStyle

from vantage.helpers import config, terms
from vantage.helpers.application import VantageApp


ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_AT = "2026-09-15T12:34:56Z"


def _app():
    return QApplication.instance() or QApplication([])


def test_notice_matches_current_version_and_product_scope():
    notice = (ROOT / "TERMS-AND-PRIVACY.md").read_text(encoding="utf-8")

    assert terms.TERMS_VERSION == "2026-09-15.1"
    assert terms.TERMS_VERSION in notice
    assert "GPL-3.0" in notice
    assert "does not sell your data" in notice
    assert "vantagecompanion@gmail.com" in notice
    assert "indemn" not in notice.casefold()


def test_accept_button_requires_explicit_checkbox_and_escape_rejects():
    app = _app()
    saves = []
    dialog = terms.TermsDialog(
        terms_text="# Test notice",
        save_acceptance=lambda: saves.append(True) or (True, ""))

    assert not dialog.accept_button.isEnabled()
    dialog.accept_button.click()
    assert saves == []
    dialog.confirm.setChecked(True)
    assert dialog.accept_button.isEnabled()
    assert dialog.accept_button.accessibleName()
    assert dialog.exit_button.accessibleDescription()

    dialog.show()
    app.processEvents()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert saves == []


def test_large_text_actions_reflow_fit_and_notice_remains_scrollable():
    app = _app()
    previous_font = QFont(app.font())
    large_font = QFont(previous_font)
    large_font.setPointSize(18)
    app.setFont(large_font)
    try:
        dialog = terms.TermsDialog()
        dialog.show()
        app.processEvents()

        available = dialog.screen().availableGeometry()
        assert dialog.geometry().intersected(available) == dialog.geometry()
        assert dialog.notice.verticalScrollBar().maximum() > 0
        assert dialog.actions._columns in {1, 2}
        for button in (dialog.exit_button, dialog.accept_button):
            margin = button.style().pixelMetric(
                QStyle.PixelMetric.PM_ButtonMargin, None, button)
            required = (
                button.fontMetrics().horizontalAdvance(button.text())
                + margin * 2)
            assert button.width() >= required
            top_left = button.mapTo(dialog, QPoint(0, 0))
            assert dialog.rect().contains(QRect(top_left, button.size()))

        dialog.confirm.setChecked(True)
        dialog.confirm.setFocus(Qt.FocusReason.TabFocusReason)
        for expected in (dialog.exit_button, dialog.accept_button):
            QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
            app.processEvents()
            assert dialog.focusWidget() is expected
        dialog.close()
    finally:
        app.setFont(previous_font)


def test_acceptance_persists_exact_version_and_utc_timestamp(tmp_path, monkeypatch):
    destination = tmp_path / "vantage.config.json"
    monkeypatch.setattr(config, "data", {"general": {}})
    monkeypatch.setattr(config, "_filename", str(destination))

    saved, error = terms.record_acceptance()

    assert saved is True
    assert error == ""
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    assert persisted["legal"]["terms_version"] == terms.TERMS_VERSION
    assert config.valid_utc_timestamp(persisted["legal"]["accepted_at"])
    assert terms.acceptance_is_current(persisted)


def test_current_version_skips_dialog(monkeypatch):
    monkeypatch.setattr(config, "data", {"legal": {
        "terms_version": terms.TERMS_VERSION,
        "accepted_at": ACCEPTED_AT,
    }})

    class UnexpectedDialog:
        def __init__(self, _parent):
            raise AssertionError("current acceptance must not prompt")

    monkeypatch.setattr(terms, "TermsDialog", UnexpectedDialog)
    assert terms.ensure_terms_accepted() is True


def test_old_or_missing_version_prompts_again(monkeypatch):
    prompts = []

    class RejectingDialog:
        def __init__(self, parent):
            prompts.append(parent)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(terms, "TermsDialog", RejectingDialog)
    for legal in (
            {},
            {"terms_version": "2026-09-14.1", "accepted_at": ACCEPTED_AT},
            {"terms_version": terms.TERMS_VERSION, "accepted_at": ""}):
        monkeypatch.setattr(config, "data", {"legal": legal})
        assert terms.ensure_terms_accepted() is False

    assert len(prompts) == 3


def test_save_failure_never_accepts_or_leaves_acceptance_in_memory(monkeypatch):
    app = _app()
    original = {"terms_version": "2026-09-14.1", "accepted_at": ACCEPTED_AT}
    monkeypatch.setattr(config, "data", {"legal": dict(original)})
    monkeypatch.setattr(config, "save", lambda: (_ for _ in ()).throw(
        OSError("read-only profile")))

    saved, error = terms.record_acceptance()
    assert saved is False
    assert "could not save" in error
    assert config.data["legal"] == original
    assert not terms.acceptance_is_current()

    dialog = terms.TermsDialog(
        terms_text="# Test notice",
        save_acceptance=lambda: (False, "Acceptance was not written."))
    dialog.confirm.setChecked(True)
    dialog.accept_button.click()
    app.processEvents()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.status.text() == "Acceptance was not written."
    assert dialog.accept_button.isEnabled()


def test_save_status_is_announced_and_failure_has_focused_fallback(monkeypatch):
    app = _app()
    announcements = []

    class RecordingAccessible:
        AnnouncementPoliteness = terms.QAccessible.AnnouncementPoliteness

        @staticmethod
        def updateAccessibility(event):
            announcements.append(event.message())

    monkeypatch.setattr(terms, "QAccessible", RecordingAccessible)
    dialog = terms.TermsDialog(
        terms_text="# Test notice",
        save_acceptance=lambda: (False, "Acceptance was not written."))
    dialog.show()
    dialog.confirm.setChecked(True)
    dialog.accept_button.click()
    app.processEvents()

    assert announcements == [
        "Saving your acceptance…", "Acceptance was not written."]
    assert dialog.focusWidget() is dialog.accept_button
    fallback = dialog.accept_button.accessibleDescription()
    assert "Acceptance was not written." in fallback
    assert "try again" in fallback
    dialog.close()


def test_announcement_api_failure_keeps_actionable_accept_description(
        monkeypatch):
    _app()

    class FailingAccessible:
        AnnouncementPoliteness = terms.QAccessible.AnnouncementPoliteness

        @staticmethod
        def updateAccessibility(_event):
            raise RuntimeError("accessibility backend unavailable")

    monkeypatch.setattr(terms, "QAccessible", FailingAccessible)
    dialog = terms.TermsDialog(
        terms_text="# Test notice",
        save_acceptance=lambda: (False, "Read-only data folder."))
    dialog.confirm.setChecked(True)
    dialog.accept_button.click()

    assert "Read-only data folder." in (
        dialog.accept_button.accessibleDescription())
    assert "try again" in dialog.accept_button.accessibleDescription()


def test_missing_packaged_notice_fails_closed(tmp_path, monkeypatch):
    _app()
    saves = []
    monkeypatch.setattr(
        terms, "resource_path", lambda path: str(tmp_path / path))

    dialog = terms.TermsDialog(
        save_acceptance=lambda: saves.append(True) or (True, ""))

    assert not dialog.confirm.isEnabled()
    assert not dialog.accept_button.isEnabled()
    dialog.confirm.setChecked(True)
    dialog.accept_button.click()
    assert saves == []
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "unavailable" in dialog.status.text()


def test_missing_notice_does_not_bypass_with_current_config(tmp_path, monkeypatch):
    prompts = []
    monkeypatch.setattr(config, "data", {"legal": {
        "terms_version": terms.TERMS_VERSION,
        "accepted_at": ACCEPTED_AT,
    }})
    monkeypatch.setattr(
        terms, "resource_path", lambda path: str(tmp_path / path))

    class RejectingUnavailableDialog:
        def __init__(self, parent):
            prompts.append(parent)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(terms, "TermsDialog", RejectingUnavailableDialog)

    assert terms.acceptance_is_current()
    assert terms.ensure_terms_accepted() is False
    assert len(prompts) == 1


def test_config_validation_keeps_only_valid_legal_acceptance(monkeypatch):
    monkeypatch.setattr(config, "data", {"legal": {
        "terms_version": "not-a-version",
        "accepted_at": "tomorrow",
        "external_account": "must not persist",
    }})

    config.verify_settings()

    assert config.data["legal"] == {"terms_version": "", "accepted_at": ""}


def test_direct_app_construction_does_not_enforce_terms_by_default():
    parameter = inspect.signature(VantageApp.__init__).parameters["enforce_terms"]
    assert parameter.default is False


def test_decline_aborts_before_splash_or_services(tmp_path):
    script = r'''
import json
from vantage.helpers import application

application.ensure_terms_accepted = lambda: False

class ForbiddenSplash:
    def __init__(self):
        raise AssertionError("splash must not be created after decline")

application.StartupSplash = ForbiddenSplash
app = application.VantageApp([], enforce_terms=True)
print(json.dumps({
    "aborted": app.startup_aborted,
    "splash": hasattr(app, "_splash"),
    "services": hasattr(app, "_services"),
}))
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=20)

    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "aborted": True,
        "splash": False,
        "services": False,
    }
