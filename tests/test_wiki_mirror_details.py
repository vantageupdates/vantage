"""Small authored fixtures exercise the mirror's real template structures."""

import pytest

from vantage.helpers.wiki_source import parse_page
from vantage.helpers.wiki_mirror_details import (
    parse_item_html, parse_entity_html, parse_zone_html)
from vantage.parsers.market import combined_market_price, parse_wiki_item_wikitext
from vantage.parsers.quests import parse_quest_html, parse_quest_catalog_payload
from vantage.parsers.zones import known_mob_matches


ITEM = '''<div class="hbdiv">Other Item<span class="hb"><div class="itemtitle">Wrong</div>
<div class="itemdata">DMG: 999<br>Delay: 999</div></span></div>
<div class="itemtitle">Example Spear</div><div class="itemdata">
<div class="itemicon"><img src="/images/Item_591.png"></div>
MAGIC ITEM<br>Skill: Piercing Atk Delay: 20<br>DMG: 9 AC: 5<br>MANA: +25<br>
Effect: <a href="/Example_Burst_(Spell)">Example Burst</a> (Combat)<br>Class: NEC</div>
<h2>Drops From</h2><p><a href="/Example_Zone">Example Zone</a></p>
<ul><li><a href="https://p99.funcamp.net/Example_Foreman">Example Foreman</a></li></ul>
<h2>Related quests</h2><ul><li><a href="/Example_Quest">Example Quest</a></li></ul>'''


def test_item_html_primary_stats_effect_link_and_source_relationships():
    item = parse_item_html(ITEM, "Example Spear")
    assert item["name"] == "Example Spear"
    assert item["numeric_stats"] == {"dmg": 9, "dly": 20, "ac": 5, "mana": 25}
    assert item["effects"][0]["target"] == "Example Burst (Spell)"
    assert item["drops"][0]["npc"] == "Example Foreman"
    assert item["drops"][0]["zone"] == "Example Zone"
    assert item["image"] == "Item_591.png"
    assert item["related_quests"][0]["name"] == "Example Quest"
    assert parse_wiki_item_wikitext("", "Example Spear", ITEM) == item


def test_non_item_page_does_not_succeed_from_embedded_tooltip():
    with pytest.raises(ValueError, match="stat block"):
        parse_item_html('<span class="hb"><div class="itemdata">DMG: 99</div></span>')


def test_npc_html_reads_only_loot_links_and_facts():
    npc = parse_entity_html('''<table class="mobStatsBox"><tr><th>Example Guard</th></tr>
    <tr><td><b>Race:</b> Sarnak</td></tr><tr><td><b>Level:</b> 51</td></tr>
    <tr><td><b>Zone:</b><a href="/Example_Zone">Example Zone</a></td></tr></table>
    <h3>Description</h3><p>Guards the gate.</p><h3>Known Loot</h3><ul><li>
    <div class="hbdiv"><a href="/Example_Spear">Example Spear</a><span class="hb">
    Effect: <a href="/Wrong_Spell">Wrong Spell</a></span></div></li></ul>
    <h3>Related Quests</h3><a href="/Example_Quest">Example Quest</a>''')
    assert dict(npc["facts"])["Level"] == "51"
    assert dict(npc["facts"])["Zone"] == "Example Zone"
    assert npc["drops"] == ["Example Spear"]
    assert npc["related_quests"][0]["target"] == "Example Quest"


