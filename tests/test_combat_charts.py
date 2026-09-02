import datetime

from vantage.helpers.combat import AttackerStats, CombatEvent, Encounter, HealStats
from vantage.helpers.combat_charts import build_chart_data


def _encounter():
    started = datetime.datetime(2026, 1, 1, 12, 0, 0)
    fight = Encounter("Velketor", started, started + datetime.timedelta(seconds=8))
    alice = fight.attackers.setdefault("Alice", AttackerStats("Alice"))
    alice.add(100, "Slashing", started)
    alice.add(50, "Slashing", started + datetime.timedelta(seconds=6))
    bob = fight.attackers.setdefault("Bob", AttackerStats("Bob"))
    bob.add(60, "Piercing", started + datetime.timedelta(seconds=1))
    healer = fight.healers.setdefault("Cleric", HealStats("Cleric"))
    healer.add(80, "Alice")
    fight.events.extend((
        CombatEvent(started, "Damage", "Alice", "Velketor", 100),
        CombatEvent(started + datetime.timedelta(seconds=1),
                    "Damage", "Bob", "Velketor", 60),
        CombatEvent(started + datetime.timedelta(seconds=2),
                    "Incoming", "Velketor", "Alice", 40),
        CombatEvent(started + datetime.timedelta(seconds=3),
                    "Heal", "Cleric", "Alice", 80),
        CombatEvent(started + datetime.timedelta(seconds=6),
                    "Damage", "Alice", "Velketor", 50),
    ))
    return fight


def test_damage_chart_has_raw_rolling_and_average_series():
    chart = build_chart_data(_encounter(), "damage_timeline", "Total")
    assert chart["kind"] == "line"
    assert [series["name"] for series in chart["series"]] == [
        "Damage / second", "Rolling 6s DPS", "Average DPS"]
    assert chart["series"][0]["values"][0] == 100
    assert chart["series"][0]["values"][1] == 60
    assert chart["series"][0]["values"][6] == 50
    assert round(chart["series"][1]["values"][1], 1) == 80.0


def test_chart_actor_filter_and_damage_bars_are_exact():
    timeline = build_chart_data(_encounter(), "damage_timeline", "Alice")
    assert sum(timeline["series"][0]["values"]) == 150
    bars = build_chart_data(_encounter(), "damage_total")
    assert bars["labels"] == [("Alice", 150.0), ("Bob", 60.0)]


def test_tanking_chart_keeps_incoming_and_observed_healing_separate():
    chart = build_chart_data(_encounter(), "tanking_timeline", "Alice")
    assert sum(chart["series"][0]["values"]) == 40
    assert sum(chart["series"][2]["values"]) == 80


def test_long_fights_are_bounded_to_about_six_hundred_bins():
    started = datetime.datetime(2026, 1, 1)
    fight = Encounter(
        "Long fight", started, started + datetime.timedelta(hours=2))
    fight.events.append(CombatEvent(started, "Damage", "You", "Mob", 1))
    fight.events.append(CombatEvent(
        fight.last_at, "Damage", "You", "Mob", 1))
    chart = build_chart_data(fight, "damage_timeline")
    assert len(chart["series"][0]["values"]) <= 601
    assert chart["step"] > 1
