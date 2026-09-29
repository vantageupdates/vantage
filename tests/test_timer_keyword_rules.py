import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers.timer_keywords import (
    match_keyword_phrase, normalize_keyword_rules, own_say_message,
    validate_keyword_rule)
from vantage.helpers.device_sync import apply_sync_settings, export_sync_settings


ROOT = Path(__file__).resolve().parents[1]


def _rule(**overrides):
    value = {
        "enabled": True,
        "phrase": "stop camp",
        "action": "stop",
        "timer_id": "timer-1",
    }
    value.update(overrides)
    return value


def test_keyword_rule_validation_is_bounded_literal_and_defaults_off():
    assert validate_keyword_rule(_rule(enabled=None))["enabled"] is False
    with pytest.raises(ValueError, match="literal chat phrase"):
        validate_keyword_rule(_rule(phrase=""))
    with pytest.raises(ValueError, match="three literal"):
        validate_keyword_rule(_rule(phrase="%T"))
    with pytest.raises(ValueError, match="only one"):
        validate_keyword_rule(_rule(phrase="stop %T {timer}"))
    with pytest.raises(ValueError, match="Separate placeholders"):
        validate_keyword_rule(_rule(
            action="create", phrase="$make%T{duration}", timer_id=""))
    with pytest.raises(ValueError, match="exactly one"):
        validate_keyword_rule(_rule(
            action="create", phrase="$make {duration}", timer_id=""))
    with pytest.raises(ValueError, match="no longer exists"):
        validate_keyword_rule(_rule(), known_timer_ids={"other"})


def test_captured_create_duration_ignores_irrelevant_stored_default():
    rule = validate_keyword_rule(_rule(
        action="create", phrase="$maketimer %T {duration}", timer_id="",
        create_seconds="not used"))

    assert rule["create_seconds"] == 400
    assert match_keyword_phrase(
        rule["phrase"], "$maketimer Kennel Master Ae'le 6:40") == {
            "target": "Kennel Master Ae'le", "duration": "6:40"}


def test_literal_match_escapes_regex_and_preserves_apostrophe_names():
    assert match_keyword_phrase(
        "reset (camp)+ {timer}", "RESET (camp)+ Kennel Master Ae'le!") == {
            "timer": "Kennel Master Ae'le"}
    assert match_keyword_phrase("reset (camp)+ {timer}", "reset camp any") is None
    assert own_say_message("You say, 'killed Kennel Master Ae\'le'") == \
        "killed Kennel Master Ae'le"
    assert own_say_message("Friend says, 'killed Kennel Master Ae\'le'") == ""
    assert own_say_message("You tell your party, 'killed a mob'") == ""


def test_normalization_rejects_duplicates_and_limits_rule_count():
    values = [
        _rule(id=f"r-{index}", phrase=f"stop camp {index}")
        for index in range(70)]
    values.insert(1, _rule(id="duplicate", phrase=" STOP   CAMP 0 "))

    result = normalize_keyword_rules(values)

    assert len(result) == 64
    assert sum(rule["phrase"].casefold() == "stop camp 0" for rule in result) == 1


def test_keyword_rules_follow_existing_timer_device_sync_boundary():
    source = {
        "timers": {"keyword_rules": [validate_keyword_rule(_rule())]},
        "general": {"sync_timers": True},
    }
    portable = export_sync_settings(source, include_timers=True)
    current = {"timers": {"keyword_rules": []}, "general": {}}

    apply_sync_settings(current, portable, include_timers=True)

    assert current["timers"]["keyword_rules"] == \
        source["timers"]["keyword_rules"]
    assert "timers" not in export_sync_settings(
        source, include_timers=False)


