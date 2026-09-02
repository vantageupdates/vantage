import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_every_authored_surface_has_control_header_and_tab_tooltips(tmp_path):
    output = tmp_path / "audit"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    env["VANTAGE_TEST_OUTPUT"] = str(output)
    subprocess.run(
        [sys.executable, str(ROOT / "work" / "closure_ui_audit.py")],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        timeout=60)
    report = json.loads(
        (output / "closure-ui-audit.json").read_text(encoding="utf-8"))

    for surface, results in report.items():
        assert results["missing_tooltips"] == [], surface
        assert results["missing_accessible_names"] == [], surface
        assert results["missing_header_tooltips"] == [], surface
        assert results["missing_tab_tooltips"] == [], surface
