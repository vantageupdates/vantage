from types import SimpleNamespace

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.helpers.notification_overlay import NotificationOverlay


def make_overlay(monkeypatch, geometry=(40, 50, 320, 150)):
    app = QApplication.instance() or QApplication([])
    settings = config.notification_overlay_defaults('readability')
    settings['geometry'] = list(geometry)
    monkeypatch.setattr(config, 'data', {
        'general': {'notification_overlays': {'readability': settings}}})
    monkeypatch.setattr(config, 'save', lambda: None)
    return app, NotificationOverlay('readability', 'Alerts', 'top_left')


def test_long_overlay_title_and_detail_wrap_without_inflating_saved_window(monkeypatch):
    app, overlay = make_overlay(monkeypatch)
    try:
        original = overlay.geometry()
        title = 'Regrowth of the Grove fading on Spiritflux'
        message = ('Regrowth of the Grove expires in five seconds. '
                   'Refresh this buff when it ends.')
        overlay.notify(title, message, countdown_seconds=60)
        app.processEvents()
        row = overlay._rows[0]
        assert overlay.geometry() == original
        assert row.title.wordWrap()
        assert row.title.height() >= row.title.heightForWidth(row.title.width())
        assert row.message.height() >= row.message.heightForWidth(row.message.width())
        assert row.title.geometry().right() < row.remaining.geometry().left()
        assert row.remaining.text() == '1:00'
        assert row.title.toolTip() == title
        assert row.message.toolTip() == message
        assert row.geometry().bottom() < overlay.height()
        assert overlay._settings()['geometry'] == [40, 50, 320, 150]
    finally:
        overlay.close()


def test_overlay_text_keeps_literal_names_and_user_font_settings(monkeypatch):
    app, overlay = make_overlay(monkeypatch, (40, 50, 360, 180))
    try:
        overlay._settings()['font_size'] = 12
        overlay._settings()['font_weight'] = 'normal'
        overlay.notify('Mindflux <Castle>', 'Incoming tell <message>', countdown_seconds=60)
        app.processEvents()
        row = overlay._rows[0]
        assert row.title.textFormat() == Qt.TextFormat.PlainText
        assert row.message.textFormat() == Qt.TextFormat.PlainText
        assert row.title.text() == 'Mindflux <Castle>'
        assert row.title.font().pointSize() == 12
        assert not row.title.font().bold()
    finally:
        overlay.close()


def test_open_overlay_recovers_on_monitor_change_without_rewriting_preferences(monkeypatch):
    app, overlay = make_overlay(monkeypatch)
    try:
        fake = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1040))
        monkeypatch.setattr(QApplication, 'screenAt', lambda _point: fake)
        overlay.setGeometry(2300, 1200, 320, 150)
        saved = list(overlay._settings()['geometry'])
        app.sendEvent(overlay, QEvent(QEvent.Type.ScreenChangeInternal))
        QTest.qWait(20)
        assert fake.availableGeometry().contains(overlay.geometry())
        assert overlay.size().width() == 320
        assert overlay.size().height() == 150
        assert overlay._settings()['geometry'] == saved
        stable = overlay.geometry()
        overlay._screen_geometry_watcher.schedule()
        QTest.qWait(20)
        assert overlay.geometry() == stable
    finally:
        overlay.close()