RUNTIME_SCRIPT = r"""
import datetime
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import PHASE_IDLE, PHASE_RESPAWN, SpawnTimerState
from vantage.helpers.timer_keywords import validate_keyword_rule
import vantage.parsers.timers as timers_module

app = VantageApp([])
panel = app._parsers_dict['timers']
panel._zone_changed("Chardok")
notices = []
panel.announce = lambda message: (
    notices.append(message), panel.status.setText(message))

fixed = SpawnTimerState("Fixed camp", 120, zone="Kael Drakkel")
target_a = SpawnTimerState(
    "Kennel cycle A", 180, zone="Chardok",
    death_mobs=["Kennel Master Ae'le", "Kennel Master"])
target_b = SpawnTimerState(
    "Kennel cycle B", 240, zone="Chardok",
    death_mobs=["Kennel Master Ae'le", "Kennel Master"])
wrong_zone = SpawnTimerState(
    "Wrong-zone kennel", 300, zone="Kael Drakkel",
    death_mobs=["Kennel Master Ae'le"])
for timer in (fixed, target_a, target_b, wrong_zone):
    panel._register_timer(timer)

stamp = datetime.datetime(2026, 9, 29, 12, 0, 0)

def apply(rule, message, seconds):
    config.data['timers']['keyword_rules'] = [validate_keyword_rule(rule)]
    panel.parse(stamp + datetime.timedelta(seconds=seconds), message)

apply({
    'enabled': True, 'phrase': 'start fixed', 'action': 'start',
    'timer_id': fixed.timer_id,
}, "You say, 'start fixed'", 1)
started_deadline = fixed.deadline
apply({
    'enabled': True, 'phrase': 'reset fixed', 'action': 'reset',
    'timer_id': fixed.timer_id,
}, "You say, 'reset fixed'", 2)
reset_deadline = fixed.deadline
apply({
    'enabled': True, 'phrase': 'pause fixed', 'action': 'pause',
    'timer_id': fixed.timer_id,
}, "You say, 'pause fixed'", 3)
paused_remaining = fixed.paused_remaining
apply({
    'enabled': True, 'phrase': 'pause fixed again', 'action': 'pause',
    'timer_id': fixed.timer_id,
}, "You say, 'pause fixed again'", 3)
pause_idempotent = (
    not fixed.running and fixed.paused_remaining == paused_remaining)
apply({
    'enabled': True, 'phrase': 'start paused', 'action': 'start',
    'timer_id': fixed.timer_id,
}, "You say, 'start paused'", 3)
start_does_not_resume = (
    not fixed.running and fixed.paused_remaining == paused_remaining)
apply({
    'enabled': True, 'phrase': 'resume fixed', 'action': 'resume',
    'timer_id': fixed.timer_id,
}, "You say, 'resume fixed'", 4)
resumed = fixed.running and fixed.paused_remaining is None
apply({
    'enabled': True, 'phrase': 'stop fixed', 'action': 'stop',
    'timer_id': fixed.timer_id,
}, "You say, 'stop fixed'", 5)
stopped = fixed.phase == PHASE_IDLE and not fixed.running
stop_kept_timer = fixed.timer_id in panel._states

# One matching target is rejected as ambiguous until the rule explicitly opts
# into all matching saved spawn triggers. A timer in another zone is untouched.
dynamic = {
    'enabled': True, 'phrase': 'killed %T', 'action': 'reset',
    'timer_id': '', 'all_matches': False,
}
apply(dynamic, "You say, 'killed Kennel Master'", 6)
ambiguous_rejected = not target_a.running and not target_b.running
dynamic['all_matches'] = True
apply(dynamic, "You say, 'killed Kennel Master Ae\'le'", 7)
all_current_zone = target_a.running and target_b.running
wrong_zone_untouched = not wrong_zone.running

# Only own /say is accepted.
before_other = (target_a.deadline, target_b.deadline)
panel.parse(stamp + datetime.timedelta(seconds=8),
            "Otherplayer says, 'killed Kennel Master Ae\'le'")
panel.parse(stamp + datetime.timedelta(seconds=9),
            "You tell your party, 'killed Kennel Master Ae\'le'")
other_ignored = before_other == (target_a.deadline, target_b.deadline)

# Create belongs to the shared primary registry; every independent window sees
# the same object. The captured 6:40 is exactly 400 seconds.
secondary = panel.create_secondary_window()
secondary._refresh_zone_filter('Kael Drakkel')
secondary.show()
app.processEvents()
accessible_announcements = []
timers_module.QAccessible.updateAccessibility = \
    lambda event: accessible_announcements.append(type(event).__name__)
create_rule = {
    'enabled': True, 'phrase': '$maketimer %T {duration}',
    'action': 'create', 'timer_id': '', 'create_seconds': 'ignored',
}
apply(create_rule, "You say, '$maketimer a royal guard 6:40'", 10)
secondary_announcement_count = len(accessible_announcements)
created = next(timer for timer in panel._states.values()
               if timer.name == 'a royal guard')
created_id = created.timer_id
create_count = len(panel._states)
panel.parse(stamp + datetime.timedelta(seconds=10),
            "You say, '$maketimer a royal guard 6:40'")
same_line_deduped = len(panel._states) == create_count
panel.parse(stamp + datetime.timedelta(seconds=11),
            "You say, '$maketimer a royal guard 6:40'")
existing_no_overwrite = (
    len(panel._states) == create_count and
    panel._states[created_id].respawn_seconds == 400)
shared_registry = (
    secondary._states is panel._states and created_id in secondary._rows and
    secondary._rows[created_id].isHidden())

# An unknown-zone Create is rejected unless the rule explicitly allows the
# predictable Unassigned destination.
panel._zone_changed("")
create_default = {
    'enabled': True, 'phrase': '$new {name}', 'action': 'create',
    'timer_id': '', 'create_seconds': 90, 'allow_unassigned': False,
}
apply(create_default, "You say, '$new unknown camp'", 12)
unknown_rejected = not any(
    timer.name == 'unknown camp' for timer in panel._states.values())
create_default['allow_unassigned'] = True
apply(create_default, "You say, '$new unassigned camp'", 13)
unassigned = next(timer for timer in panel._states.values()
                  if timer.name == 'unassigned camp')

config.save()
result = {
    'start_then_reset': (
        started_deadline is not None and reset_deadline > started_deadline),
    'paused': paused_remaining is not None and not fixed.running,
    'pause_idempotent': pause_idempotent,
    'start_does_not_resume': start_does_not_resume,
    'resumed': resumed,
    'stopped': stopped,
    'stop_kept_timer': stop_kept_timer,
    'ambiguous_rejected': ambiguous_rejected,
    'all_current_zone': all_current_zone,
    'wrong_zone_untouched': wrong_zone_untouched,
    'other_ignored': other_ignored,
    'created': [created.respawn_seconds, created.zone, created.running,
                created.phase == PHASE_RESPAWN],
    'same_line_deduped': same_line_deduped,
    'existing_no_overwrite': existing_no_overwrite,
    'shared_registry': shared_registry,
    'secondary_announcement_count': secondary_announcement_count,
    'unknown_rejected': unknown_rejected,
    'unassigned': [unassigned.respawn_seconds, unassigned.zone,
                   unassigned.running],
    'saved_rule_count': len(config.data['timers']['keyword_rules']),
    'last_notice': notices[-1],
}
secondary.close()
app.processEvents()
print(json.dumps(result))
app.quit()
"""


