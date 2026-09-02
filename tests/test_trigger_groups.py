from vantage.helpers.trigger_groups import (
    effective_trigger_style, group_enabled, group_state, group_style,
    normalize_group_path, normalize_trigger_groups, set_group_enabled,
    set_group_style)


def test_group_paths_migrate_from_legacy_categories_and_include_ancestors():
    spells = {
        'trigger_categories': {'Raid/Velious/Kael': False},
        'custom_timers': []}

    groups = normalize_trigger_groups(spells)

    assert normalize_group_path(r' Raid\Velious / Kael ') == (
        'Raid/Velious/Kael')
    assert list(groups) == ['Raid', 'Raid/Velious', 'Raid/Velious/Kael']
    assert groups['Raid/Velious/Kael']['enabled'] is False


def test_parent_disable_blocks_children_and_character_override_is_exact():
    spells = {'custom_timers': [], 'trigger_categories': {}}
    set_group_enabled(spells, 'Raid', False)
    set_group_enabled(spells, 'Raid/Velious', True)
    assert group_enabled(spells, 'Raid/Velious', 'Gandalf') is False

    set_group_enabled(spells, 'Raid', True, 'Gandalf')
    assert group_enabled(spells, 'Raid/Velious', 'Gandalf') is True
    assert group_enabled(spells, 'Raid/Velious', 'Frodo') is False
    assert group_state(spells, 'Raid', 'gAnDaLf') is True


def test_character_override_can_disable_one_profile_only():
    spells = {'custom_timers': [], 'trigger_categories': {}}
    set_group_enabled(spells, 'Utility/Invisibility', True)
    set_group_enabled(spells, 'Utility/Invisibility', False, 'Ranger')

    assert group_enabled(spells, 'Utility/Invisibility', 'Druid') is True
    assert group_enabled(spells, 'Utility/Invisibility', 'ranger') is False
    assert spells['trigger_categories']['Utility/Invisibility'] is True


def test_trigger_style_inherits_ancestor_then_profile_then_trigger():
    spells = {'custom_timers': [], 'trigger_groups': {}}
    set_group_style(spells, 'Raid', {'font_color': '#AA8844'})
    set_group_style(spells, 'Raid/Kael', {'font_color': '#8877AA'})
    set_group_style(
        spells, 'Raid/Kael', {'font_color': '#66AA77'}, 'Alice')

    assert group_style(
        spells, 'Raid/Kael', inherited=True)['font_color'] == '#8877AA'
    assert effective_trigger_style(
        spells, 'Raid/Kael', profile='Alice')['font_color'] == '#66AA77'
    assert effective_trigger_style(
        spells, 'Raid/Kael', {'font_color': '#CC6655'}, 'Alice'
    )['font_color'] == '#CC6655'


def test_empty_style_removes_override_and_invalid_colors_are_ignored():
    spells = {'custom_timers': [], 'trigger_groups': {}}
    set_group_style(spells, 'Raid', {'font_color': '#AABBCC'})
    set_group_style(spells, 'Raid', {'font_color': 'not-css'})
    assert group_style(spells, 'Raid') == {}
