from vantage.helpers.encounter_events import (
    QUAKE_LINES, RING_WAR_START, parse_encounter_event,
    ring_war_milestones)


def test_exact_fte_quake_and_ring_war_detection():
    fte = parse_encounter_event("Dain Frostreaver IV engages Mindflux!")
    assert (fte.kind, fte.player, fte.npc, fte.message) == (
        "fte", "Mindflux", "Dain Frostreaver IV",
        "Mindflux FTE Dain Frostreaver IV")

    for line in QUAKE_LINES:
        quake = parse_encounter_event(line)
        assert quake.kind == "quake"
    assert parse_encounter_event(RING_WAR_START).kind == "ring_war"

    assert parse_encounter_event(
        "Dain Frostreaver IV engages Mindflux.") is None
    assert parse_encounter_event("WinEQ2 Control Panel") is None


def test_ring_war_schedule_matches_original_cumulative_timing():
    rows = ring_war_milestones()
    assert len(rows) == 24
    assert [(row.timer_name, row.seconds) for row in rows[:8]] == [
        ("Ring War · Wave 1 · Round 1", 210),
        ("Ring War · Wave 1 · Round 2", 420),
        ("Ring War · Wave 1 · Round 3", 630),
        ("Ring War · Wave 1 · Round 4", 840),
        ("Ring War · Wave 1 · Round 5", 1050),
        ("Ring War · Wave 1 · Round 6", 1260),
        ("Ring War · Wave 1 · Round 7", 1470),
        ("Ring War · Wave 1 · Break", 1770),
    ]
    assert rows[8].seconds == 1980
    assert rows[15].seconds == 3540
    assert rows[16].seconds == 3750
    assert rows[-1].timer_name == "Ring War · Wave 3 · Break"
    assert rows[-1].seconds == 5319

