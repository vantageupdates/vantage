import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers.spells import Spell, SpellContainer, SpellWidget


def _app():
    if 'level' not in config.data.get('spells', {}):
        config.verify_settings()
    return QApplication.instance() or QApplication([])


def _spell(name="Fetter", **values):
    fields = {
        "name": name,
        "effect_text_other": "'s feet adhere to the ground.",
        "effect_text_worn_off": "Your feet come free.",
        "duration": 70,
        "duration_seconds": 420,
        "duration_formula": 11,
        "spell_icon": 58,
        "skill": 5,
        "resist_type": 1,
        "type": 0,
    }
    fields.update(values)
    return Spell(**fields)


def test_spell_state_restores_current_remaining_time_after_downtime():
    _app()
    started = datetime.datetime(2026, 9, 2, 12, 0, 0)
    container = SpellContainer()
    container.add_spell(
        _spell(runtime_level=60), started, "a crystalline devourer",
        "Mindflux", "Green")
    target = container.get_spell_target_by_name("a crystalline devourer")
    target.alias = "Ramp"
    target.set_instance_number(1)
    target.spell_widgets()[0]._warning_played = True

    saved = container.snapshot_runtime_state(
        now_epoch=1_000, now_datetime=started + datetime.timedelta(seconds=30))
    restored = SpellContainer()
    count = restored.restore_runtime_state(
        saved, {"Fetter": _spell()}, now_epoch=1_060,
        now_datetime=started + datetime.timedelta(seconds=60))

    restored_target = restored.get_spell_target_by_name(
        "a crystalline devourer")
    widget = restored_target.spell_widgets()[0]
    assert count == 1
    assert round((widget.end_time - (
        started + datetime.timedelta(seconds=60))).total_seconds()) == 330
    assert restored_target.instance_marker == "A"
    assert restored_target.alias == "Ramp"
    assert widget.runtime_character == "Mindflux"
    assert widget.runtime_server == "Green"
    assert widget._warning_played is True


def test_expired_spell_state_is_not_restored():
    _app()
    container = SpellContainer()
    saved = [{
        "deadline": 999,
        "target": "__you__",
        "spell": {"name": "Fetter", "duration_seconds": 420,
                  "duration_formula": 11, "duration": 70, "type": 0},
    }]

    assert container.restore_runtime_state(
        saved, {}, now_epoch=1_000,
        now_datetime=datetime.datetime(2026, 9, 2)) == 0
    assert container.spell_targets() == []


def test_character_filter_keeps_separate_same_spell_rows():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    buff = _spell(
        "Clarity II", effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    container.add_spell(buff, now, "__you__", "Mindflux", "Green")
    container.add_spell(buff, now, "__you__", "Harmflux", "Green")
    target = container.get_spell_target_by_name("__you__")

    assert len(target.spell_widgets()) == 2
    container.set_profile_filter("Mindflux", "Green")
    assert [
        widget.runtime_character for widget in target.spell_widgets()
        if not widget.isHidden()] == ["Mindflux"]
    container.set_profile_filter("Harmflux", "Green")
    assert [
        widget.runtime_character for widget in target.spell_widgets()
        if not widget.isHidden()] == ["Harmflux"]


def test_self_buff_recast_claims_and_collapses_legacy_duplicate_rows():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    legacy = _spell(
        "Clarity II", runtime_key="legacy-click:clarity-ii",
        effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    current = _spell(
        "Clarity II", runtime_key="spell:clarity-ii",
        effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    container.add_spell(legacy, now, "__you__", "", "")
    container.add_spell(
        current, now + datetime.timedelta(seconds=5), "__you__",
        "Mindflux", "Green")
    # A second old row can exist in a persisted state from a pre-profile build;
    # the next authoritative cast must collapse all compatible copies.
    target = container.get_spell_target_by_name("__you__")
    target._layout.addWidget(SpellWidget(
        legacy, now + datetime.timedelta(seconds=1), "", ""))
    container.add_spell(
        current, now + datetime.timedelta(seconds=10), "__you__",
        "Mindflux", "Green")

    widgets = target.spell_widgets()
    assert len(widgets) == 1
    assert widgets[0].spell.name == "Clarity II"
    assert widgets[0].runtime_character == "Mindflux"
    assert widgets[0].runtime_server == "Green"


def test_runtime_character_level_controls_duration():
    _app()
    previous_level = config.data['spells']['level']
    try:
        config.data['spells']['level'] = 60
        scalable = _spell(
            "Scaling Buff", duration_seconds=0, duration=100,
            duration_formula=1, type=1, runtime_level=10)
        widget = SpellWidget(scalable, datetime.datetime.now())
        assert widget._ticks == 5
        assert widget._seconds == 30
    finally:
        config.data['spells']['level'] = previous_level
