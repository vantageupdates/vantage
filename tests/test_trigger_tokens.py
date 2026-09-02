from vantage.helpers import config
from vantage.parsers.spells import (
    CustomTrigger, compile_trigger_pattern, dynamic_timer_seconds,
    render_trigger_text)


def test_named_token_captures_and_renders_alert():
    config.data = {'sharing': {'player_name': 'Gandalf'}}
    trigger = CustomTrigger(alert_text='{spell} #{COUNTER}')
    trigger.counter = 3
    match = compile_trigger_pattern('You begin casting {spell}').match(
        'You begin casting Chloroplast')
    assert match.group('spell') == 'Chloroplast'
    assert render_trigger_text(trigger.alert_text, match, trigger) == 'Chloroplast #3'


def test_character_token_matches_detected_character():
    pattern = compile_trigger_pattern('{c} has fallen to the ground', 'Gandalf')
    assert pattern.match('Gandalf has fallen to the ground')
    assert not pattern.match('Frodo has fallen to the ground')


def test_imported_regex_and_numeric_group_rendering():
    trigger = CustomTrigger(name='Spawn ${1}', regex=True)
    match = compile_trigger_pattern(
        r'^You have slain (.+)!$', raw_regex=True).match(
            'You have slain Quillmane!')

    assert match
    assert render_trigger_text(trigger.name, match, trigger) == 'Spawn Quillmane'


def test_gina_dynamic_timespan_token_captures_and_resolves_duration():
    trigger = CustomTrigger(
        name="Dynamic {ts}", text="Respawn in {ts}", time="00:00:00",
        timer_type="countdown")
    match = compile_trigger_pattern(trigger.text).match(
        "Respawn in 1:02:03.5")
    assert match
    assert trigger.timer_type == "countdown"
    assert dynamic_timer_seconds(match) == 3723.5
    assert render_trigger_text(trigger.name, match, trigger) == (
        "Dynamic 1:02:03.5")


def test_dynamic_timespan_supports_days_and_bare_seconds():
    pattern = compile_trigger_pattern("Wait {ts}")
    assert dynamic_timer_seconds(pattern.match("Wait 45")) == 45
    assert dynamic_timer_seconds(pattern.match("Wait 2:03:04:05")) == 183845


def test_trigger_round_trip_preserves_gina_style_routing_and_behavior():
    trigger = CustomTrigger(
        name='Charm on {target}', text='{target} is charmed', time='00:03:00',
        category='Enchanter', overlay_id='timers', restart_behavior='keep',
        end_text='Your charm spell has worn off.', profile='Gandalf',
        comments='Track charm safely', timer_type='repeating',
        timer_visible_seconds=30, timer_ending_seconds=12,
        timer_ending_alert='Charm ending',
        timer_ending_sound='builtin:crystal-ping',
        timer_ended_alert='Charm ended',
        counter_reset_seconds=120, clipboard_text='/g Charm ended',
        tts_text='Charm on target', interrupt_speech=True,
        timer_ending_tts='Charm ending soon',
        timer_ending_interrupt=True,
        timer_ended_tts='Charm finished', timer_ended_interrupt=False,
        timer_name='Charm · {target}',
        restart_based_on_timer_name=True,
        end_patterns=[
            {'text': 'Your charm spell has worn off.', 'regex': False},
            {'text': '^Charm target died$', 'regex': True}])

    restored = CustomTrigger(*trigger.to_list())
    assert restored.category == 'Enchanter'
    assert restored.overlay_id == 'timers'
    assert restored.restart_behavior == 'keep'
    assert restored.end_text == 'Your charm spell has worn off.'
    assert restored.profile == 'Gandalf'
    assert restored.comments == 'Track charm safely'
    assert restored.timer_type == 'repeating'
    assert restored.timer_visible_seconds == 30
    assert restored.timer_ending_seconds == 12
    assert restored.timer_ending_alert == 'Charm ending'
    assert restored.timer_ending_sound == 'builtin:crystal-ping'
    assert restored.timer_ended_alert == 'Charm ended'
    assert restored.counter_reset_seconds == 120
    assert restored.clipboard_text == '/g Charm ended'
    assert restored.tts_text == 'Charm on target'
    assert restored.interrupt_speech is True
    assert restored.timer_ending_tts == 'Charm ending soon'
    assert restored.timer_ending_interrupt is True
    assert restored.timer_ended_tts == 'Charm finished'
    assert restored.timer_name == 'Charm · {target}'
    assert restored.restart_based_on_timer_name is True
    assert len(restored.end_patterns) == 2


def test_first_run_seeds_the_essential_p99_alerts():
    previous = config.data
    try:
        config.data = {}
        config.verify_settings()
        triggers = {
            CustomTrigger(*item).name: CustomTrigger(*item)
            for item in config.data['spells']['custom_timers']
        }
        assert triggers['Invisibility Fading'].enabled is True
        assert triggers['Charm Break'].sound_path == 'builtin:danger-double'
        assert triggers['Fizzle'].time == '00:00:00'
        assert triggers['Critical hit'].enabled is False
    finally:
        config.data = previous
