import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers.character_context import CharacterContextTracker


ROOT = Path(__file__).resolve().parents[1]


def test_exact_eqtool_character_group_and_pet_messages_are_bounded():
    tracker = CharacterContextTracker(max_profiles=3)
    context, changed = tracker.ingest(
        "Mindflux", "Green",
        "You have finished memorizing Zumaik`s Animation.")
    assert changed is True
    assert (context.player_class, context.level) == ("Enchanter", 55)

    context, _ = tracker.ingest(
        "Mindflux", "Green",
        "You notify Kelder that you agree to join the group.")
    assert context.group_leader == "Kelder"

    tracker.ingest(
        "Mindflux", "Green", "You begin casting Zumaik`s Animation.")
    context, _ = tracker.ingest(
        "Mindflux", "Green", "Gabtik says 'At your service Master.'")
    assert (context.pet_name, context.pet_state) == ("Gabtik", "Active")
    context, _ = tracker.ingest(
        "Mindflux", "Green",
        "Gabtik tells you, 'Attacking a frost giant Master.'")
    assert context.pet_state == "Attacking"
    context, _ = tracker.ingest(
        "Mindflux", "Green",
        "Gabtik says 'Sorry to have failed you, oh Great One.'")
    assert (context.pet_name, context.pet_state, context.pet_spell) == (
        "", "", "")

    # A nearby pet creation cannot become ours without our preceding summon.
    context, changed = tracker.ingest(
        "Mindflux", "Green", "SomeonePet says 'At your service Master.'")
    assert context.pet_name == ""
    assert changed is False

    for index in range(5):
        tracker.ingest(f"Player{index}", "Green", "Welcome to EverQuest!")
    assert len(tracker.snapshot()) == 3


SCRIPT = r"""
import datetime
import json
from vantage.helpers.application import VantageApp
from vantage.helpers import config

app = VantageApp([])
spells = app._parsers_dict['spells']
combat = app._parsers_dict['combat']
for panel in (spells, combat):
    if panel._collapsed:
        panel._set_collapsed(False)

stamp = datetime.datetime(2026, 8, 30, 12, 0, 0)
def line(text):
    app._parse((stamp, text, 'Mindflux', 'Green'))

line('You have finished memorizing Zumaik`s Animation.')
line('You have gained a level! Welcome to level 60!')
line('You notify Kelder that you agree to join the group.')
line('You begin casting Zumaik`s Animation.')
line("Gabtik says 'At your service Master.'")
line("Gabtik tells you, 'Attacking a frost giant Master.'")

profile = next(iter(config.data['general']['character_profiles'].values()))
app.update_character_level('Harmflux', 'Green', 55)
spells._refresh_character_profiles()
harmflux_index = next(
    index for index in range(spells._character_widget.count())
    if (spells._character_widget.itemData(index) or {}).get('character') ==
    'Harmflux')
spells._character_widget.setCurrentIndex(harmflux_index)
print(json.dumps({
    'detected_level': profile['level'],
    'selected_level': spells._level_widget.value(),
    'character_choices': [
        spells._character_widget.itemText(index)
        for index in range(spells._character_widget.count())],
    'level_tooltip': spells._level_widget.toolTip(),
    'pet_status': combat.pet_context.text(),
    'pet_tooltip': combat.pet_context.toolTip(),
    'pet_rows': combat._tracker.pet_rows(),
    'profile': profile,
}))
app.quit()
"""


def test_character_context_updates_spells_combat_and_persistent_profile(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["detected_level"] == 60
    assert result["selected_level"] == 55
    assert result["character_choices"] == [
        "All", "Harmflux · Green", "Mindflux · Green"]
    assert "Enchanter" in result["level_tooltip"]
    assert "LEADER Kelder" in result["pet_status"]
    assert "PET Gabtik (Attacking)" in result["pet_status"]
    assert "Source: exact messages" in result["pet_tooltip"]
    assert result["pet_rows"] == [{
        "pet": "Gabtik", "owner": "Mindflux",
        "source": "Local pet context"}]
    assert result["profile"]["level"] == 60
    assert result["profile"]["player_class"] == "Enchanter"
    assert result["profile"]["group_leader"] == "Kelder"
    assert result["profile"]["pet_name"] == "Gabtik"
