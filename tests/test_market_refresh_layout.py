"""Async refresh captions must not reallocate the Market search field."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QPushButton, QWidget

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.parsers.market import GreenMarket, _MarketRefreshButton


app = QApplication([])
for filename in ('NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(str(Path('data/fonts') / filename))
app.setFont(QFont('Noto Sans'))
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))


def rect(widget):
    return [widget.x(), widget.y(), widget.width(), widget.height()]


styles = []
for stylesheet in ('', 'font-size: 18px;',
                   'font-size: 18px; padding: 6px 13px;',
                   'font-size: 18px; padding: 6px 13px; min-width: 220px;'):
    toolbar = QWidget()
    toolbar.resize(970, 90)
    layout = QHBoxLayout(toolbar)
    search = QLineEdit()
    button = _MarketRefreshButton('Refresh')
    button.setIcon(game_icon('refresh'))
    button.setStyleSheet(stylesheet)
    layout.addWidget(search, 1)
    layout.addWidget(button)
    toolbar.show()
    app.processEvents()
    before = {
        'search': rect(search), 'button': rect(button),
        'hint': [button.sizeHint().width(), button.sizeHint().height()],
        'minimum': [button.minimumSizeHint().width(), button.minimumSizeHint().height()],
    }
    button.setText('Refreshing…')
    button.setEnabled(False)
    app.processEvents()
    after = {
        'search': rect(search), 'button': rect(button),
        'hint': [button.sizeHint().width(), button.sizeHint().height()],
        'minimum': [button.minimumSizeHint().width(), button.minimumSizeHint().height()],
    }
    reference = QPushButton('Refreshing…')
    reference.setIcon(game_icon('refresh'))
    reference.setStyleSheet(stylesheet)
    reference.ensurePolished()
    styles.append({
        'before': before, 'after': after,
        'natural_busy_width': reference.sizeHint().width(),
    })
    toolbar.close()


class SettingsSignals(QObject):
    config_updated = Signal()


class OfflineReply(QObject):
    finished = Signal()

    def error(self):
        return QNetworkReply.NetworkError.HostNotFoundError

    def errorString(self):
        return 'Deterministic offline test'


def get(manager, request):
    reply = OfflineReply(manager)
    QTimer.singleShot(40, reply.finished.emit)
    return reply


QNetworkAccessManager.get = get
profile = Path(os.environ['VANTAGE_DATA_DIR'])
profile.mkdir(parents=True, exist_ok=True)
config.load(str(profile / 'vantage.config.json'))
config.verify_settings()
app._signals = {'settings': SettingsSignals()}
app._parsers_dict = {}
market = GreenMarket()
market.resize(490, 310)
market.show()
app.processEvents()
market.refresh()
app.processEvents()
before = {
    'search': rect(market.search), 'tabs': rect(market.tabs),
    'caption': market._refresh_button.text(),
    'enabled': market._refresh_button.isEnabled(),
    'requests': sorted(market._requests_in_flight),
}
market.search.setText('manastone')
market.resize(245, 155)
QTest.qWait(80)
after = {
    'search': rect(market.search), 'tabs': rect(market.tabs),
    'caption': market._refresh_button.text(),
    'enabled': market._refresh_button.isEnabled(),
    'requests': sorted(market._requests_in_flight),
}
print(json.dumps({
    'styles': styles, 'before': before, 'after': after,
    'surface': [market._surface.width(), market._surface.height()],
    'size': [market.width(), market.height()],
}))
app.quit()
"""


@pytest.fixture(scope='module')
def refresh_layout_result(tmp_path_factory):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(
        tmp_path_factory.mktemp('market-refresh-layout') / 'profile')
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_refresh_captions_keep_geometry_across_font_padding_and_style_minimums(
        refresh_layout_result):
    cases = refresh_layout_result['styles']
    for case in cases:
        assert case['before'] == case['after']
        assert case['before']['hint'][0] >= case['natural_busy_width']
    assert cases[1]['before']['hint'][0] > cases[0]['before']['hint'][0]
    assert cases[2]['before']['hint'][0] > cases[1]['before']['hint'][0]
    assert cases[3]['before']['hint'][0] >= 220


def test_async_refresh_completion_keeps_logical_search_and_tabs_geometry(
        refresh_layout_result):
    before = refresh_layout_result['before']
    after = refresh_layout_result['after']
    assert before['search'] == after['search']
    assert before['tabs'] == after['tabs']
    assert before['caption'] == 'Refreshing…'
    assert before['enabled'] is False
    assert before['requests'] == ['Green']
    assert after['caption'] == 'Refresh'
    assert after['enabled'] is True
    assert after['requests'] == []
    assert refresh_layout_result['surface'] == [980, 620]
    assert refresh_layout_result['size'] == [245, 155]
