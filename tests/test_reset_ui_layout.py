import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import copy
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from vantage.helpers import config
from vantage.helpers.application import VantageApp

content = {
    'active_spells': [{'name': 'Clarity II', 'remaining': 921}],
    'profiles': {'green|mindflux': {'level': 60, 'class': 'Enchanter'}},
    'timers': [{'timer_id': 'frenzy', 'name': 'Frenzy', 'remaining': 1337}],
    'combat': [{'target': 'A crystalline devourer', 'damage': 5555}],
    'watches': ['Fungi Covered Scale Tunic'],
    'alerts': [{'seller': 'Trader', 'item': 'Jade Mace'}],
    'zone': 'velketor\'s labyrinth',
    'zone_content': {'mobs': ['Crystal Eyes']},
    'quest_title': 'Druid Epic Quest',
    'quest_steps': ['Find Telin Darkforest.'],
    'quest_checked': ['step-key'],
}
config.data['spells']['active_timer_state'] = copy.deepcopy(content['active_spells'])
config.data['general']['character_profiles'] = copy.deepcopy(content['profiles'])
config.data['timers']['items'] = copy.deepcopy(content['timers'])
config.data['combat']['saved_history'] = copy.deepcopy(content['combat'])
config.data['market']['live_watch_items'] = copy.deepcopy(content['watches'])
config.data['market']['live_auction_events'] = copy.deepcopy(content['alerts'])
config.data['zones']['last_zone'] = content['zone']
config.data['zones']['cached_content'] = copy.deepcopy(content['zone_content'])
config.data['quests']['checklist'].update({
    'title': content['quest_title'], 'steps': copy.deepcopy(content['quest_steps']),
    'checked': copy.deepcopy(content['quest_checked'])})
config.data['quickbar'].update({
    'geometry': [35, 45, 500, 90], 'orientation': 'vertical',
    'opacity': 55, 'frameless': False, 'always_on_top': False,
    'show_header': False})
config.data['maps'].update({
    'geometry': [55, 65, 310, 320], 'opacity': 45,
    'frameless': False, 'always_on_top': False, 'toggled': True})
config.data['quests']['checklist']['geometry'] = [40, 50, 444, 333]
config.save()

app = VantageApp([])
bar = app._parsers_dict['quickbar']
launcher = bar._buttons['reload_ui']
bar.show()
app._parsers_dict['quests']._checklist.show()
launcher.setFocus()
app.processEvents()

def content_state():
    return {
        'active_spells': config.data['spells']['active_timer_state'],
        'profiles': config.data['general']['character_profiles'],
        'timers': config.data['timers']['items'],
        'combat': config.data['combat']['saved_history'],
        'watches': config.data['market']['live_watch_items'],
        'alerts': config.data['market']['live_auction_events'],
        'zone': config.data['zones']['last_zone'],
        'zone_content': config.data['zones']['cached_content'],
        'quest_title': config.data['quests']['checklist']['title'],
        'quest_steps': config.data['quests']['checklist']['steps'],
        'quest_checked': config.data['quests']['checklist']['checked'],
    }

live_content_before = copy.deepcopy(content_state())

prompt = []
before_cancel = config.ui_presentation_snapshot()
def answer_no(parent, title, text, buttons, default):
    prompt.append({
        'parent': parent is bar, 'title': title,
        'default_no': default == QMessageBox.StandardButton.No,
        'has_no': bool(buttons & QMessageBox.StandardButton.No),
        'preservation_copy': all(word in text for word in (
            'Buffs', 'timers', 'profiles', 'combat history',
            'Market watches', 'zone content', 'quest checklist')),
        'effects_disclosed': all(word in text for word in (
            'hides every window except the Quick Bar', 'expands rolled',
            'compact mode', 'column widths')),
    })
    return QMessageBox.StandardButton.No
QMessageBox.question = answer_no
cancelled = app.reset_ui_layout(parent=bar, launcher=launcher)
app.processEvents()
cancel_state = {
    'result': cancelled,
    'data_unchanged': (
        config.ui_presentation_snapshot() == before_cancel and
        content_state() == live_content_before),
    'focus_returned': launcher.hasFocus(),
}

notices = []
app._queue_quickbar_notice = lambda message: notices.append(message)
QMessageBox.question = staticmethod(
    lambda *_args: QMessageBox.StandardButton.Yes)
confirmed = app.reset_ui_layout(parent=bar, launcher=launcher)
QTest.qWait(220)
app.processEvents()
if not launcher.hasFocus():
    bar.restore_action_focus('reload_ui')
    QTest.qWait(20)
    app.processEvents()
with open(config._filename, encoding='utf-8') as source:
    persisted = json.load(source)
