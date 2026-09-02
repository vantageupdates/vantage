import datetime
import xml.etree.ElementTree as ET

from vantage.helpers.combat import AttackerStats, Encounter, TankStats
from vantage.helpers.combat_exports import (
    bbcode_table, compact_number, detailed_plain_text, eq_summary_lines,
    html_report, xml_report)


def sample_encounter():
    started = datetime.datetime(2026, 8, 30, 12, 0, 0)
    encounter = Encounter(
        "A Crystalline Devourer", started,
        started + datetime.timedelta(seconds=120), zone="Velketor")
    encounter.touch_damage(started)
    encounter.touch_damage(started + datetime.timedelta(seconds=119))
    alice = AttackerStats("Alice")
    alice.add(750_000, "Slashing", started)
    alice.add(250_000, "Kick", started + datetime.timedelta(seconds=99),
              critical=True)
    alice.miss(started + datetime.timedelta(seconds=100))
    bob = AttackerStats("Bob")
    bob.add(500_000, "Direct Damage", started + datetime.timedelta(seconds=30))
    bob.add(100_000, "Direct Damage", started + datetime.timedelta(seconds=89))
    encounter.attackers = {"Alice": alice, "Bob": bob}
    alice_tank = TankStats("Alice")
    alice_tank.hit(12_000)
    encounter.tanks["Alice"] = alice_tank
    return encounter, alice, bob


def test_eq_summary_uses_configured_fields_top_players_and_safe_splitting():
    encounter, alice, bob = sample_encounter()
    options = {
        "output_channel": "/gu", "separator": " | ", "top_players": 1,
        "show_opponent": True, "show_damage": True,
        "show_percentage": True, "show_dps": True, "show_sdps": True,
        "append_dps_label": True,
    }
    lines = eq_summary_lines(encounter, [alice, bob], options, max_chars=120)

    assert all(line.startswith("/gu ") for line in lines)
    assert all(len(line) <= 120 for line in lines)
    combined = " ".join(lines)
    assert "A Crystalline Devourer in 120s" in combined
    assert "DMG 1.6m" in combined
    assert "#1 Alice" in combined
    assert "Bob" not in combined
    assert "dps" in combined and "sdps" in combined


def test_detailed_text_matches_familiar_gamparse_shape_without_fake_metrics():
    encounter, alice, bob = sample_encounter()
    text = detailed_plain_text(encounter, [alice, bob], {
        "plain_show_type": True,
        "plain_show_crit": True,
        "plain_show_accuracy": True,
    }, version="1.14.0")

    assert "A Crystalline Devourer on 2026-08-30 in 120sec" in text
    assert "--- DMG: 1600000" in text
    assert "------ Total: 1000000 -- Slashing: 750000 -- Kick: 250000" in text
    assert "------ Critical hits: 1 -- Normal hits: 1" in text
    assert "------ Attempts: 3 -- Hits: 2 -- Misses: 1" in text
    assert "--- DMG to PC: 12000 @100dps" in text
    assert text.endswith("Produced by Vantage v1.14.0")


def test_forum_html_and_xml_formats_are_structured_and_escape_content():
    headers = ["Player", "Damage"]
    rows = [["Alice [Main]", "1,000,000"], ["Bob & Pet", "600,000"]]
    bbcode = bbcode_table("Fight [One]", "Summary", headers, rows)
    assert "[b]Fight (One)[/b]" in bbcode
    assert "[td]Alice (Main)[/td]" in bbcode

    html = html_report(
        "Fight <One>", "Damage & time", [("Overview", headers, rows)],
        {"html_theme": "slate", "html_font_size": "medium"})
    assert "<!doctype html>" in html
    assert "Fight &lt;One&gt;" in html
    assert "Bob &amp; Pet" in html
    assert "font-size:14px" in html

    xml = xml_report(
        "Fight <One>", "Damage & time", [("Overview", headers, rows)])
    root = ET.fromstring(xml)
    assert root.tag == "vantage-combat-report"
    assert root.findtext("title") == "Fight <One>"
    assert root.find("section/row/field").attrib["name"] == "Player"


def test_compact_numbers_do_not_drop_integer_zeroes():
    assert compact_number(100_000) == "100k"
    assert compact_number(1_000_000) == "1m"
    assert compact_number(1_250_000) == "1.2m"
