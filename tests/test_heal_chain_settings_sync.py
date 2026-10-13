"""A chat interval update must not be overwritten by the embedded settings."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_chat_interval_and_embedded_settings_stay_in_sync():
    script = r'''
import json
from datetime import datetime
from native_audit_fixture import isolate
isolate()
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from PySide6.QtTest import QTest
app = VantageApp([])
heals = app._parsers_dict['heals']
heals._set_collapsed(False)
heals.resize(heals._design_size)
heals.show()
heals._show_inline_settings()
QTest.qWait(50)
assert heals.settings_tab.verticalScrollBar().maximum() > 0
controls = [heals.monitor_enabled, heals.settings_interval, heals.cast_seconds,
            heals.hotkey_format, heals.own_marker, heals.notify_turn]
for upper, lower in zip(controls, controls[1:]):
    assert upper.geometry().bottom() < lower.geometry().top()
heals.settings_tab.ensureWidgetVisible(heals.notify_turn)
QTest.qWait(20)
assert heals.settings_tab.verticalScrollBar().value() > 0
heals.parse(datetime.now(), "Cleric tells the guild, '!KI7'")
assert heals.interval.value() == 7
assert heals.settings_interval.value() == 7
heals.own_marker.setText('RAMP01')
heals._save_embedded_settings()
assert config.data['heals']['interval'] == 7
assert config.data['heals']['own_marker'] == 'RAMP01'
heals.settings_interval.setValue(3)
assert heals.interval.value() == 3
heals.interval.setValue(5)
assert heals.settings_interval.value() == 5
heals.parse(datetime.now(), "You say, '001 CH -- Tank'")
assert heals._tracker.local_marker == '001'
assert heals._tracker.casts[-1].tank == 'Tank'
print(json.dumps({'interval': config.data['heals']['interval']}))
app.quit()
'''
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'tests'), str(ROOT / 'src')))
    result = subprocess.run(
        [sys.executable, '-B', '-c', script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {'interval': 5}
