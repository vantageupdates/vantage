import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vantage.helpers.spawn_timer import (
    PHASE_COMBAT, PHASE_RESPAWN, SpawnTimerState)
from vantage.helpers.timer_share import (
    MAX_TIMER_SHARE_CODE_CHARS,
    TimerShareError,
    build_timer_share_codes,
    decode_timer_share_code,
    extract_timer_share_codes,
    shared_record_to_state,
)


ROOT = Path(__file__).resolve().parents[1]


def test_running_share_recalculates_from_generation_to_log_read_time():
    source = SpawnTimerState(
        "Crystal Fang", 120, kill_seconds=10,
        zone="Velketor's Labyrinth")
    source.mark_killed(1_000)

    exported = build_timer_share_codes([source], now=1_030)
    assert exported.generated_at == 1_030
    assert exported.timer_count == 1
    assert len(exported.codes) == 1
    assert len(exported.codes[0]) <= MAX_TIMER_SHARE_CODE_CHARS

    log_line = f"Camper tells you, '{exported.codes[0]}'"
    assert extract_timer_share_codes(log_line) == exported.codes
    packet = decode_timer_share_code(exported.codes[0], received_at=1_045)
    restored = shared_record_to_state(
        packet.timers[0], packet, 1_045, volume=42)

    assert packet.age_seconds == 15
    assert restored.phase == PHASE_RESPAWN
    assert restored.running is True
    assert restored.remaining(1_045) == 75
    assert restored.zone == "Velketor's Labyrinth"
    assert restored.volume == 42
    assert restored.source == "Shared timer"


def test_paused_share_does_not_decay_while_message_is_in_transit():
    source = SpawnTimerState("Paused mob", 120)
    source.mark_killed(1_000)
    source.pause(1_010)
    exported = build_timer_share_codes([source], now=1_030)
    packet = decode_timer_share_code(exported.codes[0], received_at=1_100)
    restored = shared_record_to_state(packet.timers[0], packet, 1_100)

    assert packet.age_seconds == 70
    assert restored.running is False
    assert restored.remaining(1_100) == 110


def test_smart_share_catches_up_across_spawn_and_kill_phases():
    source = SpawnTimerState(
        "Smart mob", 60, kill_seconds=10, warning_seconds=5)
    source.start(1_000)
    exported = build_timer_share_codes([source], now=1_010)
    packet = decode_timer_share_code(exported.codes[0], received_at=1_075)
    restored = shared_record_to_state(packet.timers[0], packet, 1_075)

    assert restored.phase == PHASE_RESPAWN
    assert restored.cycles == 1
    assert restored.deadline == 1_130
    assert restored.remaining(1_075) == 55


def test_large_share_splits_into_independent_chat_safe_codes():
    timers = []
    for index in range(12):
        timer = SpawnTimerState(
            f"Named mob {index} {index * 7919:08x}", 1_970 + index,
            zone=f"Distinct zone {index} {index * 104729:08x}")
        timer.mark_killed(2_000 + index)
        timers.append(timer)

    exported = build_timer_share_codes(timers, now=2_100)

    assert len(exported.codes) > 1
    assert all(len(code) <= MAX_TIMER_SHARE_CODE_CHARS
               for code in exported.codes)
    decoded = [
        record.name
        for code in exported.codes
        for record in decode_timer_share_code(code, received_at=2_120).timers]
    assert decoded == [timer.name for timer in timers]


def test_damaged_expired_and_future_codes_are_safe():
    timer = SpawnTimerState("Quillmane", 1_920, zone="South Karana")
    timer.start(10_000)
    code = build_timer_share_codes([timer], now=10_010).codes[0]

    with pytest.raises(TimerShareError, match="damaged"):
        decode_timer_share_code(code[:-3] + "xxx", received_at=10_020)
    with pytest.raises(TimerShareError, match="expired"):
        decode_timer_share_code(code, received_at=10_010 + 86_401)

    future = decode_timer_share_code(code, received_at=9_900)
    assert future.age_seconds == 0
    assert future.future_clock_skew_seconds == 110
    restored = shared_record_to_state(
        future.timers[0], future, received_at=9_900)
    assert restored.deadline == 9_900 + timer.remaining(10_010)


