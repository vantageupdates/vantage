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
spells = app._parsers_dict['spells']
now = datetime.datetime.now().replace(microsecond=0)

# A worn clicky whose item cast time differs from the base spell record.
spells.parse(now, 'You begin casting Snare.')
spells.parse(
    now + datetime.timedelta(milliseconds=100),
    "Your Elder Spiritist's Gauntlets begins to glow.")
spells.parse(
    now + datetime.timedelta(seconds=4),
    'A hill giant has been ensnared.')

# An instant, item-only self click with no You begin casting line.
spells.parse(
    now + datetime.timedelta(seconds=10),
    "Your Journeyman's Boots begins to glow.")
spells.parse(
    now + datetime.timedelta(seconds=10, milliseconds=50),
    'Your feet feel quick.')

enemy = spells._spell_container.get_spell_target_by_name('A hill giant')
you = spells._spell_container.get_spell_target_by_name('__you__')
enemy_spell = enemy.spell_widgets()[0]
you_spell = you.spell_widgets()[0]
print(json.dumps({
    'enemy_name': enemy_spell.spell.name,
    'enemy_source': enemy_spell.spell.source_item,
    'enemy_tooltip': enemy_spell.toolTip(),
    'self_name': you_spell.spell.name,
    'self_source': you_spell.spell.source_item,
    'self_tooltip': you_spell.toolTip(),
}))
app.quit()
"""


def test_casted_and_instant_item_clicks_appear_in_spell_window(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["enemy_name"] == "snare"
    assert result["enemy_source"] == "Elder Spiritist's Gauntlets"
    assert "Item click" in result["enemy_tooltip"]
    assert result["self_name"] == "journeymanboots"
    assert result["self_source"] == "Journeyman's Boots"
    assert "Item click" in result["self_tooltip"]

