import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QToolButton

from vantage.helpers.spell_catalog import p99_spell_entries
from vantage.helpers.spell_library import (
    SpellLibraryDialog, SpellLibraryFilter, SpellLibraryModel,
    _cache_path, _wiki_title_from_url, extract_acquisition_text,
    parse_class_skills_html, sanitize_wiki_html)
from vantage.parsers.market import GreenMarket


def _app():
    return QApplication.instance() or QApplication([])


def test_bundled_spell_catalog_has_exact_p99_class_levels():
    entries = p99_spell_entries()
    assert len(entries) > 1100
    by_name = {entry.name: entry for entry in entries}
    assert by_name["Clarity"].class_levels == (("Enchanter", 29),)
    assert by_name["Torpor"].class_levels == (("Shaman", 60),)
    assert by_name["Aegolism"].class_levels == (("Cleric", 60),)
    assert by_name["Enstill"].level_for("Wizard") == 20
    assert by_name["Enstill"].level_for("Cleric") == 29


def test_spell_filter_combines_name_class_and_exact_level():
    _app()
    model = SpellLibraryModel(p99_spell_entries())
    proxy = SpellLibraryFilter()
    proxy.setSourceModel(model)
    proxy.set_filters("clar", "Enchanter", 29)
    names = {
        model.listings[
            proxy.mapToSource(proxy.index(row, 0)).row()].entry.name
        for row in range(proxy.rowCount())}
    assert "Clarity" in names
    assert all("clar" in name.casefold() for name in names)
    proxy.set_filters("torpor", "Shaman", 59)
    assert proxy.rowCount() == 0
    proxy.set_filters("torpor", "Shaman", 60)
    assert proxy.rowCount() == 1


def test_spell_listings_are_explicit_level_1_to_60_rows():
    _app()
    model = SpellLibraryModel(p99_spell_entries())
    levels = [listing.level for listing in model.listings]
    assert levels == sorted(levels)
    assert min(levels) == 1
    assert max(levels) == 60
    assert model.COLUMNS == ("Level", "Spell", "Class")


def test_wiki_acquisition_is_native_and_active_content_is_removed():
    wikitext = """
{{Spellpage|
| where_to_obtain =
* Kunark Level 50+ Mob Drop
[[Old Sebilis]]
* [[Emperor Chottal]]
}}
== Classes ==
* [[Shaman]] - Level 60
== Merchants ==
{|\n! Merchant !! Zone !! Price\n|-\n| [[Rizlona]] || [[The Overthere]] || 5,000 pp\n|}
== Research ==
Combine [[Rune A]] and [[Rune B]].
"""
    acquisition = extract_acquisition_text(wikitext)
    assert "MERCHANTS" in acquisition
    assert "Rizlona" in acquisition
    assert "5,000 pp" in acquisition
    assert "RESEARCH" in acquisition
    assert "WHERE TO OBTAIN" in acquisition
    assert "Emperor Chottal" in acquisition
    sanitized = sanitize_wiki_html(
        '<script>alert(1)</script><img src="track"><a href="/Torpor" '
        'onclick="bad()">Torpor</a><table bgcolor="#fff" border=1>'
        '<tr><td style="background:white" color=black>Dark cell</td>'
        '</tr></table>')
    assert "script" not in sanitized.casefold()
    assert "<img" not in sanitized.casefold()
    assert "onclick" not in sanitized.casefold()
    assert "bgcolor=" not in sanitized.casefold()
    assert "background:white" not in sanitized.casefold()
    assert "color=black" not in sanitized.casefold()
    assert "border=" not in sanitized.casefold()
    assert 'href="https://wiki.project1999.com/Torpor"' in sanitized
    assert _wiki_title_from_url(
        "https://wiki.project1999.com/Emperor_Chottal") == "Emperor Chottal"
    assert _wiki_title_from_url(
        "https://wiki.project1999.com/index.php?title=Old_Sebilis") == "Old Sebilis"


def test_p99_class_skill_tables_include_unlock_training_caps_and_guidance():
    rendered = """
<h1><span id="Skills">Skills</span></h1>
<h2><span id="Specialization">Specialization</span></h2>
<p>Enchanters usually specialize in <a href="/Skill_Alteration">Alteration</a>.</p>
<h2><span id="Casting_Skills">Casting Skills</span></h2>
<table><tr><td><b>Level</b></td><td>Trained</td><td>Skill</td>
<td>Cap Until 50</td><td>Cap Above 50</td></tr>
<tr><td>4</td><td>Yes</td><td><a href="/Skill_Meditate">Meditate</a></td>
<td>235</td><td>252</td></tr></table>
<h2><span id="Combat_Skills">Combat Skills</span></h2>
<table><tr><td>Level</td><td>Trained</td><td>Skill</td><td>Cap Until 50</td>
<td>Cap Above 50</td></tr><tr><td>22</td><td>Yes</td><td>Dodge</td>
<td>75</td><td>75</td></tr></table>
<h1><span id="Spell_Information">Spell Information</span></h1>
"""
    data = parse_class_skills_html(rendered, "Enchanter")
    assert data["class"] == "Enchanter"
    assert "specialize in Alteration" in data["specialization"]
    assert data["skills"] == [
        {"level": 4, "trained": "Yes", "name": "Meditate",
         "cap_50": "235", "cap_60": "252", "category": "Casting",
         "target": "Skill Meditate"},
        {"level": 22, "trained": "Yes", "name": "Dodge",
         "cap_50": "75", "cap_60": "75", "category": "Combat",
         "target": "Skill Dodge"},
    ]


