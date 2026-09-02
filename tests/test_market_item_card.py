import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from vantage.parsers.market import (
    MarketModel, combined_market_price, parse_wiki_entity_wikitext,
    parse_wiki_green_auction_html, parse_wiki_item_wikitext)


WIKI_ITEM = """
{{Itembox
|itemname    = Fungus Covered Scale Tunic
|lucy_img_ID = 678
|statsblock  =
LORE ITEM<br>
Slot: CHEST<br>
AC: 21<br>
Effect: [[Fungal Regrowth]] (Worn)<br>
Class: WAR CLR PAL RNG SHD DRU MNK BRD ROG SHM<br>
Race: ALL<br>
|dropsfrom =

[[Old Sebilis]]

* [[Myconid Spore King]]
}}
"""

WIKI_AUCTION_HTML = """
<div id="auc_Green" class="auctrackerbox">
<table class="eoTable3"><tr><th>30d Avg</th></tr><tr>
<td> 933 &#177; 47 </td><td> 928 &#177; 69 </td>
<td> 3629 &#177; 2996 </td><td> 1 / 13000 </td><td> 2653 </td>
</tr></table>
<table class="eoTable"><tr><th>Date</th><th>Seller</th><th>Price</th></tr>
<tr><td>2026-08-02</td><td>Donkay</td><td>1000</td>
<td>2026-08-01</td><td>Mulebard</td><td>900</td></tr>
<tr><td>2026-07-31</td><td>Zylmart</td><td>900</td>
<td>2026-07-13</td><td>Kanelgiffel</td><td>900</td></tr>
<tr><td>2026-07-06</td><td>Arotti</td><td>900</td>
<td>2026-06-09</td><td>Mourned</td><td>777</td></tr>
</table></div><div id="auc_Teal"></div>
"""


def test_wiki_itembox_is_converted_to_native_card_data():
    item = parse_wiki_item_wikitext(WIKI_ITEM)

    assert item["name"] == "Fungus Covered Scale Tunic"
    assert item["image"] == "Item_678.png"
    assert "Slot: CHEST" in item["stats"]
    assert "Fungal Regrowth (Worn)" in item["stats"]
    assert "[[" not in item["stats"]
    assert "<br>" not in item["stats"]
    assert item["drops"] == [{
        "npc": "Myconid Spore King",
        "npc_url": "https://wiki.project1999.com/Myconid_Spore_King",
        "npc_target": "Myconid Spore King",
        "zone": "Old Sebilis",
        "zone_url": "https://wiki.project1999.com/Old_Sebilis",
        "zone_target": "Old Sebilis",
    }]


def test_wiki_drop_parser_keeps_multiple_zone_relationships():
    source = """{{Itempage
|itemname = Bone Chips
|dropsfrom =
Various Zones
* Many skeleton types
[[Najena]]
* [[a skeleton|A skeleton]]
}}"""

    drops = parse_wiki_item_wikitext(source)["drops"]

    assert drops[0]["npc"] == "Many skeleton types"
    assert drops[0]["zone"] == "Various Zones"
    assert drops[1]["npc"] == "A skeleton"
    assert drops[1]["zone"] == "Najena"


def test_native_npc_summary_extracts_useful_drop_details():
    source = """{{Namedmobpage
| name = myconid spore king
| race = [[Fungusman]]
| class = [[Paladin]]
| level = 56
| zone = [[Old Sebilis]]
| location = 3%? @ (-910, 109)
| HP = 17750
| damage_per_hit = 132 - 330
| description = Drops several sought-after regenerative items.
}}"""

    entity = parse_wiki_entity_wikitext(
        source, "Myconid Spore King", "npc")

    assert entity["name"] == "myconid spore king"
    assert ("Zone", "Old Sebilis") in entity["facts"]
    assert ("Location", "3%? @ (-910, 109)") in entity["facts"]
    assert "regenerative" in entity["summary"]


def test_native_zone_summary_stays_inside_the_app():
    source = """{{Kunark Era}}
'''Sebilis''' is the vast, ancient capital of the [[Iksar]] Empire.
{| class="zoneTopTable"
! ''' Level of Monsters: '''
|48-60
|}"""

    entity = parse_wiki_entity_wikitext(source, "Old Sebilis", "zone")

    assert entity["name"] == "Old Sebilis"
    assert "ancient capital" in entity["summary"]
    assert entity["facts"] == [("Enemy levels", "48-60")]


def test_market_item_name_looks_and_behaves_like_a_link():
    model = MarketModel()
    model.set_items([{"n": "Fungus Covered Scale Tunic", "t": 0}])
    index = model.index(0, 0)

    assert "Open the compact item card" in model.data(
        index, Qt.ItemDataRole.ToolTipRole)
    assert model.data(index, Qt.ItemDataRole.ForegroundRole).isValid()
    assert model.data(index, Qt.ItemDataRole.FontRole).underline()


def test_green_wiki_auction_prices_are_extracted_without_all_time_pollution():
    auction = parse_wiki_green_auction_html(WIKI_AUCTION_HTML)

    assert auction["avg_30"] == 933
    assert auction["avg_90"] == 928
    assert auction["all_time_avg"] == 3629
    assert auction["seen"] == 2653
    assert auction["reference"] == 933
    assert auction["reference_period"] == "30d"
    assert auction["recent_median"] == 900
    assert auction["last_date"] == "2026-08-02"


def test_pig_and_wiki_are_averaged_only_when_close():
    auction = {"reference": 933}
    close = combined_market_price({"a30": 900}, auction)
    far = combined_market_price({"a30": 4000}, auction)

    assert close["close"] is True
    assert close["combined"] == 916
    assert far["close"] is False
    assert far["combined"] == 0