REOPEN_SCRIPT = r"""
import json
from vantage.helpers import config
from vantage.helpers.application import VantageApp

app = VantageApp([])
panel = app._parsers_dict['timers']
result = {
    'rules': config.data['timers']['keyword_rules'],
    'button_text': panel.keyword_rules_button.text(),
    'button_name': panel.keyword_rules_button.accessibleName(),
}
print(json.dumps(result))
app.quit()
"""


def _run_script(script, profile, timeout=45):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(profile)
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=timeout)
    assert "Traceback" not in completed.stderr, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_keyword_actions_create_and_shared_timer_windows_runtime(tmp_path):
    profile = tmp_path / "runtime-profile"
    result = _run_script(RUNTIME_SCRIPT, profile)

    assert result["start_then_reset"] is True
    assert result["paused"] is True
    assert result["pause_idempotent"] is True
    assert result["start_does_not_resume"] is True
    assert result["resumed"] is True
    assert result["stopped"] is True
    assert result["stop_kept_timer"] is True
    assert result["ambiguous_rejected"] is True
    assert result["all_current_zone"] is True
    assert result["wrong_zone_untouched"] is True
    assert result["other_ignored"] is True
    assert result["created"] == [400, "Chardok", True, True]
    assert result["same_line_deduped"] is True
    assert result["existing_no_overwrite"] is True
    assert result["shared_registry"] is True
    assert result["secondary_announcement_count"] == 1
    assert result["unknown_rejected"] is True
    assert result["unassigned"] == [90, "", True]
    assert result["saved_rule_count"] == 1
    assert "Created and started" in result["last_notice"]

    reopened = _run_script(REOPEN_SCRIPT, profile)
    assert len(reopened["rules"]) == 1
    assert reopened["rules"][0]["phrase"] == "$new {name}"
    assert reopened["button_text"] == "1/1"
    assert reopened["button_name"] == \
        "Keyword timer rules, 1 enabled, 1 saved"