saved_defaults = True
for path, expected in config.UI_PRESENTATION_DEFAULTS.items():
    node = persisted
    for key in path:
        node = node[key]
    saved_defaults = saved_defaults and node == expected
success = {
    'result': confirmed,
    'content_preserved': content_state() == live_content_before,
    'saved_defaults': saved_defaults,
    'live_quickbar': [bar.x(), bar.y(), bar.width(), bar.height()] ==
        config.UI_PRESENTATION_DEFAULTS[('quickbar', 'geometry')],
    'orientation': bar._orientation,
    'opacity': round(bar.windowOpacity() * 100),
    'frameless': bar._frameless,
    'always_top': bar._always_on_top,
    'others_hidden': all(
        not parser.isVisible() for parser in app._parsers
        if parser is not bar),
    'checklist_hidden': not app._parsers_dict['quests']._checklist.isVisible(),
    'focus_returned': launcher.hasFocus(),
    'notices': notices,
}

# A failed durable verification rolls both config and the live presentation
# back, and must never announce success.
config.data['quickbar']['geometry'] = [70, 80, 480, 88]
config.data['quickbar']['opacity'] = 65
bar.apply_saved_presentation()
config.save()
failure_snapshot = config.ui_presentation_snapshot()
failure_live_geometry = [bar.x(), bar.y(), bar.width(), bar.height()]
failure_content = copy.deepcopy(content_state())
failure_notices = []
failure_messages = []
app._queue_quickbar_notice = lambda message: failure_notices.append(message)
app.show_overlay_notification = (
    lambda title, message, **_kwargs: failure_messages.append([title, message]))
real_verify = config.verify_saved_ui_presentation
config.verify_saved_ui_presentation = (
    lambda expected=None: expected == failure_snapshot)
failed = app.reset_ui_layout(parent=bar, launcher=launcher, confirm=False)
app.processEvents()
config.verify_saved_ui_presentation = real_verify
rollback = {
    'result': failed,
    'snapshot': config.ui_presentation_snapshot() == failure_snapshot,
    'live_geometry': [bar.x(), bar.y(), bar.width(), bar.height()] == failure_live_geometry,
    'live_opacity': round(bar.windowOpacity() * 100) == 65,
    'content': content_state() == failure_content,
    'no_success_notice': failure_notices == [],
    'restored_message': bool(
        failure_messages and 'previous layout was restored' in
        failure_messages[-1][1]),
    'focus_returned': launcher.hasFocus(),
}

# If rollback persistence itself cannot be verified, never make the stronger
# restored claim. Give one actionable recovery instruction instead.
unverified_messages = []
app.show_overlay_notification = (
    lambda title, message, **_kwargs: unverified_messages.append([title, message]))
config.verify_saved_ui_presentation = lambda *_args, **_kwargs: False
app.reset_ui_layout(parent=bar, launcher=launcher, confirm=False)
config.verify_saved_ui_presentation = real_verify
unverified_copy = bool(
    unverified_messages and
    'could not verify restoration' in unverified_messages[-1][1] and
    'Restart Vantage' in unverified_messages[-1][1] and
    'previous layout was restored' not in unverified_messages[-1][1])

print(json.dumps({
    'prompt': prompt, 'cancel': cancel_state,
    'success': success, 'rollback': rollback,
    'label': launcher.accessibleName(),
    'tooltip': launcher.toolTip(),
    'unverified_copy': unverified_copy,
}))
app.quit()
"""


def test_reset_ui_layout_is_confirmed_presentation_only_and_transactional(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['prompt'] == [{
        'parent': True, 'title': 'Reset UI Layout?', 'default_no': True,
        'has_no': True, 'preservation_copy': True,
        'effects_disclosed': True}]
    assert result['cancel'] == {
        'result': False, 'data_unchanged': True, 'focus_returned': True}
    assert result['success'] == {
        'result': True,
        'content_preserved': True,
        'saved_defaults': True,
        'live_quickbar': True,
        'orientation': 'horizontal',
        'opacity': 92,
        'frameless': True,
        'always_top': True,
        'others_hidden': True,
        'checklist_hidden': True,
        'focus_returned': True,
        'notices': ['UI layout reset · content and active timers were preserved'],
    }
    assert result['rollback'] == {
        'result': False,
        'snapshot': True,
        'live_geometry': True,
        'live_opacity': True,
        'content': True,
        'no_success_notice': True,
        'restored_message': True,
        'focus_returned': True,
    }
    assert result['label'] == 'Reset UI Layout'
    assert 'gameplay data is preserved' in result['tooltip']
    assert result['unverified_copy'] is True
