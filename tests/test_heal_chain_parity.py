"""Synthetic CH call compatibility and conservative event attribution."""

from datetime import datetime, timedelta

import pytest

from vantage.helpers.heal_chain import HealChainTracker


def at(seconds=0):
    return datetime(2026, 10, 13) + timedelta(seconds=seconds)


@pytest.mark.parametrize("channel", (
    "say", "say out of character", "shout", "auction",
    "tell your party", "tell your guild", "tell the group",
))
def test_own_calls_work_in_each_supported_chat_channel(channel):
    tracker = HealChainTracker()
    event, cast = tracker.ingest(at(), f"You {channel}, 'AAA - CH - Tank'")
    assert event == "cast" and cast.cleric == "You"
    assert tracker.local_marker == "AAA"


@pytest.mark.parametrize("message,marker,tank", (
    ("GG 001 CH -- Tank", "001", "Tank"),
    ("AAA CH -- Tank", "AAA", "Tank"),
    ("CA RAMP1 CH -- Tank", "RAMP1", "Tank"),
    ("RAMP02 CH -- Tank", "RAMP02", "Tank"),
    ("CH - Tank - 003", "003", "Tank"),
    ("GG RCH BBB -- Tank", "BBB", "Tank"),
    ("GG RCH BBB CH -- Tank", "BBB", "Tank"),
    ("007 CH -- a shiverback", "007", "a shiverback"),
    ("AAA --- CH << Tank >> --- AAA", "AAA", "Tank"),
))
def test_default_accepts_common_ordered_ch_calls(message, marker, tank):
    tracker = HealChainTracker()
    event, cast = tracker.ingest(at(), f"Cleric says out of character, '{message}'")
    assert event == "cast" and cast.marker == marker and cast.tank == tank


@pytest.mark.parametrize("message", (
    "Currently signed up as 001 in CH chain", "when CH chains work",
    "CH please", "CH - Tank - 003 extra words", "003 - CH 5T",
))
def test_normal_chat_does_not_become_a_heal(message):
    assert HealChainTracker().ingest(at(), f"Cleric says, '{message}'") is None


def test_custom_format_remains_an_explicit_filter_and_accepts_pet_target():
    tracker = HealChainTracker("TEAM ### healing tankname")
    assert tracker.ingest(at(), "Cleric shouts, '001 CH -- Tank'") is None
    event, cast = tracker.ingest(at(), "Cleric shouts, 'TEAM 001 healing a shiverback'")
    assert event == "cast" and cast.tank == "a shiverback"


@pytest.mark.parametrize("marker,following", (
    ("001", "002"), ("009", "010"), ("111", "222"),
    ("AAA", "BBB"), ("ZZZ", "AAA"), ("R11", "R22"),
))
def test_chain_marker_progression(marker, following):
    assert HealChainTracker().next_marker("Tank", marker) == following


def test_interruptions_only_change_current_casts():
    tracker = HealChainTracker()
    _, old = tracker.ingest(at(), "Cleric tells the guild, 'AAA - CH - Tank'")
    assert tracker.ingest(at(60), "Cleric's casting is interrupted!") is None
    assert not old.interrupted
    _, current = tracker.ingest(at(61), "Cleric tells the guild, 'AAA - CH - Tank'")
    assert tracker.ingest(at(62), "Cleric's casting is interrupted!") == ("interrupt", current)
    assert current.interrupted and not old.interrupted


@pytest.mark.parametrize("message", ("!KI10", "!KI3x", "please use !KI5 later"))
def test_interval_command_must_be_a_complete_supported_command(message):
    tracker = HealChainTracker(interval=4)
    assert tracker.ingest(at(), f"Cleric tells the guild, '{message}'") is None
    assert tracker.interval == 4


def test_invalid_duplicate_template_is_safe():
    tracker = HealChainTracker("### ### tankname")
    result = tracker.ingest(at(), "Cleric tells the guild, 'AAA - CH - Tank'")
    assert result is not None and result[1].marker == "AAA"
