import datetime
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from vantage.helpers import config
from vantage.parsers.spells import Spell, SpellContainer, Spells


def _app():
    if 'level' not in config.data.get('spells', {}):
        config.verify_settings()
    return QApplication.instance() or QApplication([])


def _pacify():
    return Spell(
        name="Pacify",
        effect_text_other=" looks less aggressive.",
        duration=70,
        duration_seconds=420,
        duration_formula=11,
        spell_icon=44,
        type=1,
    )


def _fetter():
    return Spell(
        name="Fetter",
        effect_text_other="'s feet adhere to the ground.",
        effect_text_worn_off="Your feet come free.",
        duration=30,
        duration_seconds=180,
        duration_formula=11,
        spell_icon=58,
        type=0,
    )


def test_fresh_same_name_pacify_landings_create_stable_lettered_instances():
    app = _app()
    container = SpellContainer()
    now = datetime.datetime.now()

    container.add_spell(_pacify(), now, "a frost giant")
    container.add_spell(
        _pacify(), now + datetime.timedelta(seconds=5), "a frost giant")

    targets = container.get_spell_targets_by_name("A FROST GIANT")
    assert app is not None
    assert [target.target_label.text() for target in targets] == [
        "A Frost Giant · A", "A Frost Giant · B"]
    assert all("mob IDs" in target.target_label.toolTip() for target in targets)


def test_death_removes_one_duplicate_then_renumbers_the_survivor():
    app = _app()
    container = SpellContainer()
    now = datetime.datetime.now()
    container.add_spell(_pacify(), now, "a frost giant")
    container.add_spell(
        _pacify(), now + datetime.timedelta(seconds=5), "a frost giant")

    assert container.remove_dead_target("a frost giant") is True
    app.processEvents()

    targets = container.get_spell_targets_by_name("a frost giant")
    assert len(targets) == 1
    # The surviving marker stays stable so a player's location alias does not
    # silently change identity when another mob dies.
    assert targets[0].target_label.text() == "A Frost Giant · B"


def test_target_header_can_be_focused_and_removed_with_delete():
    app = _app()
    container = SpellContainer()
    container.add_spell(_pacify(), datetime.datetime.now(), "a frost giant")
    target = container.get_spell_target_by_name("a frost giant")

    assert target.target_label.focusPolicy() == Qt.FocusPolicy.StrongFocus
    handled = target.eventFilter(target.target_label, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Delete,
        Qt.KeyboardModifier.NoModifier))
    app.processEvents()

    assert handled is True
    assert container.get_spell_target_by_name("a frost giant") is None


def test_late_same_name_landing_recasts_old_instance_instead_of_splitting():
    _app()
    container = SpellContainer()
    now = datetime.datetime.now()
    container.add_spell(_pacify(), now, "a frost giant")
    container.add_spell(
        _pacify(), now + datetime.timedelta(seconds=200), "a frost giant")

    assert len(container.get_spell_targets_by_name("a frost giant")) == 1


def test_named_target_never_gets_numbered_or_duplicated():
    _app()
    container = SpellContainer()
    now = datetime.datetime.now()

    container.add_spell(_pacify(), now, "Crystal Fang", named=True)
    container.add_spell(
        _pacify(), now + datetime.timedelta(seconds=5),
        "Crystal Fang", named=True)

    targets = container.get_spell_targets_by_name("Crystal Fang")
    assert len(targets) == 1
    assert targets[0].target_label.text() == "Crystal Fang"
    assert "Named NPC" in targets[0].target_label.toolTip()


def test_effect_can_move_to_new_same_named_mob_without_restarting():
    _app()
    container = SpellContainer()
    now = datetime.datetime.now()
    container.add_spell(_pacify(), now, "a crystalline devourer")
    container.add_spell(_fetter(), now, "a crystalline devourer")

    first = container.get_spell_target_by_name("a crystalline devourer")
    fetter = first.spell_widget("Fetter")
    original_end = fetter.end_time
    destination = container.move_spell_widget(fetter)

    targets = container.get_spell_targets_by_name("a crystalline devourer")
    assert [target.instance_marker for target in targets] == ["A", "B"]
    assert [widget.spell.name for widget in targets[0].spell_widgets()] == [
        "Pacify"]
    assert [widget.spell.name for widget in targets[1].spell_widgets()] == [
        "Fetter"]
    assert destination is targets[1]
    assert fetter.end_time == original_end


def test_mob_alias_is_displayed_and_kept_with_its_marker():
    _app()
    container = SpellContainer()
    container.add_spell(
        _pacify(), datetime.datetime.now(), "a crystalline devourer")
    target = container.get_spell_target_by_name("a crystalline devourer")

    target.alias = "Ramp"
    target.set_instance_number(1)

    assert target.target_label.text() == "A Crystalline Devourer · Ramp"
    assert "Pacify" in target.target_label.toolTip()


def test_current_zone_catalog_recognizes_named_but_not_trash():
    spells = SimpleNamespace(_current_zone="Velketor's Labyrinth")

    assert Spells._is_named_target(spells, "Crystal Fang") is True
    assert Spells._is_named_target(spells, "a crystalline watcher") is False


def test_worn_off_marks_only_oldest_matching_mob_bar_as_faded():
    _app()
    previous_fade_sound = config.data['spells']['fade_sound_enabled']
    config.data['spells']['fade_sound_enabled'] = False
    try:
        container = SpellContainer()
        now = datetime.datetime.now()
        container.add_spell(_fetter(), now, "a frost giant")
        container.add_spell(
            _fetter(), now + datetime.timedelta(seconds=5), "a snow dervish")

        faded = container.mark_worn_off(
            "Your feet come free.", now + datetime.timedelta(seconds=10))
        first = container.get_spell_target_by_name(
            "a frost giant").spell_widgets()[0]
        second = container.get_spell_target_by_name(
            "a snow dervish").spell_widgets()[0]

        assert faded is first
        assert first._faded is True
        assert first.progress.property('Faded') is True
        assert first.progress._time_text == 'FADED'
        assert "A Frost Giant" in first.progress.toolTip()
        assert second._faded is False
    finally:
        config.data['spells']['fade_sound_enabled'] = previous_fade_sound
