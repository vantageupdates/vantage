import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from vantage.helpers import config
from vantage.helpers.timer_sync import timer_identity
from vantage.parsers.spells import Spells, Spell, SpellContainer, SpellWidget


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


REALISTIC_BLANK_KEY_BUFFS = (
    ("Grim Aura", 3600),
    ("Focus of Spirit", 4200),
    ("Enlightenment", 7200),
    ("Riotous Health", 3900),
)


def test_live_blank_runtime_key_self_buffs_coexist_for_spiritflux():
    _app()
    container = SpellContainer()
    started = datetime.datetime.now()

    for name, duration in REALISTIC_BLANK_KEY_BUFFS:
        container.add_spell(
            _spell(name, runtime_key="", type=1,
                   duration_seconds=duration),
            started, "__you__", "Spiritflux", "P1999Green")

    target = container.get_spell_target_by_name("__you__")
    assert sorted(widget.spell.name for widget in target.spell_widgets()) == [
        "Enlightenment", "Focus of Spirit", "Grim Aura", "Riotous Health"]
    snapshot = container.snapshot_runtime_state(
        now_epoch=1_000, now_datetime=started)
    assert {row["spell"]["runtime_key"] for row in snapshot} == {
        "enlightenment", "focus of spirit", "grim aura", "riotous health"}


def test_restore_preserves_four_blank_key_rows_deadlines_and_profile():
    _app()
    now_epoch = 10_000
    now_datetime = datetime.datetime.now()
    saved = []
    expected_deadlines = {}
    for index, (name, duration) in enumerate(REALISTIC_BLANK_KEY_BUFFS, 1):
        deadline = now_epoch + duration
        expected_deadlines[name] = deadline
        saved.append({
            "deadline": deadline,
            "target": "__you__",
            "target_created_order": 1,
            "character": "Spiritflux",
            "server": "P1999Green",
            "spell": {
                "name": name,
                "runtime_key": "",
                "duration_seconds": duration,
                "duration": duration // 6,
                "duration_formula": 0,
                "type": 1,
                "spell_icon": index,
            },
        })

    restored = SpellContainer()
    assert restored.restore_runtime_state(
        saved, {}, now_epoch=now_epoch,
        now_datetime=now_datetime) == 4
    rows = restored.snapshot_runtime_state(
        now_epoch=now_epoch, now_datetime=now_datetime)

    assert {row["spell"]["name"] for row in rows} == set(expected_deadlines)
    assert {row["spell"]["name"]: row["deadline"] for row in rows} == \
        expected_deadlines
    assert {(row["character"], row["server"]) for row in rows} == {
        ("Spiritflux", "P1999Green")}


def test_blank_key_recast_replaces_only_the_same_named_buff():
    _app()
    container = SpellContainer()
    started = datetime.datetime.now()
    for name, duration in REALISTIC_BLANK_KEY_BUFFS:
        container.add_spell(
            _spell(name, runtime_key="", type=1,
                   duration_seconds=duration),
            started, "__you__", "Spiritflux", "P1999Green")
    target = container.get_spell_target_by_name("__you__")
    before = {widget.spell.name: (widget, widget.end_time)
              for widget in target.spell_widgets()}

    recast_at = started + datetime.timedelta(seconds=30)
    container.add_spell(
        _spell("Riotous Health", runtime_key="", type=1,
               duration_seconds=3900),
        recast_at, "__you__", "Spiritflux", "P1999Green")
    after = {widget.spell.name: (widget, widget.end_time)
             for widget in target.spell_widgets()}

    assert set(after) == set(before)
    assert len(after) == 4
    for name in after:
        assert after[name][0] is before[name][0]
        if name == "Riotous Health":
            assert after[name][1] == recast_at + datetime.timedelta(seconds=3900)
        else:
            assert after[name][1] == before[name][1]


def test_authoritative_widget_removal_captures_identity_before_detach():
    _app()
    container = SpellContainer()
    container.add_spell(
        _spell(runtime_level=60), datetime.datetime.now(), "__you__",
        "Spiritflux", "Green")
    saved = container.snapshot_runtime_state()
    removed = []
    container.timer_rows_removed.connect(removed.extend)

    widget = container.get_spell_target_by_name("__you__").spell_widgets()[0]
    widget._remove()

    assert len(removed) == 1
    assert timer_identity(removed[0]) == timer_identity(saved[0])


def test_non_authoritative_render_cleanup_does_not_emit_removal():
    _app()
    container = SpellContainer()
    container.add_spell(
        _spell(runtime_level=60), datetime.datetime.now(), "__you__",
        "Spiritflux", "Green")
    removed = []
    container.timer_rows_removed.connect(removed.extend)

    widget = container.get_spell_target_by_name("__you__").spell_widgets()[0]
    widget._remove(authoritative=False)

    assert removed == []


