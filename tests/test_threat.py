import datetime

from vantage.helpers.threat import ThreatEstimator
from vantage.helpers.threat_presets import WEAPON_PRESETS, find_weapon_preset


def at(seconds):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=seconds)


def settings(main_type="1hs", off_type="1hp"):
    return {
        "enabled": True,
        "same_type_main_rate": 55,
        "main_hand": {
            "name": "Main", "type": main_type, "damage": 20, "delay": 30,
            "damage_bonus": 18, "proc_threat": 500,
            "proc_landed": "{target} is wrapped in lightning.",
            "proc_resisted": "Your target resisted the Lightning spell.",
        },
        "off_hand": {
            "name": "Off", "type": off_type, "damage": 15, "delay": 25,
            "damage_bonus": 0, "proc_threat": 0,
            "proc_landed": "", "proc_resisted": "",
        },
    }


def test_threat_counts_weapon_attempts_and_skills_by_target():
    estimator = ThreatEstimator(settings())
    estimator.ingest(at(0), "You slash a frost giant for 72 points of damage.")
    estimator.ingest(at(2), "You try to pierce a frost giant, but miss!")
    estimator.ingest(at(3), "You kick a frost giant for 8 points of damage.")

    target = estimator.current()
    assert target.name == "a frost giant"
    assert target.main_swings == 1
    assert target.off_swings == 1
    assert target.skill_threat == 5
    assert target.total == 31 + 27 + 5


def test_same_animation_weapons_use_configurable_split():
    estimator = ThreatEstimator(settings("1hs", "1hs"))
    estimator.ingest(at(0), "You slash a goblin for 10 points of damage.")
    estimator.ingest(at(1), "You try to slash a goblin, but miss!")

    target = estimator.current()
    expected_per_attempt = 31 * 0.55 + 27 * 0.45
    assert round(target.total, 2) == round(expected_per_attempt * 2, 2)
    assert target.tied_swings == 2
    assert target.main_swings + target.off_swings == 2


def test_two_hand_threat_uses_configured_damage_bonus():
    values = settings("2hs", "none")
    estimator = ThreatEstimator(values)
    estimator.ingest(at(0), "You slash Venril Sathir for 100 points of damage.")
    assert estimator.current().total == 38


def test_supported_spells_and_resists_apply_to_current_target():
    estimator = ThreatEstimator(settings())
    estimator.ingest(at(0), "You begin casting Flame Lick.")
    estimator.ingest(at(1), "a wolf is surrounded by flickering flames.")
    estimator.ingest(at(2), "You begin casting Jolt.")
    estimator.ingest(at(3), "a wolf's head snaps back.")
    estimator.ingest(at(4), "You begin casting Enveloping Roots.")
    estimator.ingest(at(5), "Your target resisted the Enveloping Roots spell.")

    target = estimator.current()
    assert target.spell_threat == 1200 - 500 + 1310
    assert target.total == 2010


def test_configured_proc_text_adds_once_and_kill_closes_current_target():
    estimator = ThreatEstimator(settings())
    estimator.ingest(at(0), "You slash a spectre for 12 points of damage.")
    estimator.ingest(at(1), "a spectre is wrapped in lightning.")
    assert estimator.current().procs == 1
    assert estimator.current().total == 531

    estimator.ingest(at(2), "You have slain a spectre!")
    assert estimator.current() is None
    assert estimator.recent()[0].killed is True


def test_unknown_spell_threat_attaches_to_the_next_target_swing():
    estimator = ThreatEstimator(settings())
    estimator.ingest(at(0), "You begin casting Flame Lick.")
    estimator.ingest(at(1), "Your target resisted the Flame Lick spell.")
    assert estimator.pending_unknown == 1200
    estimator.ingest(at(2), "You slash a basilisk for 15 points of damage.")
    assert estimator.current().total == 1231
    assert estimator.pending_unknown == 0


def test_curated_weapon_aliases_fill_stats_and_proc_messages():
    willsapper = find_weapon_preset('WS')
    earthcaller = find_weapon_preset('earth')
    assert len(WEAPON_PRESETS) >= 20
    assert willsapper['name'] == 'Willsapper'
    assert (willsapper['damage'], willsapper['delay'], willsapper['type']) == (
        13, 20, '1hp')
    assert willsapper['proc_threat'] == 400
    assert earthcaller['proc_landed'] == (
        '{target} is slowed by the embracing earth.')


def test_curated_proc_preset_runs_through_local_estimator():
    preset = find_weapon_preset('willsapper')
    values = {
        'enabled': True,
        'same_type_main_rate': 55,
        'main_hand': preset,
        'off_hand': {'type': 'none'},
    }
    estimator = ThreatEstimator(values)
    estimator.ingest(at(0), 'You pierce a wurm for 10 points of damage.')
    estimator.ingest(at(1), 'a wurm yawns.')
    assert estimator.current().main_swings == 1
    assert estimator.current().procs == 1
    assert estimator.current().total == 13 + 11 + 400
