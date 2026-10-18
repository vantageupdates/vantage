"""Routine Market status transitions must not steal height from the tabs."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r'''
import json
from pathlib import Path

from native_audit_fixture import isolate
isolate()

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel
from vantage.parsers.market import GreenMarket, _MarketStatusLabel


class SettingsSignals(QObject):
    config_updated = Signal()


app = QApplication([])
for filename in ('NotoSans-Regular.ttf', 'NotoSans-Bold.ttf'):
    QFontDatabase.addApplicationFont(str(Path('data/fonts') / filename))
app.setFont(QFont('Noto Sans'))
app.setStyleSheet(Path('data/ui/_.css').read_text(encoding='utf-8'))
app._signals = {'settings': SettingsSignals()}
app._parsers_dict = {}
GreenMarket._start_deferred_refresh = lambda self: None
market = GreenMarket()
market._refresh_timer.stop()
market.resize(490, 310)
market.show()


def settle_layout():
    # Flush posted layout requests, not a time-dependent network/status timer.
    for _ in range(4):
        app.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        app.processEvents()


def geometry():
    return {
        'body': [market._market_body.width(), market._market_body.height()],
        'tabs': [market.tabs.x(), market.tabs.y(),
                 market.tabs.width(), market.tabs.height()],
        'footer_height': market.status.parentWidget().height(),
        'status_height': market.status.height(),
        'required_height': market.status.heightForWidth(market.status.width()),
    }


market._set_gear_status('Synthetic P99 item index ready')
market.status.setText('PigParse Green ready')
settle_layout()
short = geometry()
market.status.setText(
    'PigParse Green offline · using its cache · '
    'External network disabled in the synthetic native audit')
settle_layout()
wrapped = geometry()
market.resize(245, 155)
settle_layout()
resized = geometry()
market.status.setText('PigParse Green ready\nCached listings available')
settle_layout()
explicit_lines = geometry()
market.status.setText('A longer source failure remains fully readable. ' * 12)
settle_layout()
long = geometry()

styles = []
for stylesheet in ('', 'font-size: 18px;',
                   'font-size: 18px; padding: 6px 13px;',
                   'font-size: 18px; padding: 6px 13px; border: 2px solid red;'):
    label = _MarketStatusLabel('Ready')
    reference = QLabel('Ready\nUpdated')
    for widget in (label, reference):
        widget.setWordWrap(True)
        widget.setStyleSheet(stylesheet)
        widget.ensurePolished()
    one = label.minimumSizeHint().height()
    label.setText('Ready\nUpdated')
    two = label.minimumSizeHint().height()
    reference_height = reference.heightForWidth(320)
    label.setText('A longer source failure remains fully readable. ' * 12)
    reference.setText(label.text())
    styles.append({
        'one': one, 'two': two, 'reference_two': reference_height,
        'long': label.heightForWidth(320),
        'reference_long': reference.heightForWidth(320),
    })

print(json.dumps({
    'short': short, 'wrapped': wrapped, 'resized': resized,
    'explicit_lines': explicit_lines, 'long': long, 'styles': styles,
}))
app.quit()
'''


@pytest.fixture(scope='module')
def status_layout():
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    completed = subprocess.run(
        [sys.executable, '-B', '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_one_and_two_line_statuses_keep_tabs_stable_before_and_after_resize(
        status_layout):
    baseline = status_layout['short']
    for name in ('wrapped', 'resized', 'explicit_lines'):
        assert status_layout[name] == baseline


def test_long_status_can_expand_without_clipping(status_layout):
    short, long = status_layout['short'], status_layout['long']
    assert long['required_height'] > short['required_height']
    assert long['status_height'] >= long['required_height']
    assert long['footer_height'] > short['footer_height']
    assert long['tabs'][3] >= 220


def test_two_line_reserve_tracks_fonts_padding_and_long_text(status_layout):
    cases = status_layout['styles']
    for case in cases:
        assert case['one'] == case['two'] == case['reference_two']
        assert case['long'] == case['reference_long'] > case['two']
    assert cases[1]['one'] > cases[0]['one']
    assert cases[2]['one'] > cases[1]['one']
    assert cases[3]['one'] > cases[2]['one']
