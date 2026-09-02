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
if panel._collapsed:
    panel._set_collapsed(False)
panel.setGeometry(100, 100, 520, 360)
panel.show()
app.processEvents()

normal_handles = {
    name: handle.isVisible()
    for name, handle in panel._resize_handles.items()
}

panel._start_panel_resize('bottom', QPoint(620, 460))
panel._drag_panel_resize(QPoint(620, 520))
panel._stop_panel_resize()
bottom = panel.geometry()

panel._start_panel_resize('right', QPoint(620, 520))
panel._drag_panel_resize(QPoint(700, 520))
panel._stop_panel_resize()
right = panel.geometry()

panel._start_panel_resize('top_left', QPoint(100, 100))
panel._drag_panel_resize(QPoint(70, 80))
panel._stop_panel_resize()
top_left = panel.geometry()

panel._set_collapsed(True)
rolled_handles = {
    name: handle.isVisible()
    for name, handle in panel._resize_handles.items()
}
panel._start_panel_resize('right', QPoint(0, 0))
rolled_started_resize = panel._panel_resize_state is not None

panel._set_collapsed(False)
app.processEvents()
expanded_handles = {
    name: handle.isVisible()
    for name, handle in panel._resize_handles.items()
}

panel._toggle_frame()
app.processEvents()
framed_handles = {
    name: handle.isVisible()
    for name, handle in panel._resize_handles.items()
}

def values(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]

print(json.dumps({
    'normal_handles': normal_handles,
    'bottom': values(bottom),
    'right': values(right),
    'top_left': values(top_left),
    'rolled_handles': rolled_handles,
    'rolled_started_resize': rolled_started_resize,
    'expanded_handles': expanded_handles,
    'framed_handles': framed_handles,
}))
app.quit()
"""


def test_full_panel_resizes_from_every_edge_without_rollup(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert all(result["normal_handles"].values())
    assert result["bottom"] == [100, 100, 520, 420]
    assert result["right"] == [100, 100, 600, 420]
    assert result["top_left"] == [70, 80, 630, 440]
    assert not any(result["rolled_handles"].values())
    assert result["rolled_started_resize"] is False
    assert all(result["expanded_handles"].values())
    assert not any(result["framed_handles"].values())
