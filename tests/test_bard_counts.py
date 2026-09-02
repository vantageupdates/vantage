import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers.bard_counts import BardAeCounter


ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.datetime(2026, 8, 30, 12, 0, 0)


def test_bard_count_discards_one_anonymous_wince_but_keeps_burst():
    counter = BardAeCounter()
    assert counter.ingest(STAMP, "a beetle winces.", now=0) == []
    assert counter.flush(now=1.6) == []

    counter.ingest(STAMP, "a beetle winces.", now=2)
    counter.ingest(STAMP, "a spider winces.", now=2.2)
    result = counter.flush(now=3.8)
    assert len(result) == 1
    assert result[0].text == "2 Total | 2 Hits"
    assert result[0].spell_name == ""


def test_bard_count_names_only_unambiguous_landings_and_resists():
    counter = BardAeCounter()
    counter.ingest(
        STAMP, "a beetle is bound by silver strands of music.", now=0)
    result = counter.flush(now=1.6)
    assert result[0].text == "Selo's Assonant Strane: 1 Total | 1 Hit"

    counter.ingest(
        STAMP,
        "Your target resisted the Chords of Dissonance spell.", now=2)
    result = counter.flush(now=3.6)
    assert result[0].text == "Chords of Dissonance: 1 Total | 1 Resist"

    # A generic wince attached to a named burst makes attribution ambiguous.
    counter.ingest(
        STAMP, "a beetle is bound in chords of music.", now=4)
    counter.ingest(STAMP, "someone winces.", now=4.1)
    result = counter.flush(now=5.7)
    assert result[0].text == "2 Total | 2 Hits"
    assert result[0].spell_name == ""


def test_bard_count_session_storage_has_a_hard_ceiling():
    counter = BardAeCounter(max_sessions=3)
    for index in range(8):
        counter.ingest(
            STAMP + datetime.timedelta(seconds=index * 3),
            f"target {index} winces.", now=0)
    assert len(counter.sessions) <= 3


SCRIPT = r"""
import datetime
import json
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox
from vantage.helpers.application import VantageApp
from vantage.helpers import config

app = VantageApp([])
spells = app._parsers_dict['spells']
if spells._collapsed:
    spells._set_collapsed(False)
config.data['spells']['bard_count_enabled'] = True
config.data['spells']['bard_count_overlay'] = False
config.data['spells']['bard_count_audio'] = False
spells._bard_config_updated()
app._settings._set_values()
stamp = datetime.datetime(2026, 8, 30, 12, 0, 0)
for index in range(5):
    spells.parse(stamp, f'A death beetle {index} winces.')
spells.parse(
    stamp, 'Your target resisted the Chords of Dissonance spell.')
QTest.qWait(1700)
spells._flush_bard_counts()
rows = spells._bard_group.rows()
names = {
    'spells:bard_count_enabled', 'spells:bard_count_overlay',
    'spells:bard_count_audio'}
checks = [
    widget for widget in app._settings.scaled_surface.findChildren(QCheckBox)
    if widget.objectName() in names]
print(json.dumps({
    'visible': spells._bard_group.isVisible(),
    'rows': [row.text() for row in rows],
    'tooltips': [bool(row.toolTip()) for row in rows],
    'sessions': len(spells._bard_counter.sessions),
    'settings': {
        widget.objectName(): [bool(widget.toolTip()), widget.isEnabled()]
        for widget in checks},
}))
app.quit()
"""


def test_bard_count_ui_keeps_compact_history_without_forced_audio(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["visible"] is True
    assert result["rows"] == [
        "12:00:00 · 6 Total | 5 Hits | 1 Resist"]
    assert result["tooltips"] == [True]
    assert result["sessions"] == 0
    assert result["settings"] == {
        "spells:bard_count_enabled": [True, True],
        "spells:bard_count_overlay": [True, True],
        "spells:bard_count_audio": [True, True],
    }