INTEGRATION_SCRIPT = r"""
import datetime
import json
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vantage.helpers.spawn_timer import SpawnTimerState
from vantage.helpers.timer_share import build_timer_share_codes
from vantage.helpers.application import VantageApp
import vantage.parsers.timers as timers_module

captured = []
timers_module.set_eq_clipboard = lambda text: captured.append(text) or True

app = VantageApp([])
panel = app._parsers_dict['timers']
panel._zone_changed("Velketor's Labyrinth")

local = SpawnTimerState(
    "Crystal Hunter", 120, zone="Velketor's Labyrinth")
local.mark_killed(time.time() - 10)
panel._states[local.timer_id] = local
panel._add_row(local)
panel._refresh_zone_filter("Velketor's Labyrinth")
panel.show()
app.processEvents()

focus_policy = panel.share_button.focusPolicy() == Qt.FocusPolicy.StrongFocus
panel._set_header_revealed(False)
app.processEvents()
QTest.keyClick(
    panel, Qt.Key.Key_S,
    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
app.processEvents()
shortcut_while_header_hidden = len(captured) == 1
panel._set_header_revealed(True)
panel.share_button.click()
app.processEvents()
button_activated = len(captured) == 2
own_code = captured[-1].splitlines()[0]
count_before_own_echo = len(panel._states)
panel.parse(datetime.datetime.now(), f"You say, '{own_code}'")
count_after_own_echo = len(panel._states)

received_at = int(time.time())
source = SpawnTimerState(
    "A Frost Giant Scout", 120, kill_seconds=10, zone="Kael Drakkel")
source.mark_killed(received_at - 50)
external = build_timer_share_codes([source], now=received_at - 20)
line = f"Campfriend tells you, '{external.codes[0]}'"
selected_before = panel.zone_filter.currentData()
panel._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
app.processEvents()
focus_before_import = QApplication.focusWidget()
panel.parse(datetime.datetime.fromtimestamp(received_at), line)
selected_after = panel.zone_filter.currentData()
focus_after_import = QApplication.focusWidget()
shared = next(timer for timer in panel._states.values()
              if timer.name == "A Frost Giant Scout")
imported_remaining = shared.remaining(received_at)
count_after_import = len(panel._states)
status_after_import = panel.status.text()
hidden_after_import = panel._rows[shared.timer_id].isHidden()
panel.parse(datetime.datetime.fromtimestamp(received_at + 1), line)
count_after_duplicate = len(panel._states)

shared.color = "#123456"
shared.sound_path = "builtin:quiet-chime"
shared.volume = 17
newer = SpawnTimerState(
    "A Frost Giant Scout", 120, kill_seconds=15, zone="Kael Drakkel",
    color="#ABCDEF")
newer.mark_killed(received_at - 10)
fresh = build_timer_share_codes([newer], now=received_at)
panel.parse(
    datetime.datetime.fromtimestamp(received_at + 5),
    f"Campfriend tells you, '{fresh.codes[0]}'")
merged = next(timer for timer in panel._states.values()
              if timer.name == "A Frost Giant Scout")
count_after_fresh = len(panel._states)

before_invalid = len(panel._states)
panel.parse(
    datetime.datetime.fromtimestamp(received_at + 6),
    "Campfriend tells you, 'VTS1:not-a-real-but-long-token'")
invalid_rejected = (
    len(panel._states) == before_invalid and
    "REJECTED" in panel.status.text())

print(json.dumps({
    "accessible_name": panel.share_button.accessibleName(),
    "tooltip": panel.share_button.toolTip(),
    "strong_focus": focus_policy,
    "shortcut_while_header_hidden": shortcut_while_header_hidden,
    "button_activated": button_activated,
    "clipboard_writes": len(captured),
    "own_echo_ignored": count_before_own_echo == count_after_own_echo,
    "imported_remaining": imported_remaining,
    "imported_source": shared.source,
    "selected_unchanged": selected_before == selected_after,
    "focus_unchanged_on_import": focus_before_import is focus_after_import,
    "hidden_after_import": hidden_after_import,
    "status": status_after_import,
    "duplicate_ignored": count_after_duplicate == count_after_import,
    "fresh_share_merged": count_after_fresh == count_after_import,
    "merged_remaining": merged.remaining(received_at + 5),
    "local_alerts_preserved": [
        merged.color, merged.sound_path, merged.volume],
    "invalid_rejected": invalid_rejected,
}))
app.quit()
"""


def test_timer_panel_share_button_and_automatic_log_import(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", INTEGRATION_SCRIPT],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        timeout=40)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["accessible_name"] == "Share visible timers"
    assert "zone view" in result["tooltip"]
    assert "Ctrl+Shift+S" in result["tooltip"]
    assert result["strong_focus"] is True
    assert result["shortcut_while_header_hidden"] is True
    assert result["button_activated"] is True
    assert result["clipboard_writes"] == 2
    assert result["own_echo_ignored"] is True
    assert result["imported_remaining"] == 70
    assert result["imported_source"] == "Shared timer"
    assert result["selected_unchanged"] is True
    assert result["focus_unchanged_on_import"] is True
    assert result["hidden_after_import"] is True
    assert "IMPORTED" in result["status"]
    assert "saved under Kael Drakkel" in result["status"]
    assert result["duplicate_ignored"] is True
    assert result["fresh_share_merged"] is True
    assert result["merged_remaining"] == 105
    assert result["local_alerts_preserved"] == [
        "#123456", "builtin:quiet-chime", 17]
    assert result["invalid_rejected"] is True
