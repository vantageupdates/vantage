"""Regression cases sanitized from Holyflux's October 27 P99 log."""

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers.spells import SpellTrigger, create_spell_book


@pytest.fixture
def cast_context(monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = config.data.setdefault('spells', {})
    monkeypatch.setitem(settings, 'use_casting_window', True)
    book, _, _ = create_spell_book()
    yield app, settings, book


@pytest.mark.parametrize('buffer_ms', [0, 250, 1000])
@pytest.mark.parametrize('spell_name, elapsed, landing, expected_target', [
    ('Yaulp II', 0,
     'You feel a surge of strength as you let forth a mighty yaulp.',
     '__you__'),
    ('Bravery', 2, 'Friendly looks brave.', 'Friendly'),
    ('Symbol of Ryltan', 4,
     'Friendly is cloaked in a shimmer of glowing symbols.', 'Friendly'),
])
def test_owned_casts_survive_whole_second_log_precision(
        cast_context, monkeypatch, buffer_ms, spell_name, elapsed,
        landing, expected_target):
    _, settings, book = cast_context
    monkeypatch.setitem(settings, 'casting_window_buffer', buffer_ms)
    start = datetime.datetime(2026, 10, 27, 3, 0, 0)
    landed = start + datetime.timedelta(seconds=elapsed)
    trigger = SpellTrigger(spell=book[spell_name], timestamp=start)
    delivered = []
    trigger.target_detected.connect(
        lambda source, index: delivered.append(source.targets[index]))
    try:
        assert trigger.parse(landed, landing) is True
        assert trigger.targets == [(landed, expected_target)]
        assert delivered == [(landed, expected_target)]
    finally:
        trigger.stop()


@pytest.mark.parametrize('elapsed', [-1, 0, 1, 9])
def test_precision_allowance_keeps_brave_landing_window_bounded(
        cast_context, monkeypatch, elapsed):
    _, settings, book = cast_context
    monkeypatch.setitem(settings, 'casting_window_buffer', 250)
    start = datetime.datetime(2026, 10, 27, 3, 0, 0)
    trigger = SpellTrigger(spell=book['Bravery'], timestamp=start)
    try:
        assert trigger.parse(
            start + datetime.timedelta(seconds=elapsed),
            'Friendly looks brave.') is False
        assert trigger.targets == []
    finally:
        trigger.stop()


def test_precision_allowance_does_not_accept_unrelated_effect(
        cast_context, monkeypatch):
    _, settings, book = cast_context
    monkeypatch.setitem(settings, 'casting_window_buffer', 250)
    start = datetime.datetime(2026, 10, 27, 3, 0, 0)
    trigger = SpellTrigger(spell=book['Bravery'], timestamp=start)
    try:
        assert trigger.parse(
            start + datetime.timedelta(seconds=2),
            'Someone is covered by an aura of black petals.') is False
        assert trigger.targets == []
    finally:
        trigger.stop()


@pytest.mark.parametrize('buffer_ms, last_landing_ms', [(0, 5750), (250, 6000)])
def test_early_precision_allowance_does_not_extend_cast_cleanup_deadline(
        cast_context, monkeypatch, buffer_ms, last_landing_ms):
    _, settings, book = cast_context
    monkeypatch.setitem(settings, 'casting_window_buffer', buffer_ms)
    start = datetime.datetime(2026, 10, 27, 3, 0, 0)
    trigger = SpellTrigger(spell=book['Bravery'], timestamp=start)
    try:
        # Bravery's 2750 ms cast plus the original three-second late grace.
        # The early timestamp allowance must not admit another cast's later
        # landing after this pending cast would already have been cleaned up.
        assert trigger._times_up_timer.interval() == last_landing_ms
        assert trigger.parse(
            start + datetime.timedelta(milliseconds=last_landing_ms + 1),
            'Friendly looks brave.') is False
        assert trigger.targets == []
        assert trigger.parse(
            start + datetime.timedelta(milliseconds=last_landing_ms),
            'Friendly looks brave.') is True
        assert trigger.targets == [(
            start + datetime.timedelta(milliseconds=last_landing_ms),
            'Friendly')]
    finally:
        trigger.stop()


LIVE_READER_SCRIPT = r"""
import datetime
import json
from pathlib import Path
import sys

from PySide6.QtTest import QTest

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.logreader import LogReader

app = VantageApp([])
spells = app._parsers_dict['spells']
spells.show()
config.data['spells']['use_custom_triggers'] = False
config.data['spells']['fade_sound_enabled'] = False
config.data['spells']['use_casting_window'] = True
config.data['spells']['level'] = 24
app.update_character_level('Holyflux', 'P1999Green', 24)
app.notify_event = lambda *args, **kwargs: False

directory = Path(sys.argv[1])
directory.mkdir()
log = directory / 'eqlog_Holyflux_P1999Green.txt'
log.write_text('')
reader = LogReader(str(directory))

def append(timestamp, message):
    with log.open('a', encoding='utf-8') as stream:
        stream.write(f'[{timestamp:%a %b %d %H:%M:%S %Y}] {message}\n')
    # Let the actual QFileSystemWatcher/recovery poll deliver into app._parse.
    QTest.qWait(350)

result = []
try:
    for buffer_ms in (0, 250):
        config.data['spells']['casting_window_buffer'] = buffer_ms
        recipient = f'Friendly{buffer_ms}'
        symbol_start = datetime.datetime.now().replace(microsecond=0)
        append(symbol_start, 'You begin casting Symbol of Ryltan.')
        assert spells._spell_trigger.spell.name == 'symbol of ryltan'
        QTest.qWait(3650)
        append(symbol_start + datetime.timedelta(seconds=4),
               f'{recipient} is cloaked in a shimmer of glowing symbols.')
        target = spells._spell_container.get_spell_target_by_name(recipient)
        assert target is not None
        assert target.spell_widget('symbol of ryltan') is not None

        bravery_start = datetime.datetime.now().replace(microsecond=0)
        append(bravery_start, 'You begin casting Bravery.')
        assert spells._spell_trigger.spell.name == 'bravery'
        QTest.qWait(2400)
        append(bravery_start + datetime.timedelta(seconds=2),
               f'{recipient} looks brave.')
        # This also processes the former cast's cleanup and each row's live
        # refresh timer, rather than testing only an uninterrupted replay burst.
        QTest.qWait(3700)
        rows = target.spell_widgets()
        result.append({
            'buffer': buffer_ms,
            'target_visible': target.isVisible(),
            'names': sorted(row.spell.name for row in rows),
            'rows_live': all(row.isVisible() and not row._removed and
                             not row._faded for row in rows),
            'caster': sorted(set(row.runtime_character for row in rows)),
            'remaining': {
                row.spell.name: int((row.end_time -
                                    datetime.datetime.now()).total_seconds())
                for row in rows},
        })
    self_target = spells._spell_container.get_spell_target_by_name('__you__')
    assert self_target is None or not self_target.spell_widgets()
    print(json.dumps(result))
finally:
    reader.stop()
    if spells._spell_trigger:
        spells._remove_spell_trigger()
    app.quit()
"""


def test_live_reader_keeps_symbol_and_bravery_on_other_target(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(root / 'src')
    completed = subprocess.run(
        [sys.executable, '-B', '-c', LIVE_READER_SCRIPT,
         str(tmp_path / 'Logs')],
        cwd=root, env=env, check=True, capture_output=True,
        text=True, timeout=90)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert [entry['buffer'] for entry in result] == [0, 250]
    for entry in result:
        assert entry['target_visible'] is True
        assert entry['rows_live'] is True
        assert entry['names'] == ['bravery', 'symbol of ryltan']
        assert entry['caster'] == ['Holyflux']
        assert 2600 < entry['remaining']['bravery'] <= 2700
        assert 2050 < entry['remaining']['symbol of ryltan'] <= 2160
