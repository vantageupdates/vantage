"""Pure local tests for raid evidence persistence and OpenDKP matching."""

import datetime
import sqlite3

from vantage.helpers.raid_ledger import (
    VERIFIED, RaidLedger, raid_time_matches, remote_tick_evidence)


def test_local_raid_evidence_round_trip(tmp_path):
    ledger = RaidLedger(tmp_path / "ledger.sqlite")
    started = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(
        started, "Mindflux", "Green", "Kael Drakkel")
    assert ledger.add_tick(
        session["id"], started, "Raidlead", "RAID TICK")
    assert ledger.add_roster(
        session["id"], started, "Kael Drakkel",
        ["Mindflux", "Raidlead"])
    assert ledger.update_session(
        session["id"], mobs="Statue", notes="Present from start")
    assert ledger.link_remote(session["id"], "raid-42")
    ledger.set_check(
        session["id"], VERIFIED, remote_id="raid-42",
        remote_name="Statue", tick_count=2, dkp_total=12.5)

    saved = ledger.session(session["id"])
    evidence = ledger.evidence(session["id"])
    assert saved["manual_remote"] == 1
    assert saved["verification_status"] == VERIFIED
    assert saved["waiting_for_who"] == 0
    assert evidence["ticks"][0]["speaker"] == "Raidlead"
    assert evidence["rosters"][0]["members"] == ["Mindflux", "Raidlead"]
    ledger.close()


def test_log_search_tick_metadata_is_duplicate_safe_and_persists(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = RaidLedger(path)
    started = datetime.datetime(2026, 9, 26, 19, 30)
    session = ledger.start_session(started, "Mindflux", "Green", "Kael")
    source = "log-search:archive/eqlog_Mindflux_Green.txt"
    assert ledger.add_tick(
        session["id"], started, "Raidlead", "RAID TICK", source,
        "Mindflux", "Green") is True
    assert ledger.add_tick(
        session["id"], started, "Raidlead", "RAID TICK", source,
        "Mindflux", "Green") is False
    assert ledger.add_tick(
        session["id"], started, "raidlead", "raid tick", "log",
        "Mindflux", "Green") is False
    ledger.close()

    reopened = RaidLedger(path)
    tick = reopened.evidence(session["id"])["ticks"][0]
    assert tick == {
        "timestamp": "2026-09-26 19:30:00",
        "speaker": "Raidlead",
        "message": "RAID TICK",
        "source": source,
        "character": "Mindflux",
        "server": "Green",
    }
    reopened.close()


def test_existing_raid_tick_database_adds_log_profile_metadata_columns(tmp_path):
    path = tmp_path / "legacy-ledger.sqlite"
    database = sqlite3.connect(path)
    database.execute("""
        CREATE TABLE raid_ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            speaker TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'log',
            UNIQUE(session_id, timestamp, speaker, message, source))
    """)
    database.commit()
    database.close()

    ledger = RaidLedger(path)
    columns = {row[1] for row in ledger._database.execute(
        "PRAGMA table_info(raid_ticks)").fetchall()}
    assert {"character", "server"}.issubset(columns)
    ledger.close()


def test_current_opendkp_ticks_sum_only_the_selected_toon():
    detail = {"Ticks": [
        {"TickId": 1, "Value": 5,
         "Characters": [{"Name": "Mindflux"}, {"Name": "Other"}]},
        {"TickId": 2, "Value": 7.5,
         "Characters": [{"Name": "Mindflux"}]},
        {"TickId": 3, "Value": 20,
         "Characters": [{"Name": "SomeoneElse"}]},
    ]}
    ticks, dkp = remote_tick_evidence(detail, "mindflux")
    assert [tick["TickId"] for tick in ticks] == [1, 2]
    assert dkp == 12.5


def test_tick_membership_accepts_current_opendkp_character_name_shapes():
    detail = {"Ticks": [
        {"TickId": 1, "Value": "4.5",
         "Characters": [{"PlayerName": "Mindflux"}]},
        {"TickId": 2, "Value": 8,
         "Characters": [{"MemberName": "SomeoneElse"}]},
    ]}
    ticks, dkp = remote_tick_evidence(detail, "Mindflux")
    assert [tick["TickId"] for tick in ticks] == [1]
    assert dkp == 4.5


def test_automatic_match_requires_a_safe_time_window():
    session = {
        "started_at": "2026-09-26T19:00:00-04:00",
        "ended_at": "2026-09-26T23:00:00-04:00"}
    assert raid_time_matches(
        session, {"Timestamp": "2026-09-27T00:30:00Z"})
    assert not raid_time_matches(
        session, {"Timestamp": "2026-09-30T00:30:00Z"})
