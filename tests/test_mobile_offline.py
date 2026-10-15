"""Adversarial checks for the portable private-data export boundary."""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import vantage.helpers.mobile_offline as offline


def test_projection_removes_secrets_recursively_and_preserves_full_guild_roster():
    secret = "NEVER-EXPORT-THIS-SECRET"
    source = {
        "lan_token": secret, "password": secret, "log_path": secret,
        "game": {"frame": secret}, "buffs": {"timers": [secret]},
        "guild": {
            "guild": "Castle", "slug": "castle", "token": secret,
            "authenticated": True, "profiles": [{"password": secret}],
            "standings": [{"name": f"Character {index:04}", "dkp": 42,
                           "token": secret, "private": {"password": secret}}
                          for index in range(625)],
            "loot": [{"item": "Jade Mace", "wiki_url": "javascript:" + secret}],
            "raids": [{"name": "Test raid", "raw": secret}],
            "auctions": [{"item": secret}],
            "sheets": [{"name": "Roster", "url":
                        "https://docs.google.com/spreadsheets/d/abc1234567890/edit?resourcekey="
                        + secret + "#gid=123"}],
        },
        "zones": {"data": {
            "name": "West Commonlands", "map_image": secret,
            "mobs": [{"name": "Kizdean Gix", "named": True, "log": secret}],
            "unique_items": ["Dragoon Dirk", {"password": secret}],
        }},
        "quests": {"current": {
            "title": "Jboots", "summary": "Find the boots.", "raw_html": secret,
            "metadata": {"Classes": "All", "password": secret},
            "steps": [{"text": "Hail Hasten", "kind": "action", "token": secret}],
        }},
    }
    output = offline.build_offline_snapshot(
        source, source_version="1.2.3", exported_at=datetime(2026, 10, 15, tzinfo=timezone.utc))
    serialized = json.dumps(output)
    assert secret not in serialized
    assert set(output) == {"format", "schema", "exported_at", "source_version",
                           "guild", "zone", "quest", "truncated"}
    assert output["exported_at"] == "2026-10-15T00:00:00+00:00"
    assert output["source_version"] == "1.2.3"
    assert len(output["guild"]["standings"]) == 625
    assert output["guild"]["standings"][-1]["name"] == "Character 0624"
    assert output["guild"]["standings_total"] == 625
    assert output["guild"]["loot"][0]["wiki_url"] == "https://wiki.project1999.com/Jade_Mace"
    assert output["guild"]["sheets"][0]["url"] == (
        "https://docs.google.com/spreadsheets/d/abc1234567890/edit")
    assert output["zone"]["unique_items"] == ["Dragoon Dirk"]
    assert output["quest"]["metadata"] == {"Classes": "All"}
    assert output["truncated"] == []


def test_sheet_export_rejects_active_urls_credentials_and_published_bearer_links():
    urls = [
        "javascript:alert(1)", "data:text/html,secret", "file:///C:/secret",
        "http://docs.google.com/spreadsheets/d/abc1234567890/edit",
        "https://docs.google.com.evil.test/spreadsheets/d/abc1234567890/edit",
        "https://user:password@docs.google.com/spreadsheets/d/abc1234567890/edit",
        "https://docs.google.com:444/spreadsheets/d/abc1234567890/edit",
        "https://docs.google.com/spreadsheets/d/e/published-secret/pubhtml",
        "https://evil.test/secret", "https://[broken",
    ]
    result = offline.build_offline_snapshot({"guild": {
        "guild": "Castle", "sheets": [{"name": "Bad", "url": url} for url in urls]}})
    assert result["guild"]["sheets"] == []


def test_empty_and_malformed_sections_do_not_become_stringified_private_state():
    result = offline.build_offline_snapshot({
        "guild": {"guild": {"password": "secret"}},
        "zones": {"data": ["secret"]}, "quests": None})
    assert result["guild"] is None
    assert result["zone"] is None
    assert result["quest"] is None
    loading = offline.build_offline_snapshot({"guild": {
        "guild": "Castle", "loading": True, "standings": "private blob"}})
    assert loading["guild"]["name"] == "Castle"
    assert loading["guild"]["standings"] == []
    assert loading["guild"]["standings_total"] == 0


