from vantage.helpers import config
from vantage.parsers.spells import CustomTrigger, compile_trigger_pattern


FAILURE_LINES = {
    "Target too far": "Your target is too far away, get closer!",
    "Target out of range": "Your target is out of range, get closer!",
    "Cannot see target": "You can't see your target from here.",
    "No target selected": "You must first select a target for this spell!",
    "Spell not recovered": "You haven't recovered yet...",
}


def _definitions():
    return {
        row[0]: CustomTrigger(*row) for row in config.BASIC_ALERTS
        if row[0] in FAILURE_LINES
    }


def test_basic_spell_failures_are_exact_anchored_editable_routes():
    definitions = _definitions()
    assert definitions.keys() == FAILURE_LINES.keys()
    for name, line in FAILURE_LINES.items():
        trigger = definitions[name]
        pattern = compile_trigger_pattern(
            trigger.text, raw_regex=trigger.regex)
        assert trigger.regex is True
        assert pattern.match(line)
        assert not pattern.match("Prefix " + line)
        assert not pattern.match(line + " suffix")
        assert not pattern.match(f'Player says, "{line}"')
        assert trigger.enabled is True
        assert trigger.audio_delivery("basic") == "sound"
        assert trigger.tts_text == trigger.alert_text
        assert trigger.match_cooldown_seconds == 1.0
        assert len(trigger.to_list()) == 48


def test_basic_failure_v4_migration_preserves_customized_same_name(
        tmp_path, monkeypatch):
    previous = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    customized = [
        "TARGET OUT OF RANGE", FAILURE_LINES["Target out of range"],
        "00:00:00", "", "my-custom.wav", "My custom range alert",
        False, False, "Vantage · Basics",
    ]
    try:
        config.data = {
            "spells": {
                "custom_timers": [customized.copy()],
                "basic_alerts_version": 4,
            }
        }
        config.verify_settings()
        rows = config.data["spells"]["custom_timers"]
        matches = [
            row for row in rows
            if row[0].casefold() == "target out of range"]
        assert matches == [customized]
        assert config.data["spells"]["basic_alerts_version"] == 5
        assert all(
            sum(row[0].casefold() == name.casefold() for row in rows) == 1
            for name in FAILURE_LINES)
    finally:
        config.data = previous
