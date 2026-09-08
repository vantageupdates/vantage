import base64
import copy
import json

from vantage.helpers import config
from vantage.helpers.opendkp import (
    auction_bids, auction_id, auction_item_name, decode_token_username,
    normalize_guild_slug, rows_from_payload, watch_matches)


def test_generic_guild_normalization_accepts_slug_or_opendkp_address_only():
    assert normalize_guild_slug("dragon-guild") == "dragon-guild"
    assert normalize_guild_slug("https://Dragon-Guild.OpenDKP.com/#/bids") == "dragon-guild"
    assert normalize_guild_slug("dragon-guild.opendkp.com") == "dragon-guild"
    assert normalize_guild_slug("https://example.com/dragon-guild") == ""
    assert normalize_guild_slug("bad guild") == ""
    assert normalize_guild_slug("-bad-") == ""


def test_payload_and_auction_helpers_support_current_and_legacy_shapes():
    row = {"Id": "42", "Item": {"Name": " Cloak   of Flames "},
           "bids": [{"CharacterId": 7, "Value": 50}]}
    assert rows_from_payload({"Models": [row]}, "Models") == [row]
    assert rows_from_payload([row], "Models") == [row]
    assert auction_id(row) == 42
    assert auction_item_name(row) == "Cloak of Flames"
    assert auction_bids(row) == row["bids"]
    assert watch_matches(row, ["cloak", "manastone"]) == ["cloak"]


def test_token_username_decode_never_requires_or_exposes_a_secret():
    encoded = base64.urlsafe_b64encode(json.dumps(
        {"cognito:username": "RaiderOne"}).encode()).decode().rstrip("=")
    assert decode_token_username(f"ignored.{encoded}.signature") == "RaiderOne"
    assert decode_token_username("not-a-token") == ""


def test_opendkp_profiles_are_bounded_generic_and_never_store_passwords():
    original = copy.deepcopy(config.data)
    try:
        config.data = {"opendkp": {"active_guild": "GUILD-ONE", "guilds": [{
            "slug": "GUILD-ONE", "name": " Any Guild ",
            "character_id": "25", "character_name": " A Character ",
            "username": " Account ", "password": "must-not-survive",
            "watch_items": [" Cloak  of Flames ", "cloak of flames", "Manastone"],
        }, {"slug": "bad guild"}]}}
        config.verify_settings()
        assert config.data["opendkp"]["active_guild"] == "guild-one"
        assert config.data["opendkp"]["guilds"] == [{
            "slug": "guild-one", "name": "Any Guild",
            "url": "https://guild-one.opendkp.com",
            "character_id": 25, "character_name": "A Character",
            "username": "Account",
            "watch_items": ["Cloak of Flames", "Manastone"],
        }]
        assert "password" not in json.dumps(config.data["opendkp"]).casefold()
    finally:
        config.data = original


def test_quickbar_catalog_exposes_one_generic_opendkp_window():
    from vantage.helpers.quickbar_items import QUICKBAR_ITEMS
    matches = [item for item in QUICKBAR_ITEMS if item[0] == "opendkp"]
    assert matches == [
        ("opendkp", "OpenDKP · DKP & Bids", "ph-gavel", "windows")]

