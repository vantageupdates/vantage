from vantage.helpers.spawn_timer import (
    PHASE_AVAILABLE,
    PHASE_COMBAT,
    PHASE_RESPAWN,
    SpawnTimerState,
    reset_stale_persisted_timers,
    zone_timer_visible,
    parse_duration_input,
)
from vantage.helpers.respawn_catalog import (
    NAMED_SPAWN_CATALOG, RESPAWN_CATALOG, duration_seconds,
    named_spawn_for, respawn_for_short_name)
from vantage.parsers.timers import (
    extract_killed_mob, extract_log_timer_command)


def test_manual_kill_anchors_respawn_and_increments_cycle():
    timer = SpawnTimerState("Quillmane", 1920, kill_seconds=45)
    timer.mark_killed(100)
    assert timer.phase == PHASE_RESPAWN
    assert timer.deadline == 2020
    assert timer.cycles == 1


def test_smart_timer_moves_from_spawn_to_combat():
    timer = SpawnTimerState("Mob", 60, kill_seconds=10, warning_seconds=5)
    timer.start(0)
    events = timer.tick(60)
    assert [event.kind for event in events] == ["spawn"]
    assert timer.phase == PHASE_COMBAT
    assert timer.deadline == 70


def test_smart_timer_catches_up_across_missed_cycles():
    timer = SpawnTimerState("Mob", 60, kill_seconds=10)
    timer.start(0)
    events = timer.tick(145)
    assert [event.kind for event in events] == ["spawn", "auto_kill", "spawn", "auto_kill"]
    assert timer.phase == PHASE_RESPAWN
    assert timer.deadline == 200
    assert timer.cycles == 2


def test_non_smart_timer_waits_for_manual_confirmation():
    timer = SpawnTimerState("Mob", 60, smart=False)
    timer.start(0)
    timer.tick(90)
    assert timer.phase == PHASE_AVAILABLE
    assert timer.deadline is None


def test_pause_and_resume_preserve_remaining_time():
    timer = SpawnTimerState("Mob", 60)
    timer.start(0)
    timer.pause(20)
    assert timer.remaining(90) == 40
    timer.resume(100)
    assert timer.deadline == 140


def test_kill_match_honors_zone_and_regex():
    timer = SpawnTimerState("Quillmane", 100, zone="South Karana", mob_pattern=r"^Quillmane$")
    assert timer.matches_kill("Quillmane", "South Karana")
    assert not timer.matches_kill("Quillmane", "North Karana")


def test_friendly_duration_input_uses_minutes_for_bare_numbers():
    assert parse_duration_input("3") == 180
    assert parse_duration_input("3:50") == 230
    assert parse_duration_input("1:03:50") == 3830
    assert parse_duration_input("90s") == 90
    assert parse_duration_input("1.5h") == 5400
    assert parse_duration_input("bad input") == 0


def test_saved_countdowns_reset_only_after_configured_clean_shutdown_gap():
    recent = {
        "items": [{"name": "Keep me", "phase": "respawn", "running": True}],
        "clear_after_hours": 4,
        "last_session_closed_at": 10_000,
    }
    assert reset_stale_persisted_timers(recent, 10_000 + 3 * 3600) is False
    assert recent["items"][0]["running"] is True
    assert recent["last_session_closed_at"] == 0.0

    stale = {
        "items": [{
            "name": "Keep this row", "zone": "Velketor's Labyrinth",
            "phase": "respawn", "running": True, "deadline": 99_000,
        }],
        "clear_after_hours": 4,
        "last_session_closed_at": 10_000,
    }
    assert reset_stale_persisted_timers(stale, 10_000 + 4 * 3600) is True
    assert len(stale["items"]) == 1
    assert stale["items"][0]["name"] == "Keep this row"
    assert stale["items"][0]["zone"] == "Velketor's Labyrinth"
    assert stale["items"][0]["phase"] == "idle"
    assert stale["items"][0]["running"] is False
    assert stale["items"][0]["deadline"] is None
    assert stale["items"][0]["cycles"] == 0
    assert stale["last_session_closed_at"] == 0.0


def test_unclean_or_legacy_session_does_not_discard_saved_timers():
    settings = {
        "items": [{"name": "Preserve me"}],
        "clear_after_hours": 4,
        "last_session_closed_at": 0,
    }
    assert reset_stale_persisted_timers(settings, 99_999) is False
    assert settings["items"] == [{"name": "Preserve me"}]


def test_zone_timer_rows_are_grouped_without_losing_global_rows():
    assert zone_timer_visible("Velketor's Labyrinth", "Velketor's Labyrinth")
    assert zone_timer_visible("velketor's labyrinth", "VELKETOR'S LABYRINTH")
    assert not zone_timer_visible("Kael Drakkel", "Velketor's Labyrinth")
    assert zone_timer_visible("", "Velketor's Labyrinth")
    assert zone_timer_visible("Kael Drakkel", "")


def test_timer_volume_is_individual_and_clamped():
    loud = SpawnTimerState("Loud", 60, volume=100)
    quiet = SpawnTimerState("Quiet", 60, volume=20)
    invalid = SpawnTimerState("Invalid", 60, volume=500)

    assert loud.volume == 100
    assert quiet.volume == 20
    assert invalid.volume == 100
    assert SpawnTimerState.from_dict(quiet.to_dict()).volume == 20


def test_death_lines_extract_every_mob_name_without_punctuation():
    assert extract_killed_mob("You have slain Quillmane!") == "Quillmane"
    assert extract_killed_mob(
        "myconid spore king has been slain by Mindflux.") == \
        "myconid spore king"
    assert extract_killed_mob("You slash a kobold for 10 points") is None


def test_established_log_timer_commands_accept_seconds_and_labels():
    assert extract_log_timer_command(
        "You say, 'StartTimer-30-Invis_Check'") == (30, 'Invis Check')
    assert extract_log_timer_command(
        "Alice tells you, 'PigTimer-6:40-Guard_George'") == (
            400, 'Guard George')
    assert extract_log_timer_command(
        "You tell yourself, 'StartTimer-1:02:00-Ring8'") == (
            3720, 'Ring8')
    assert extract_log_timer_command('ordinary chat') is None


def test_complete_zone_catalog_covers_every_bundled_map_short_name():
    from vantage.parsers.maps.mapdata import MapData

    assert len(RESPAWN_CATALOG) == 121
    assert set(MapData.get_zone_dict().values()) == set(RESPAWN_CATALOG)
    assert respawn_for_short_name("velketor").seconds == 32 * 60 + 50
    assert respawn_for_short_name("highpass").seconds == 22 * 60
    assert duration_seconds("8 hours") == 8 * 3600


def test_automatic_catalog_accepts_named_mobs_and_rejects_zone_trash():
    assert len(NAMED_SPAWN_CATALOG) >= 900
    assert named_spawn_for("velketor", "Crystal Fang") is not None
    assert named_spawn_for("velketor", "a crystalline watcher") is None
    assert named_spawn_for("southkarana", "Quillmane") is not None


def test_automatic_timer_metadata_survives_persistence():
    timer = SpawnTimerState(
        "Quillmane", 400, source="P99 catalog", automatic=True)
    restored = SpawnTimerState.from_dict(timer.to_dict())
    assert restored.source == "P99 catalog"
    assert restored.automatic is True
