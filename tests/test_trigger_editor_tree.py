import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtWidgets import QTreeWidgetItemIterator
from vantage.helpers.application import VantageApp
from vantage.helpers import config
from vantage.helpers.settings import (
    CustomTriggerSettings, TRIGGER_ITEM_ID, TRIGGER_ITEM_KIND)

app = VantageApp([])
dialog = CustomTriggerSettings()
config.data['spells']['trigger_groups']['Raid'] = {
    'enabled': True, 'profiles': {'Gandalf': False}, 'order': 999}
dialog._load_from_config()

trigger_item = None
raid_item = None
iterator = QTreeWidgetItemIterator(dialog._triggers)
while iterator.value():
    item = iterator.value()
    kind = item.data(0, TRIGGER_ITEM_KIND)
    if kind == 'trigger' and trigger_item is None:
        trigger_item = item
    if kind == 'group' and item.data(0, TRIGGER_ITEM_ID) == 'Raid':
        raid_item = item
    iterator += 1

assert trigger_item is not None and raid_item is not None
name = str(trigger_item.data(0, TRIGGER_ITEM_ID))
parent = trigger_item.parent()
if parent:
    parent.takeChild(parent.indexOfChild(trigger_item))
else:
    dialog._triggers.takeTopLevelItem(
        dialog._triggers.indexOfTopLevelItem(trigger_item))
raid_item.addChild(trigger_item)
dialog._triggers.setCurrentItem(trigger_item)
dialog._persist_tree_structure()
moved = dialog._custom_triggers[name].category

before = len(dialog._custom_triggers)
dialog._clone_trigger()
clone_name = dialog._selected_trigger_name()
clone = dialog._custom_triggers[clone_name]

result = {
    'moved': moved,
    'clone_added': len(dialog._custom_triggers) == before + 1,
    'clone_disabled': clone.enabled is False,
    'clone_category': clone.category,
    'tree_tooltip': bool(dialog._triggers.toolTip()),
    'button_tooltips': all((
        dialog._add_trigger_button.toolTip(), dialog._add_group_button.toolTip(),
        dialog._clone_trigger_button.toolTip(),
        dialog._remove_trigger_button.toolTip(),
        dialog._save_trigger_button.toolTip())),
}
print(json.dumps(result))
dialog.close()
app.quit()
"""


def test_trigger_tree_moves_and_clones_real_trigger_data(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'moved': 'Raid',
        'clone_added': True,
        'clone_disabled': True,
        'clone_category': 'Raid',
        'tree_tooltip': True,
        'button_tooltips': True,
    }