def test_zone_html_semantic_npc_table_and_notables():
    zone = parse_zone_html('''<p>A mountain stronghold.</p><table>
    <tr><th>Level of Monsters:</th><td>40-50</td></tr>
    <tr><th>Notable NPCs:</th><td><a href="/Example_Guard">Example Guard</a></td></tr>
    <tr><th>Unique Items:</th><td><a href="/Example_Spear">Example Spear</a>
    <span class="hb">DMG: 99 <a href="/Wrong_Spell">Wrong Spell</a></span></td></tr></table>
    <h2>What's in this zone?</h2><table><tr><th>Quest</th><th>Level</th></tr>
    <tr><td>False NPC</td><td>99</td></tr></table>
    <table class="eoTable3 sortable"><tr><th>NPC Name</th><th>Race</th><th>Class</th>
    <th>Level</th><th>Location</th><th>Known Loot</th><th>Description</th></tr>
    <tr><td><a href="https://p99.funcamp.net/Example_Guard">Example Guard</a></td>
    <td>Sarnak</td><td>Warrior</td><td>50</td><td>1, 2</td><td><a href="/Example_Spear">Example Spear</a>
    <span class="hb"><a href="/Wrong_Spell">Wrong Spell</a></span></td><td>Guards.</td></tr></table>''', "Example Zone")
    assert zone["levels"] == "40-50"
    assert zone["summary"] == "A mountain stronghold."
    assert zone["unique_items"] == ["Example Spear"]
    assert len(zone["mobs"]) == 1
    assert zone["mobs"][0]["named"] is True
    assert zone["mobs"][0]["target"] == "Example Guard"
    assert zone["mobs"][0]["drops"] == ["Example Spear"]


def test_quest_html_preserves_dd_hierarchy_coordinates_and_ignores_tooltips():
    quest = parse_quest_html('''<div id="toc"><ul><li>Give a fake menu item</li></ul></div>
    <table><tr><td>Start Zone:</td><td>Example Woods</td></tr></table>
    <h2>Rewards</h2><ul><li><a href="/Example_Blade">Example Blade</a>
    <span class="hb">Cast Fake Spell<br>DMG: 50</span></li></ul>
    <h2>Checklist</h2><div class="checkbox-list"><ul><li>Forage the following items</li></ul>
    <dl><dd><ul><li>Frozen Root from Example Peaks at (-120, 250).</li>
    <li>Give the root to Example Druid and say "I will help".</li></ul></dd></dl>
    <ul><li>Return to the grove with the reward.</li></ul></div>
    <h2>Unrelated lore</h2><p>Kill the excluded monster.</p>''', "Example Quest")
    assert quest["rewards"] == ["Example Blade"]
    assert quest["metadata"]["Start Zone"] == "Example Woods"
    actions = [step for step in quest["steps"] if step["kind"] == "action"]
    assert len(actions) == 3
    assert actions[0]["text"] == "Forage Frozen Root from Example Peaks at (-120, 250)."
    assert actions[0]["depth"] == 1
    assert actions[0]["group"] == "Forage the following items"
    assert 'say "I will help"' in actions[1]["text"]
    assert "excluded" not in str(quest)


def test_effect_html_reads_four_cell_metadata_and_numbered_effects():
    data = parse_entity_html('''<h2>Details</h2><table><tr><td>1 :</td><td>Increase AC by 10</td></tr></table>
    <table><tr><td>Mana</td><td>70</td><td>Skill</td><td>Abjuration</td></tr>
    <tr><td>Spell Type</td><td>Beneficial</td><td>Duration</td><td>45 minutes</td></tr></table>''', "Example Courage", "effect")
    assert dict(data["facts"])["Mana"] == "70"
    assert dict(data["facts"])["Duration"] == "45 minutes"
    assert "Increase AC by 10" in data["summary"]


def test_catalog_reads_only_category_members_and_safe_continuation():
    raw = '''<h1 id="firstHeading">Category:Quests</h1><div id="mw-content-text">
    <a href="/Unrelated">Unrelated</a><div id="mw-pages"><a href="/index.php_title=Category:Quests&amp;pagefrom=Next#mw-pages">next 200</a>
    <ul><li><a href="/Example_Quest">Example Quest</a></li></ul></div></div>'''
    titles, continuation = parse_quest_catalog_payload(parse_page(raw))
    assert titles == ["Example Quest"]
    assert continuation == "https://p99.funcamp.net/index.php_title=Category:Quests&pagefrom=Next"


def test_known_mob_search_merges_loaded_details_without_claiming_complete_search():
    row = {"name": "Example Guard", "drops": ["Example Spear"], "level": "50"}
    assert known_mob_matches("Example Guard", [row]) == [row]


def test_archive_price_is_never_combined_with_current_market_signal():
    comparison = combined_market_price({"a30": 100}, {"reference": 100, "archived": True})
    assert comparison["wiki"] == 100
    assert comparison["combined"] == 0
    assert comparison["close"] is False