def test_count_and_text_limits_are_explicit_without_250_character_cutoff():
    result = offline.build_offline_snapshot({
        "guild": {"guild": "G" * 1000,
                  "standings": [{"name": str(index), "rank": "R" * 1000}
                                for index in range(10001)],
                  "loot": [{"item": "Item"}] * 501},
        "zones": {"data": {"name": "Zone", "unique_items": ["Item"] * 2001}},
        "quests": {"current": {"title": "Quest", "steps": [{"text": "A" * 10000}] * 181}},
    })
    assert len(result["guild"]["name"]) == 160
    assert len(result["guild"]["standings"]) == 10000
    assert result["guild"]["standings_total"] == 10001
    assert len(result["guild"]["standings"][0]["rank"]) == 96
    assert len(result["guild"]["loot"]) == 500
    assert len(result["zone"]["unique_items"]) == 2000
    assert len(result["quest"]["steps"]) == 180
    assert len(result["quest"]["steps"][0]["text"]) == 4000
    assert set(result["truncated"]) == {
        "guild.standings", "guild.loot", "zone.unique_items", "quest.steps"}


def test_final_utf8_byte_budget_keeps_valid_json_and_signals_omissions(monkeypatch):
    assert offline.MAX_EXPORT_BYTES == 8 * 1024 * 1024
    monkeypatch.setattr(offline, "MAX_EXPORT_BYTES", 12000)
    source = {"guild": {"guild": "Castle", "standings": [
        {"name": "😀" * 160, "rank": "😀" * 96} for _ in range(1000)]}}
    encoded = offline.encode_offline_snapshot(source)
    assert len(encoded) <= 12000
    result = json.loads(encoded)
    assert result["guild"]["standings_total"] == 1000
    assert 0 < len(result["guild"]["standings"]) < 1000
    assert "guild.standings" in result["truncated"]


def test_quest_checkmarks_are_projected_to_indices_only_for_matching_title():
    step = "Hail Hasten"
    key = hashlib.sha256(step.casefold().encode()).hexdigest()[:16]
    source = {"quests": {
        "current": {"title": "Jboots", "steps": [
            {"text": "Preparation", "kind": "group"}, {"text": step}]},
        "checklist": {"title": "Jboots", "checked": [key, "not-a-step-key"]},
    }}
    result = offline.build_offline_snapshot(source)
    assert result["quest"]["checked"] == [1]
    assert key not in json.dumps(result)
    source["quests"]["checklist"]["title"] = "Different quest"
    assert offline.build_offline_snapshot(source)["quest"]["checked"] == []


def test_public_reference_builder_only_exports_bundled_names_and_wiki_links(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("offline_reference_builder", root / "companion-web/build_data.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for kind, filename, minimum in (("zones", "zone_catalog.json", 50),
                                    ("quests", "quest_catalog.json", 200)):
        rows = builder.load_reference_index(root / "data/reference" / filename, kind)
        assert len(rows) > minimum
        assert all(set(row) == {"name", "wiki"} for row in rows)
        assert all(row["wiki"].startswith("https://wiki.project1999.com/") for row in rows)
    malicious = tmp_path / "zones.json"
    malicious.write_text(json.dumps({"zones": [{"name": "The Zone", "map": "private-path", "wiki": "javascript:bad"}]}))
    assert builder.load_reference_index(malicious, "zones") == [
        {"name": "The Zone", "wiki": "https://wiki.project1999.com/The_Zone"}]


def test_catalog_builder_explicitly_closes_sqlite_before_temporary_cleanup(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("offline_closure_builder", root / "companion-web/build_data.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    events = []

    class Database:
        def execute(self, query):
            events.append("query")
            return self

        def fetchall(self):
            return []

        def close(self):
            events.append("closed")

    monkeypatch.setattr(builder.sqlite3, "connect", lambda path: Database())
    assert builder.load_items(tmp_path / "catalog.sqlite", [], tmp_path / "missing-eras.json") == []
    assert events == ["query", "closed"]
