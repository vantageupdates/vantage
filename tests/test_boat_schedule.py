import datetime

from vantage.helpers.boats import (
    BOAT_ROUTES, route_for_announcement, schedules_from_activities)


UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 8, 30, 13, 20, tzinfo=UTC)


def _remaining(values):
    return {
        schedule.route.start_point: schedule.remaining_seconds
        for schedule in values}


def test_eqtool_phase_math_is_preserved_for_barrel_barge():
    current = schedules_from_activities([{
        'startPoint': 'oasis', 'boat': 0,
        'lastSeen': (NOW - datetime.timedelta(seconds=10)).isoformat(),
    }], NOW)
    assert _remaining(current) == {'oasis': 109, 'timorous': 500}

    after_five_trips = schedules_from_activities([{
        'startPoint': 'oasis', 'boat': 0,
        'lastSeen': (NOW - datetime.timedelta(
            seconds=BOAT_ROUTES[0].trip_seconds * 5 + 10)).isoformat(),
    }], NOW)
    repeated = _remaining(after_five_trips)
    assert abs(repeated['oasis'] - 109) <= 1
    assert abs(repeated['timorous'] - 500) <= 1


def test_schedule_uses_latest_observation_and_marks_old_data_stale():
    values = schedules_from_activities([
        {'startPoint': 'butcher', 'boat': 2,
         'lastSeen': (NOW - datetime.timedelta(days=3)).isoformat()},
        {'startPoint': 'firiona', 'boat': 2,
         'lastSeen': (NOW - datetime.timedelta(seconds=30)).isoformat()},
    ], NOW, source='PigParse API · Green')
    assert len(values) == 2
    assert all(value.source == 'PigParse API · Green' for value in values)
    assert not any(value.stale for value in values)
    stale = schedules_from_activities([{
        'startPoint': 'nro', 'boat': 3,
        'lastSeen': (NOW - datetime.timedelta(days=1)).isoformat(),
    }], NOW)
    assert all(value.stale for value in stale)


def test_exact_boat_announcement_is_detected_without_loose_guessing():
    route = route_for_announcement(
        "Rack Stonebelly shouts, 'Da Barrel Barge will be here soon soon!'")
    assert route is not None
    assert (route.boat_name, route.start_point) == ('Barrel Barge', 'oasis')
    assert route_for_announcement('The boat may arrive soon') is None
