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
    assert output["guild"]["loot"][0]["wiki_url"] == "https://p99.funcamp.net/Jade_Mace"
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
                  "loot": [{"item": "Item"}] * 1001},
        "zones": {"data": {"name": "Zone", "unique_items": ["Item"] * 2001}},
        "quests": {"current": {"title": "Quest", "steps": [{"text": "A" * 10000}] * 181}},
    })
    assert len(result["guild"]["name"]) == 160
    assert len(result["guild"]["standings"]) == 10000
    assert result["guild"]["standings_total"] == 10001
    assert len(result["guild"]["standings"][0]["rank"]) == 96
    assert len(result["guild"]["loot"]) == 1001
    assert len(result["zone"]["unique_items"]) == 2000
    assert len(result["quest"]["steps"]) == 180
    assert len(result["quest"]["steps"][0]["text"]) == 4000
    assert set(result["truncated"]) == {
        "guild.standings", "zone.unique_items", "quest.steps"}


def test_full_guild_loot_above_500_survives_export_and_phone_import():
    from tests.test_companion_pwa import run_javascript

    result = offline.build_offline_snapshot({"guild": {
        "guild": "Synthetic guild", "loot": [
            {"item": "Repeated purchase", "character": f"Character {index}",
             "dkp": index, "private": "never export", "wiki_url": "javascript:bad"}
            for index in range(1203)]}})
    assert len(result["guild"]["loot"]) == 1203
    assert result["truncated"] == []
    encoded = json.dumps(result)
    assert "never export" not in encoded and "javascript:" not in encoded
    run_javascript("""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={window:{},URL,TextEncoder};vm.createContext(context);
vm.runInContext(fs.readFileSync('companion-web/offline.js','utf8'),context);
const api=context.window.VantageOffline;
const fixture=""" + encoded + """;
const clean=api.snapshot(fixture);
assert.equal(clean.guild.loot.length,1203);
assert.equal(clean.guild.loot[1202].character,'Character 1202');
assert.equal(clean.guild.loot[1202].dkp,'1202');
assert.throws(()=>api.snapshot({...fixture,extra:'x'.repeat(api.MAX_BYTES)}),/8 MiB/);
assert.throws(()=>api.snapshot({...fixture,guild:{...fixture.guild,loot:Array(200000).fill({})}}));
""")


def test_loot_is_limited_by_utf8_budget_not_first_page(monkeypatch):
    monkeypatch.setattr(offline, "MAX_EXPORT_BYTES", 300_000)
    result = offline.build_offline_snapshot({"guild": {
        "guild": "Synthetic guild", "loot": [
            {"item": "Repeated purchase", "character": str(index)}
            for index in range(10000)]}})
    assert 500 < len(result["guild"]["loot"]) < 10000
    assert result["truncated"] == ["guild.loot"]
    assert len(offline._encode(result)) <= 300_000


def test_unfinished_loot_is_explicitly_omitted_without_losing_other_sections():
    from tests.test_companion_pwa import run_javascript

    snapshots = []
    for status, provisional in (("preparing", []), ("failed", []),
                                ("loading", [{"item": "Partial purchase"}])):
        result = offline.build_offline_snapshot({
            "guild": {"guild": "Synthetic guild", "loot": provisional,
                      "loot_complete": False, "loot_status": status,
                      "standings": [{"name": "Synthetic character", "dkp": 0}]},
            "zones": {"data": {"name": "Synthetic zone"}}})
        assert result["guild"]["loot"] == []
        assert result["guild"]["standings"][0]["dkp"] == "0"
        assert result["zone"]["name"] == "Synthetic zone"
        assert len(result["truncated"]) == 1
        assert "guild.loot" in result["truncated"][0]
        assert "not yet complete" in result["truncated"][0]
        snapshots.append(result)
    run_javascript("""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const context={window:{},URL,TextEncoder};vm.createContext(context);
vm.runInContext(fs.readFileSync('companion-web/offline.js','utf8'),context);
for(const fixture of """ + json.dumps(snapshots) + """) {
 const imported=context.window.VantageOffline.snapshot(fixture);
 assert.equal(imported.guild.loot.length,0);
 assert.equal(imported.truncated[0],fixture.truncated[0]);
 assert.equal(imported.zone.name,'Synthetic zone');
}
""")


def test_previous_complete_and_genuinely_empty_loot_remain_valid_during_refresh():
    for status in ("loading", "failed"):
        for purchases in ([], [{"item": "Previous complete purchase"}]):
            result = offline.build_offline_snapshot({"guild": {
                "guild": "Synthetic guild", "loot": purchases,
                "loot_complete": True, "loot_status": status}})
            assert len(result["guild"]["loot"]) == len(purchases)
            assert result["truncated"] == []


def test_phone_saved_loot_warning_persists_without_changing_row_or_focus_order():
    from tests.test_companion_pwa import run_javascript

    run_javascript(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const elements={'guild-results':{replaceChildren(...rows){this.children=rows}},
 'guild-view':{value:'loot'},'guild-search':{value:''},'guild-more':{hidden:true}};
let status='';
const state={guildLimit:100,snapshot:{truncated:['guild.loot (not yet complete)'],guild:{loot:[],standings:[]}}};
const context={state,$:id=>elements[id],norm:value=>value.toLowerCase(),number:String,
 resultCount:(id,section,text)=>{assert.equal(id,'guild-count');status=text},
 node:(tag,style,text)=>({tag,text,children:[],append(...rows){this.children.push(...rows)}}),appendLink:()=>{}};
vm.createContext(context);
const source=fs.readFileSync('companion-web/app.js','utf8');
vm.runInContext(source.slice(source.indexOf('function renderGuild('),source.indexOf('function referenceRows(')),context);
context.renderGuild();
assert(status.includes('0 matching saved records')&&status.includes('incomplete'));
assert(status.includes('import a new copy'));
assert(!status.includes('guild.loot'));
state.snapshot.guild.loot=Array.from({length:1203},(_,index)=>({item:'Purchase '+index}));
context.renderGuild();
assert(status.includes('1203 matching saved records')&&status.includes('incomplete'));
assert.equal(elements['guild-results'].children.length,100);
assert.equal(elements['guild-results'].children[99].children[0].text,'Purchase 99');
assert.equal(elements['guild-more'].hidden,false);
state.guildLimit=200;context.renderGuild();
assert.equal(elements['guild-results'].children[100].children[0].text,'Purchase 100');
elements['guild-view'].value='standings';context.renderGuild();assert(!status.includes('incomplete'));
elements['guild-view'].value='loot';state.snapshot.truncated=[];state.snapshot.guild.loot=[];
context.renderGuild();assert(!status.includes('incomplete'));assert(status.includes('0 matching saved records'));
""")


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
        assert all(row["wiki"].startswith("https://p99.funcamp.net/") for row in rows)
    malicious = tmp_path / "zones.json"
    malicious.write_text(json.dumps({"zones": [{"name": "The Zone", "map": "private-path", "wiki": "javascript:bad"}]}))
    assert builder.load_reference_index(malicious, "zones") == [
        {"name": "The Zone", "wiki": "https://p99.funcamp.net/The_Zone"}]


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
