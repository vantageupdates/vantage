import datetime

from vantage.helpers.heal_chain import HealChainTracker


def at(seconds):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=seconds)


def test_parses_ch_calls_and_computes_next_marker():
    tracker = HealChainTracker("### - CH - tankname", interval=3)
    event, cast = tracker.ingest(
        at(0), "Althea tells the guild, 'AAA - CH - Dain'")
    assert event == "cast"
    assert cast.cleric == "Althea"
    assert cast.tank == "Dain"
    assert tracker.next_marker("Dain", "AAA") == "BBB"
    tracker.ingest(at(2), "Brielle tells the guild, 'BBB - CH - Dain'")
    assert tracker.next_marker("Dain", "BBB") == "CCC"
    tracker.ingest(at(4), "Althea tells the guild, 'AAA - CH - Dain'")
    assert tracker.next_marker("Dain", "BBB") == "AAA"
    assert len(tracker.active(at(5))) == 3
    assert tracker.active(at(15)) == []


def test_custom_format_interval_command_and_interruptions():
    tracker = HealChainTracker("ST ### CH -- tankname")
    event, cast = tracker.ingest(
        at(0), "You tell your guild, 'ST CCC CH -- Vulak'")
    assert event == "cast"
    assert tracker.local_marker == "CCC"
    assert tracker.ingest(at(1), "Someone tells the guild, '!KI5'") == (
        "interval", 5)
    event, interrupted = tracker.ingest(at(2), "Your spell is interrupted.")
    assert event == "interrupt"
    assert interrupted is cast
    assert cast.interrupted is True


def test_clear_command_resets_chain():
    tracker = HealChainTracker()
    tracker.ingest(at(0), "A tells the group, 'AAA - CH - Tank'")
    event, _ = tracker.ingest(at(1), "clearcch is not online at this time.")
    assert event == "clear"
    assert not tracker.casts
    assert not tracker.rosters
