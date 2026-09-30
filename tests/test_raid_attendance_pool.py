from copy import deepcopy
from vantage.helpers import config
from vantage.helpers.raid_attendance import (
    sanitize_attendance_alts, pool_raid_attendance, pooled_tick_evidence)


def event(raid_id=1, tick_id=1, value=0.5, pool='Main'):
    return {'RaidId': raid_id, 'RaidName': 'Vindi', 'PoolName': pool,
            'Ticks': [{'TickId': tick_id, 'Attended': 1, 'Value': value}]}


def test_saved_alts_sanitize_deduplicate_bound_and_round_trip(monkeypatch):
    entries = [{'character_id': '1', 'name': ' Wildflux '},
               {'character_id': 1, 'name': 'Duplicate'},
               {'character_id': 'bad', 'name': 'Bad'}, {'character_id': 0, 'name': 'Bad'}]
    assert sanitize_attendance_alts(entries) == [{'character_id': 1, 'name': 'Wildflux'}]
    assert len(sanitize_attendance_alts([{'character_id': i, 'name': f'Alt{i}'} for i in range(1, 100)])) == 24
    monkeypatch.setattr(config, 'data', {'opendkp': {'guilds': [
        {'slug': 'castle', 'attendance_alts': entries, 'attendance_include_alts': False},
        {'slug': 'other', 'attendance_alts': [{'character_id': 2, 'name': 'Fistflux'}]}]}})
    config.verify_settings()
    before = deepcopy(config.data['opendkp']['guilds'])
    config.verify_settings()
    assert config.data['opendkp']['guilds'] == before
    assert before[0]['attendance_alts'] == [{'character_id': 1, 'name': 'Wildflux'}]
    assert before[0]['attendance_include_alts'] is False
    assert before[1]['attendance_alts'][0]['name'] == 'Fistflux'


def test_duplicate_raids_and_ticks_union_without_mutating_inputs():
    original = event()
    rows = pool_raid_attendance({'Mindflux': [original, original], 'Wildflux': [event(), event(2, 2, 1)]})
    assert len(rows) == 2
    shared = next(row for row in rows if row['RaidId'] == 1)
    assert shared['_attendance_tick_count'] == 1
    assert shared['_attendance_dkp'] == 0.5
    assert len(shared['_attendance_members']) == 2
    assert '_attendance_members' not in original


def test_distinct_ticks_same_raid_merge_and_keep_different_pools_separate():
    rows = pool_raid_attendance({'Mindflux': [event()], 'Spiritflux': [event(1, 2, 1), event(2, 3, 2, 'Other')]})
    assert rows[0]['_attendance_tick_count'] == 2
    assert rows[0]['_attendance_dkp'] == 1.5
    assert rows[1]['PoolName'] == 'Other'


def test_missing_ids_conflicting_and_unknown_awards_are_not_invented():
    rows = pool_raid_attendance({'Mindflux': [event(value=None)], 'Wildflux': [event(value=0.5)]})
    assert rows[0]['_attendance_dkp'] is None
    assert pool_raid_attendance({'A': [event(value=1)], 'B': [event(value=2)]})[0]['_attendance_dkp'] is None
    row = pool_raid_attendance({'A': [event(tick_id=None)], 'B': [event(tick_id=None)]})[0]
    assert row['_attendance_tick_count'] is None
    assert row['_attendance_dkp'] is None


def test_detail_shared_tick_award_counted_once_and_per_character_counts_kept():
    payload = {'Ticks': [
        {'TickId': 1, 'Value': 0.5, 'Characters': [{'Name': 'Mindflux'}, {'Name': 'Wildflux'}]},
        {'TickId': 2, 'Value': 1, 'Characters': [{'Name': 'Spiritflux'}]}]}
    assert pooled_tick_evidence(payload, ['Mindflux', 'Wildflux', 'Spiritflux']) == (
        2, 1.5, {'Mindflux': 1, 'Wildflux': 1, 'Spiritflux': 1})
