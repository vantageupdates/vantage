"""The online P99 copy supplies passive, on-demand spell and item references."""
from pathlib import Path

import pytest

import vantage.helpers.mobile_share as mobile
from vantage.helpers.spell_library import (
    _wiki_title_from_url, _wiki_url, extract_acquisition_text,
    parse_class_skills_html, sanitize_wiki_html)
from vantage.helpers.wiki_source import parse_page


FIXTURES = Path(__file__).parent / "fixtures"


def article(name="wiki_mirror_spell_bravery.html"):
    return (FIXTURES / name).read_bytes()


class Response:
    def __init__(self, body, url="https://p99.funcamp.net/Bravery"):
        self.body = body
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        assert limit == mobile.MAX_WIKI_RESPONSE + 1
        return self.body[:limit]


def test_mirror_spell_description_effects_and_merchant_table():
    page = parse_page(article())
    rendered = page["parse"]["text"]["*"]
    detail = mobile.parse_mobile_spell_html(rendered)
    assert "hit points and armor class" in detail["description"]
    assert detail["effects"] == [
        "Increase AC by 9 (L24) to 10 (L30)",
        "Increase Max Hitpoints by 114 (L24) to 140 (L50)",
    ]
    assert "snapshot" in detail["source"]
    acquisition = extract_acquisition_text("", rendered)
    assert "WHERE TO OBTAIN" in acquisition
    assert "Ak'Anon · Clockwork Merchant (CG-3) · Cleric Guild" in acquisition
    assert "No research recipe is listed." in acquisition
    assert "Navigation" not in detail["description"]


def test_spell_cache_is_fetched_once_from_mirror(monkeypatch, tmp_path):
    calls = []
    def fetch(request, timeout):
        calls.append(request.full_url)
        assert timeout == 8
        return Response(article())
    monkeypatch.setattr(mobile, "urlopen", fetch)
    monkeypatch.setattr(mobile, "_mobile_spell_detail_path", lambda _: tmp_path / "spell.json")
    first = mobile.load_mobile_spell_detail("Bravery")
    assert mobile.load_mobile_spell_detail("Bravery") == first
    assert calls == ["https://p99.funcamp.net/Bravery"]


@pytest.mark.parametrize("body", [
    b"", b"<html><title>Just a moment...</title></html>",
    b'<h1 id="firstHeading">Bravery</h1><div id="mw-content-text"></div>',
    b'<h1 id="firstHeading">Bravery</h1><div id="mw-content-text"><script>attack()</script></div>',
    b"x" * (mobile.MAX_WIKI_RESPONSE + 1),
], ids=["empty", "challenge", "empty-article", "script-only", "oversize"])
def test_mobile_rejects_bad_articles_without_caching(monkeypatch, tmp_path, body):
    path = tmp_path / "spell.json"
    monkeypatch.setattr(mobile, "urlopen", lambda *_args, **_kwargs: Response(body))
    monkeypatch.setattr(mobile, "_mobile_spell_detail_path", lambda _: path)
    with pytest.raises(ValueError):
        mobile.load_mobile_spell_detail("Bravery")
    assert not path.exists()


def test_mobile_rejects_unexpected_redirect_source(monkeypatch):
    monkeypatch.setattr(mobile, "urlopen", lambda *_args, **_kwargs:
                        Response(article(), "https://unrelated.example/Bravery"))
    with pytest.raises(ValueError, match="unexpected source"):
        mobile._read_mobile_wiki_page("Bravery")


def test_cached_canonical_links_and_html_are_safe_mirror_links():
    safe = sanitize_wiki_html('''<script>bad()</script><iframe src="https://bad.example"></iframe>
        <img src="https://bad.example/track"><a href=javascript:bad() onclick=bad()>Bad</a>
        <a href="data:text/html,bad">Bad data</a><a href="//evil.example/x">Foreign</a>
        <a href="https://wiki.project1999.com/index.php?title=Skill_Abjuration">Skill</a>
        <a href="/Bravery" style="background:url(https://bad.example)">Bravery</a>''')
    assert "javascript:" not in safe and "data:" not in safe
    assert "evil.example" not in safe and "bad.example" not in safe
    assert "onclick" not in safe and "<img" not in safe
    assert 'href="https://p99.funcamp.net/Skill_Abjuration"' in safe
    assert _wiki_url("Bravery") == "https://p99.funcamp.net/Bravery"
    assert _wiki_title_from_url("https://p99.funcamp.net/Skill_Abjuration") == "Skill Abjuration"
    assert mobile._safe_p99_url("https://wiki.project1999.com/Bravery") == _wiki_url("Bravery")
    assert mobile._safe_p99_url("javascript:bad()", fallback_name="Bravery") == _wiki_url("Bravery")


def test_class_skills_keep_mirror_targets():
    result = parse_class_skills_html('''<h1><span id="Skills">Skills</span></h1>
        <h2><span id="Casting_Skills">Casting Skills</span></h2>
        <table><tr><th>Level</th><th>Trained</th><th>Skill</th><th>Cap Until 50</th><th>Cap Above 50</th></tr>
        <tr><td>4</td><td>Yes</td><td><a href="https://p99.funcamp.net/Skill_Meditate">Meditate</a></td><td>235</td><td>252</td></tr></table>''', "Enchanter")
    assert result["skills"][0]["target"] == "Skill Meditate"


def test_mirror_mobile_weapon_preserves_dmg_delay_and_existing_price(monkeypatch, tmp_path):
    monkeypatch.setattr(mobile, "urlopen", lambda *_args, **_kwargs:
                        Response(article("wiki_mirror_item_boneshear_mobile.html"), "https://p99.funcamp.net/Boneshear"))
    monkeypatch.setattr(mobile, "_mobile_item_detail_path", lambda _: tmp_path / "item.json")
    detail = mobile.load_mobile_item_detail({"name": "Boneshear", "price": 500, "stats": {"ac": 3}})
    assert detail["status"] == "complete"
    assert detail["stats"]["dmg"] == 9
    assert detail["stats"]["dly"] == 20
    assert detail["stats"]["ac"] == 3
    assert detail["price"] == 500
    assert detail["wiki_url"] == "https://p99.funcamp.net/Boneshear"
    assert "snapshot" in detail["source"]
