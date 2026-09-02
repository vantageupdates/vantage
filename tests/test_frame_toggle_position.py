import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtCore import QPoint
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
panel = app._parsers_dict['timers']
panel.show()
panel.move(430, 315)
app.processEvents()
expected = QPoint(panel.pos())
native_flags = panel._set_flags

def simulate_windows_recreation():
    native_flags()
    panel.move(expected.x(), expected.y() - 36)

panel._set_flags = simulate_windows_recreation
panel._toggle_frame()
app.processEvents()
first = QPoint(panel.pos())
panel._toggle_frame()
app.processEvents()
second = QPoint(panel.pos())
print(json.dumps({
    'expected': [expected.x(), expected.y()],
    'first': [first.x(), first.y()],
    'second': [second.x(), second.y()],
}))
app.quit()
"""


def test_frame_toggle_preserves_exact_screen_anchor(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["first"] == result["expected"]
    assert result["second"] == result["expected"]
