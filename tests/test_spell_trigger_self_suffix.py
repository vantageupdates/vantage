import datetime

from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers.spells import SpellTrigger, create_spell_book


def test_exact_self_landing_wins_before_other_target_suffix():
    QApplication.instance() or QApplication([])
    spells = config.data.setdefault('spells', {})
    previous = spells.get('use_casting_window')
    spells['use_casting_window'] = False
    trigger = None
    try:
        book, _landing_index, _worn_index = create_spell_book()
        camouflage = book['Camouflage']
        assert camouflage.effect_text_you == 'Your body fades away.'
        assert camouflage.effect_text_you.endswith(
            camouflage.effect_text_other)

        now = datetime.datetime.now().replace(microsecond=0)
        trigger = SpellTrigger(spell=camouflage, timestamp=now)

        assert trigger.parse(now, camouflage.effect_text_you) is True
        assert trigger.targets == [(now, '__you__')]
    finally:
        if trigger is not None:
            trigger.stop()
        if previous is None:
            spells.pop('use_casting_window', None)
        else:
            spells['use_casting_window'] = previous