def test_cancelled_update_handoff_resumes_live_spell_persistence(monkeypatch):
    _app()
    original_spells = config.data['spells']
    monkeypatch.setattr(config, '_filename', '')

    class _Host:
        checkpoint_runtime_state = Spells.checkpoint_runtime_state
        begin_update_handoff = Spells.begin_update_handoff
        cancel_update_handoff = Spells.cancel_update_handoff

    host = _Host()
    host._runtime_state_save_timer = QTimer()
    host._runtime_state_save_timer.setSingleShot(True)
    host._spell_container = SpellContainer()
    host._update_handoff_rows = None
    now = datetime.datetime.now()
    host._spell_container.add_spell(
        _spell('Fetter'), now, '__you__', 'Spiritflux', 'Green')
    config.data['spells'] = {
        **original_spells,
        'active_timer_state': [],
        'active_timer_sync': {},
    }
    try:
        frozen = host.begin_update_handoff()
        assert [row['spell']['name'] for row in frozen] == ['Fetter']

        # The app remains open after Popen fails. A later live cast must be
        # observed rather than remaining pinned to the failed-update snapshot.
        host.cancel_update_handoff()
        host._spell_container.add_spell(
            _spell('Regrowth'), now, '__you__', 'Spiritflux', 'Green')
        host.checkpoint_runtime_state()
        assert sorted(row['spell']['name'] for row in
                      config.data['spells']['active_timer_state']) == [
                          'Fetter', 'Regrowth']
    finally:
        config.data['spells'] = original_spells


def test_spell_state_restores_current_remaining_time_after_downtime():
    _app()
    # Keep the live Qt timer in the future while testing the independent
    # snapshot clock. A fixed wall-clock date eventually makes the widget
    # expire before the snapshot assertion is reached.
    started = datetime.datetime.now()
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


def test_synced_refresh_restores_exact_or_nearest_focus_without_stealing():
    app = _app()
    original_spells = config.data['spells']
    now = datetime.datetime.now()
    book = {
        name: _spell(name, type=1, runtime_key=name.casefold())
        for name in ("Focus of Spirit", "Regrowth", "Grim Aura")}

    class _Host:
        _runtime_sync_signature = staticmethod(Spells._runtime_sync_signature)
        _synced_focus_candidates = Spells._synced_focus_candidates
        _capture_synced_focus = Spells._capture_synced_focus
        _restore_synced_focus = Spells._restore_synced_focus

    host = _Host()
    host._runtime_state_save_timer = QTimer()
    host._runtime_state_save_timer.setSingleShot(True)
    host._character_widget = QLineEdit()
    host.spell_book = book
    host._spell_container = SpellContainer()
    host._spell_container.show()
    for name in ("Focus of Spirit", "Regrowth"):
        host._spell_container.add_spell(
            book[name], now, "__you__", "Spiritflux", "Green")
    regrowth = next(
        widget for widget in
        host._spell_container.get_spell_target_by_name(
            "__you__").spell_widgets()
        if widget.spell.name == "Regrowth")
    regrowth.setFocus()
    app.processEvents()

    desired = SpellContainer()
    for name in ("Regrowth", "Grim Aura"):
        desired.add_spell(
            book[name], now, "__you__", "Spiritflux", "Green")
    config.data['spells'] = {
        **original_spells,
        'active_timer_state': desired.snapshot_runtime_state(),
        'active_timer_sync': {},
    }
    Spells.refresh_synced_content(host)
    app.processEvents()

    target = host._spell_container.get_spell_target_by_name("__you__")
    refreshed_regrowth = next(
        widget for widget in target.spell_widgets()
        if widget.spell.name == "Regrowth")
    assert refreshed_regrowth.hasFocus()

    desired = SpellContainer()
    desired.add_spell(
        book["Grim Aura"], now, "__you__", "Spiritflux", "Green")
    config.data['spells']['active_timer_state'] = \
        desired.snapshot_runtime_state()
    Spells.refresh_synced_content(host)
    app.processEvents()
    remaining = host._spell_container.get_spell_target_by_name(
        "__you__").spell_widgets()[0]
    assert remaining.spell.name == "Grim Aura"
    assert remaining.hasFocus()

    outside = QLineEdit()
    outside.show()
    outside.setFocus()
    app.processEvents()
    desired.add_spell(
        book["Focus of Spirit"], now, "__you__", "Spiritflux", "Green")
    config.data['spells']['active_timer_state'] = \
        desired.snapshot_runtime_state()
    Spells.refresh_synced_content(host)
    app.processEvents()
    assert outside.hasFocus()

    config.data['spells'] = original_spells
    outside.close()
    host._spell_container.close()


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


