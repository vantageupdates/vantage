import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.spells import item_click_spell_name


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

# An unrelated cast must not block an instant item-only click. JBoots emits
# neither a casting nor a glow anchor on P99; its landing line is authoritative.
spells.parse(
    now + datetime.timedelta(seconds=9),
    'You begin casting Clarity.')
spells.parse(
    now + datetime.timedelta(seconds=10),
    'Your feet feel quick.')

# A common ambiguous emote must not manufacture another item timer.
spells.parse(
    now + datetime.timedelta(seconds=11),
    'You feel different.')

pending_after_click = (
    spells._spell_trigger.spell.name if spells._spell_trigger else '')

enemy = spells._spell_container.get_spell_target_by_name('A hill giant')
you = spells._spell_container.get_spell_target_by_name('__you__')
enemy_spell = enemy.spell_widgets()[0]
you_spell = you.spell_widgets()[0]
self_tooltip_before_fade = you_spell.toolTip()
spells.parse(
    now + datetime.timedelta(seconds=12),
    'Your feet slow down.')
print(json.dumps({
    'enemy_name': enemy_spell.spell.name,
    'enemy_source': enemy_spell.spell.source_item,
    'enemy_tooltip': enemy_spell.toolTip(),
    'self_name': you_spell.spell.name,
    'self_source': you_spell.spell.source_item,
    'self_tooltip': self_tooltip_before_fade,
    'self_faded': you_spell.progress.property('Faded'),
    'self_count': len(you.spell_widgets()),
    'pending_after_click': pending_after_click,
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
    assert result["self_faded"] is True
    assert result["self_count"] == 1
    assert result["pending_after_click"] == "clarity"


def test_shipped_clicky_index_uses_current_project_1999_item_names():
    assert item_click_spell_name("Amulet of Necropotence") == (
        "Illusion: Skeleton")
    assert item_click_spell_name("Beguiler's Trousers") == "Clarity"
    assert item_click_spell_name("Staff of the Serpent") == (
        "Speed of the Shissar")
    assert item_click_spell_name("Elder Spiritist's Gauntlets") == "Snare"


PEGASUS_SCRIPT = r"""
import datetime
import json

from vantage.helpers.application import VantageApp
from vantage.parsers.spells import get_spell_duration

app = VantageApp([])
spells = app._parsers_dict['spells']
now = datetime.datetime.now().replace(microsecond=0)

# These are the exact three P99 log lines produced by the Pegasus cloak.
spells.parse(now, 'You begin casting Levitate.')
spells.parse(
    now + datetime.timedelta(seconds=1),
    'Your Pegasus Feather Cloak begins to glow.')
trigger_name = spells._spell_trigger.spell.name
trigger_source = spells._spell_trigger.spell.source_item
spells.parse(
    now + datetime.timedelta(seconds=6),
    'Your feet leave the ground.')

target = spells._spell_container.get_spell_target_by_name('__you__')
widget = target.spell_widgets()[0]
regular = spells.spell_book['Levitate']
print(json.dumps({
    'trigger_name': trigger_name,
    'trigger_source': trigger_source,
    'timer_name': widget.spell.name,
    'timer_source': widget.spell.source_item,
    'seconds': widget._seconds,
    'regular_level_60_seconds': get_spell_duration(regular, 60) * 6,
}))
app.quit()
"""


def test_pegasus_cloak_uses_fixed_twelve_minute_item_effect(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", PEGASUS_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["trigger_name"] == "levitation"
    assert result["trigger_source"] == "Pegasus Feather Cloak"
    assert result["timer_name"] == "levitation"
    assert result["timer_source"] == "Pegasus Feather Cloak"
    assert result["seconds"] == 12 * 60
    assert result["regular_level_60_seconds"] != result["seconds"]