def test_spell_price_prefers_cached_green_wts_row():
    class Model:
        items = [
            {"n": "Spell: Torpor", "t": 1, "a30": 40000, "t30": 20},
            {"n": "Spell: Torpor", "t": 0, "a30": 50000, "t30": 8},
            {"n": "Torpor", "t": 2, "a30": 48000, "t30": 40},
        ]

    class Market:
        _model = Model()

    result = GreenMarket.price_for_spell(Market(), "Torpor")
    assert result["t"] == 0
    assert result["a30"] == 50000


def test_spell_library_is_complete_but_lazy(monkeypatch):
    _app()
    monkeypatch.setattr(SpellLibraryDialog, "_fetch", lambda *_args: None)

    class Market:
        @staticmethod
        def price_for_spell(name):
            return {"n": f"Spell: {name}", "t": 0, "a30": 1200,
                    "a60": 1250, "a90": 1300, "t30": 9}

    dialog = SpellLibraryDialog(Market())
    try:
        assert dialog.proxy.rowCount() > 1100
        assert dialog.level_filter.count() == 61
        assert dialog.level_filter.itemData(1) == 1
        assert dialog.level_filter.itemData(60) == 60
        dialog.class_filter.setCurrentText("Enchanter")
        _app().processEvents()
        enchanter_levels = [
            dialog.level_filter.itemData(index)
            for index in range(1, dialog.level_filter.count())]
        assert enchanter_levels
        assert enchanter_levels == sorted(set(enchanter_levels))
        assert all(any(
            class_name == "Enchanter" and level == listed_level
            for entry in dialog._entries
            for class_name, listed_level in entry.class_levels)
                   for level in enchanter_levels)
        dialog.search.setText("Torpor")
        dialog.class_filter.setCurrentText("Shaman")
        dialog.level_filter.setCurrentIndex(
            dialog.level_filter.findData(60))
        _app().processEvents()
        dialog._select_first()
        _app().processEvents()
        assert dialog.proxy.rowCount() == 1
        index = dialog.proxy.index(0, 1)
        dialog._activate_index(index)
        assert dialog._current.name == "Torpor"
        assert dialog.table.viewport().cursor().shape() == \
            Qt.CursorShape.PointingHandCursor
        assert dialog.body.openExternalLinks() is False
        assert dialog.catalog_tabs.count() == 2
        assert dialog.catalog_tabs.tabText(1) == "Skills"
        assert dialog.catalog_tabs.tabToolTip(1)
        assert dialog.search.toolTip()
        assert dialog.class_filter.toolTip()
        assert dialog.level_filter.toolTip()
        assert "PigParse Green" in dialog._price_html(
            dialog.model.listings[
                dialog.proxy.mapToSource(
                    dialog.proxy.index(0, 0)).row()].entry)

        opened = []
        dialog._fetch_linked_page = lambda title, url=None: opened.append(title)
        dialog._open_detail_link(QUrl(
            "https://wiki.project1999.com/Emperor_Chottal"))
        assert opened == ["Emperor Chottal"]
    finally:
        dialog.close()


def test_skills_tab_filters_visible_class_rows(monkeypatch):
    _app()
    monkeypatch.setattr(
        SpellLibraryDialog, "_load_selected_class_skills", lambda *_args, **_kwargs: None)
    dialog = SpellLibraryDialog()
    try:
        dialog.catalog_tabs.setCurrentWidget(dialog.skills_page)
        dialog._set_skills_data({
            "class": "Enchanter",
            "specialization": "Alteration is the common specialization.",
            "skills": [
                {"level": 4, "trained": "Yes", "name": "Meditate",
                 "cap_50": "235", "cap_60": "252", "category": "Casting",
                 "target": "Skill Meditate"},
                {"level": 22, "trained": "Yes", "name": "Dodge",
                 "cap_50": "75", "cap_60": "75", "category": "Combat",
                 "target": "Skill Dodge"},
            ],
        })
        assert dialog.skill_table.rowCount() == 2
        dialog.skill_search.setText("dodge")
        _app().processEvents()
        assert dialog.skill_table.rowCount() == 1
        assert dialog.skill_table.item(0, 1).text() == "Dodge"
        assert dialog.skill_table.horizontalHeaderItem(0).toolTip()
        assert dialog.skill_search.findChild(QToolButton).toolTip()
    finally:
        dialog.close()


def test_spell_library_prices_and_wiki_cache_follow_market_server():
    _app()

    class Market:
        _server = "Blue"

        @staticmethod
        def price_for_spell(name):
            return {"n": f"Spell: {name}", "t": 0, "a30": 900,
                    "t30": 4}

    dialog = SpellLibraryDialog(Market())
    try:
        entry = next(item for item in dialog._entries if item.name == "Clarity")
        prices = dialog._price_html(entry, {"reference": 1000})
        assert "PigParse Blue" in prices
        assert "P99 Wiki Blue" in prices
        assert _cache_path("Clarity", "Green") != _cache_path(
            "Clarity", "Blue")
    finally:
        dialog.close()