def test_character_filter_hides_legacy_rows_from_specific_profiles():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    buff = _spell(
        "Clarity II", effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    container.add_spell(buff, now, "__you__", "", "")
    target = container.get_spell_target_by_name("__you__")
    legacy = target.spell_widgets()[0]

    container.set_profile_filter("", "")
    assert legacy.isHidden() is False
    container.set_profile_filter("Mindflux", "Green")
    assert legacy.isHidden() is True
    container.set_profile_filter("Harmflux", "Green")
    assert legacy.isHidden() is True


def test_worn_off_isolated_to_exact_character_profile():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    buff = _spell(
        "Clarity II", effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    # Give the other profile an earlier deadline: profile filtering, rather
    # than global expiry order, must still choose Mindflux.
    container.add_spell(buff, now, "__you__", "Harmflux", "Green")
    container.add_spell(
        buff, now + datetime.timedelta(seconds=30), "__you__",
        "Mindflux", "Green")
    target = container.get_spell_target_by_name("__you__")
    rows = {widget.runtime_character: widget
            for widget in target.spell_widgets()}

    faded = container.mark_worn_off(
        "Your mind fogs.", now + datetime.timedelta(seconds=60),
        play_sound=False, character="Mindflux", server="Green")

    assert faded is rows["Mindflux"]
    assert rows["Mindflux"]._faded is True
    assert rows["Harmflux"]._faded is False


def test_worn_off_profile_falls_back_only_to_unprofiled_legacy_row():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    buff = _spell(
        "Clarity II", effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    container.add_spell(buff, now, "__you__", "Harmflux", "Green")
    target = container.get_spell_target_by_name("__you__")
    other_profile = target.spell_widgets()[0]

    assert container.mark_worn_off(
        "Your mind fogs.", now + datetime.timedelta(seconds=10),
        play_sound=False, character="Mindflux", server="Green") is None
    assert other_profile._faded is False

    legacy = SpellWidget(
        buff, now + datetime.timedelta(seconds=1), "", "")
    target._layout.addWidget(legacy)
    faded = container.mark_worn_off(
        "Your mind fogs.", now + datetime.timedelta(seconds=20),
        play_sound=False, character="Mindflux", server="Green")

    assert faded is legacy
    assert legacy._faded is True
    assert other_profile._faded is False


def test_profile_matcher_rejects_legacy_row_for_character_snapshot():
    _app()
    widget = SpellWidget(_spell(type=1), datetime.datetime.now(), "", "")

    from vantage.parsers.spells import Spells

    assert Spells._spell_widget_matches_profile(widget, "", "") is True
    assert Spells._spell_widget_matches_profile(
        widget, "Mindflux", "Green") is False


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


def test_self_buff_recast_revives_faded_row_and_rejects_stale_worn_off():
    _app()
    now = datetime.datetime.now()
    container = SpellContainer()
    clarity = _spell(
        "Clarity II", runtime_key="spell:clarity-ii",
        effect_text_other=" feels a clarity of mind.",
        effect_text_worn_off="Your mind fogs.", type=1)
    container.add_spell(
        clarity, now, "__you__", "Mindflux", "Green")
    target = container.get_spell_target_by_name("__you__")
    original = target.spell_widgets()[0]
    original.mark_faded(
        now + datetime.timedelta(seconds=10), play_sound=False)

    assert original._faded is True
    assert original._fade_remove_timer.isActive() is True
    assert original.progress._time_text == "FADED"

    refreshed_at = now + datetime.timedelta(seconds=12)
    container.add_spell(
        clarity, refreshed_at, "__you__", "Mindflux", "Green")
    widgets = target.spell_widgets()

    assert widgets == [original]
    assert original._faded is False
    assert original._active is True
    assert original._fade_remove_timer.isActive() is False
    assert original.progress._time_text != "FADED"
    assert original.progress.property("Faded") is False
    assert original.progress.property("Warning") is False
    assert original.progress.property("Critical") is False
    assert original.progress.property("Pulse") is False
    assert original.end_time == refreshed_at + datetime.timedelta(seconds=420)

    # EQ may emit the replaced copy's worn-off line just after the landing.
    # It must not fade the refreshed generation or let the old grace callback
    # remove it.
    assert container.mark_worn_off(
        "Your mind fogs.", refreshed_at + datetime.timedelta(seconds=1),
        play_sound=False) is None
    original._remove_if_still_faded()
    assert original._removed is False

    # Outside the short replacement window, the same line is authoritative.
    faded = container.mark_worn_off(
        "Your mind fogs.", refreshed_at + datetime.timedelta(seconds=4),
        play_sound=False)
    assert faded is original
    assert original._faded is True


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
