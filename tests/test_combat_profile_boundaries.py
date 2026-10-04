import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp

app = VantageApp([])
stamp = datetime.datetime(2026, 1, 1, 10, 0, 0)
app._parse((
    stamp, "You slash a skeleton for 10 points of damage.",
    "Alice", "Green"))
app._parse((
    stamp + datetime.timedelta(seconds=1),
    "You slash a skeleton for 20 points of damage.", "Bob", "Green"))
combat = app._parsers_dict["combat"]
records = combat._combat_archive.summaries()
active = combat._tracker.current()
print(json.dumps({
    "saved": [[row.target, row.character, row.server, row.total_damage]
              for row in records],
    "active": [active.target, active.total_damage] if active else None,
    "profile": list(combat._combat_profile),
}))
app.quit()
"""


def test_interleaved_character_logs_never_merge_or_mislabel_fights(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, check=True,
        capture_output=True, text=True, timeout=35)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["saved"] == [["a skeleton", "Alice", "Green", 10]]
    assert result["active"] == ["a skeleton", 20]
    assert result["profile"] == ["Bob", "Green"]