UI_SCRIPT = r"""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.spawn_timer import SpawnTimerState
import vantage.parsers.timers as timers_module
from vantage.parsers.timers import TimerKeywordRulesDialog

app = VantageApp([])
panel = app._parsers_dict['timers']
timer = SpawnTimerState('Camp timer', 120, zone='Chardok')
dialog = TimerKeywordRulesDialog([timer], [])
dialog.show()
QTest.qWait(20)

dialog.action.setCurrentIndex(dialog.action.findData('create'))
dialog.phrase.setText('$maketimer %T {duration}')
dialog.create_duration.setText('not a duration')
app.processEvents()
captured_duration_state = {
    'hidden': not dialog.create_duration.isVisible(),
    'disabled': not dialog.create_duration.isEnabled(),
    'label_hidden': not dialog.create_duration_label.isVisible(),
}
dialog.enabled.setChecked(True)
dialog._add_rule()
created_rule = dialog.rules()[0]
off_rule = dict(created_rule)
off_rule['enabled'] = False
config.data['timers']['keyword_rules'] = [off_rule]
panel._refresh_keyword_rules_button()
off_count = [
    panel.keyword_rules_button.text(),
    panel.keyword_rules_button.accessibleName()]
dialog.action.setCurrentIndex(dialog.action.findData('stop'))
dialog.phrase.setText('stop camp')
dialog.target.setCurrentIndex(dialog.target.findData(timer.timer_id))
dialog.create_duration.setText('irrelevant invalid duration')
app.processEvents()
non_create_hidden = (
    not dialog.create_duration.isVisible() and
    not dialog.create_duration.isEnabled() and
    not dialog.allow_unassigned.isVisible() and
    not dialog.allow_unassigned.isEnabled())
non_create_candidate = dialog._candidate()

dialog.table.selectRow(0)
app.processEvents()
before_remove = len(dialog.rules())

confirmation = {}
def answer_confirmation(label):
    def answer():
        box = next(widget for widget in app.topLevelWidgets()
                   if isinstance(widget, QMessageBox) and widget.isVisible())
        buttons = {button.text(): button for button in box.buttons()}
        confirmation['labels'] = sorted(buttons)
        confirmation['default'] = box.defaultButton().text()
        confirmation['escape'] = box.escapeButton().text()
        buttons[label].click()
    QTimer.singleShot(0, answer)

answer_confirmation('Cancel')
native_cancelled = not dialog._confirm_remove_rule(created_rule['phrase'])
dialog._confirm_remove_rule = lambda _phrase: False
dialog._remove_rule()
cancel_kept = len(dialog.rules()) == before_remove
dialog.table.selectRow(0)
app.processEvents()
dialog._confirm_remove_rule = lambda _phrase: True
dialog._remove_rule()
app.processEvents()
removed_count = len(dialog.rules())
remove_focus = dialog.scaled_surface.focusWidget()
removed = (
    not dialog.rules() and
    dialog.scaled_surface.focusWidget() is dialog.add_button)

# The native dialog accepts Escape and does not alter the caller-owned list.
escape = TimerKeywordRulesDialog([timer], [created_rule])
escape.show()
QTest.qWait(20)
QTest.keyClick(escape, Qt.Key.Key_Escape)
app.processEvents()
escape_closed = not escape.isVisible()

# Rebuild a row and prove Tab leaves the grid rather than wrapping cells.
flow = TimerKeywordRulesDialog([timer], [created_rule])
flow.show()
QTest.qWait(20)
flow.table.setCurrentCell(0, 1)
flow.table.setFocus(Qt.FocusReason.OtherFocusReason)
cell_before = [flow.table.currentRow(), flow.table.currentColumn()]
QTest.keyClick(flow.table, Qt.Key.Key_Tab)
app.processEvents()
cell_after = [flow.table.currentRow(), flow.table.currentColumn()]
surface_focus = flow.scaled_surface.focusWidget()
tab_left = surface_focus is not flow.table
flow.table.setCurrentCell(0, 1)
flow.table.setFocus(Qt.FocusReason.OtherFocusReason)
reverse_before = [flow.table.currentRow(), flow.table.currentColumn()]
QTest.keyClick(
    flow.table, Qt.Key.Key_Backtab)
app.processEvents()
reverse_after = [flow.table.currentRow(), flow.table.currentColumn()]
reverse_focus = flow.scaled_surface.focusWidget()
reverse_left = reverse_focus is not flow.table
flow.table.setFocus(Qt.FocusReason.OtherFocusReason)
QTest.keyClick(
    flow.table, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(20)
menus = [widget for widget in app.topLevelWidgets()
         if isinstance(widget, QMenu) and widget.isVisible()]
column_menu_actions = [action.text() for action in menus[-1].actions()]
menus[-1].close()

result = {
    'captured_duration': captured_duration_state,
    'created_rule': created_rule,
    'off_count': off_count,
    'non_create_hidden': non_create_hidden,
    'non_create_action': non_create_candidate['action'],
    'cancel_kept': cancel_kept,
    'native_cancelled': native_cancelled,
    'confirmation': confirmation,
    'removed': removed,
    'removed_count': removed_count,
    'remove_focus': (
        remove_focus.accessibleName() or remove_focus.objectName() or
        remove_focus.metaObject().className()) if remove_focus else '',
    'escape_closed': escape_closed,
    'tab_left': tab_left,
    'cell_unchanged': cell_before == cell_after,
    'reverse_left': reverse_left,
    'reverse_cell_unchanged': reverse_before == reverse_after,
    'reverse_focus': (
        reverse_focus.accessibleName() or reverse_focus.objectName() or
        reverse_focus.metaObject().className()) if reverse_focus else '',
    'column_menu_actions': column_menu_actions,
    'table_description': flow.table.accessibleDescription(),
    'action_description': flow.action.accessibleDescription(),
    'all_matches_label': flow.all_matches.accessibleName(),
}
for item in (dialog, escape, flow):
    item.close()
app.processEvents()
print(json.dumps(result))
app.quit()
"""


def test_keyword_rule_dialog_progressive_controls_keyboard_and_remove(tmp_path):
    result = _run_script(UI_SCRIPT, tmp_path / "ui-profile")

    assert result["captured_duration"] == {
        "hidden": True, "disabled": True, "label_hidden": True}
    assert result["created_rule"]["create_seconds"] == 400
    assert result["off_count"] == [
        "0/1", "Keyword timer rules, 0 enabled, 1 saved"]
    assert result["non_create_hidden"] is True
    assert result["non_create_action"] == "stop"
    assert result["cancel_kept"] is True
    assert result["native_cancelled"] is True
    assert result["confirmation"] == {
        "labels": ["Cancel", "Remove"],
        "default": "Cancel",
        "escape": "Cancel",
    }
    assert result["removed"] is True
    assert result["escape_closed"] is True
    assert result["tab_left"] is True
    assert result["cell_unchanged"] is True
    assert result["reverse_left"] is True
    assert result["reverse_cell_unchanged"] is True
    assert "Widen Phrase" in result["column_menu_actions"]
    assert "Narrow Phrase" in result["column_menu_actions"]
    assert "Tab leaves" in result["table_description"]
    assert "READY" in result["action_description"]
    assert result["all_matches_label"] == "Apply to all matching timers"
