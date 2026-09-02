import sqlite3

from PySide6.QtCore import Qt

from vantage.parsers.market import (
    GEAR_COLUMN_DEFAULT_WIDTHS, GEAR_DB_FIELDS, GearFilter, GearItem,
    GearModel, MarketFilter, MarketModel,
    gear_item_summary_html, load_gear_items)


def _gear(name, **values):
    defaults = {
        "classes": 1, "races": 1, "slots": 131072,
        "ac": 0, "hp": 0, "mana": 0, "astr": 0, "asta": 0,
        "adex": 0, "aagi": 0, "aint": 0, "awis": 0, "acha": 0,
        "mr": 0, "fr": 0, "cr": 0, "dr": 0, "pr": 0,
        "attack": 0, "haste": 0, "regen": 0, "manaregen": 0,
        "clickName": "", "procName": "", "wornName": "",
        "focusName": "", "bardName": "",
    }
    defaults.update(values)
    return GearItem(name=name, **defaults)


def test_local_p99_index_loads_stats_and_effects(tmp_path):
    database_path = tmp_path / "items.sqlite"
    numeric = set(GEAR_DB_FIELDS) - {
        "name", "clickName", "procName", "wornName", "focusName",
        "bardName"}
    definitions = [
        f"{field} {'INTEGER' if field in numeric else 'TEXT'}"
        for field in GEAR_DB_FIELDS]
    with sqlite3.connect(database_path) as database:
        database.execute(f"CREATE TABLE items ({', '.join(definitions)})")
        values = {
            field: 0 if field in numeric else "" for field in GEAR_DB_FIELDS}
        values.update({
            "id": 4242, "name": "Crown of Insight", "classes": 8192,
            "races": 32, "slots": 4, "ac": 12, "mana": 75,
            # The downloaded classic EQ schema uses 0 for NO DROP.
            "aint": 9, "nodrop": 0, "wornName": "Flowing Thought I"})
        database.execute(
            f"INSERT INTO items VALUES ({', '.join('?' for _ in GEAR_DB_FIELDS)})",
            [values[field] for field in GEAR_DB_FIELDS])

    era_path = tmp_path / "item_eras.json"
    era_path.write_text(
        '{"items":{"crown of insight":"velious"}}', encoding="utf-8")
    items = load_gear_items(database_path, era_path)

    assert len(items) == 1
    assert items[0].id == 4242
    assert (items[0].ac, items[0].aint) == (12, 9)
    assert (items[0].nodrop, items[0].era) == (1, "velious")
    assert items[0].effects("worn") == (("Worn", "Flowing Thought I"),)
    summary = gear_item_summary_html(items[0])
    assert "<b>AC</b> +12" in summary
    assert "<b>Worn</b> · Flowing Thought I" in summary
    assert "<b>NO DROP</b>" in summary
    assert "<b>Velious</b>" in summary


def test_local_p99_index_normalizes_inverted_tradeable_flag(tmp_path):
    database_path = tmp_path / "items.sqlite"
    numeric = set(GEAR_DB_FIELDS) - {
        "name", "clickName", "procName", "wornName", "focusName",
        "bardName"}
    definitions = [
        f"{field} {'INTEGER' if field in numeric else 'TEXT'}"
        for field in GEAR_DB_FIELDS]
    with sqlite3.connect(database_path) as database:
        database.execute(f"CREATE TABLE items ({', '.join(definitions)})")
        for name, source_nodrop in (
                ("Epic Spear", 0), ("Tradeable Tunic", 1)):
            values = {
                field: 0 if field in numeric else ""
                for field in GEAR_DB_FIELDS}
            values.update({"name": name, "nodrop": source_nodrop})
            database.execute(
                f"INSERT INTO items VALUES "
                f"({', '.join('?' for _ in GEAR_DB_FIELDS)})",
                [values[field] for field in GEAR_DB_FIELDS])

    loaded = {item.name: item for item in load_gear_items(database_path)}

    assert loaded["Epic Spear"].nodrop == 1
    assert loaded["Tradeable Tunic"].nodrop == 0
    assert "NO DROP" in gear_item_summary_html(loaded["Epic Spear"])
    assert "Droppable" in gear_item_summary_html(loaded["Tradeable Tunic"])


def test_gear_catalog_combines_filters_effect_search_and_stat_sorting():
    low = _gear("Low Crown", classes=8192, races=32, ac=8, aint=4)
    high = _gear(
        "High Crown", classes=8192, races=32, ac=25, aint=12,
        wornName="Flowing Thought II")
    wrong_class = _gear(
        "Warrior Helm", classes=1, races=32, ac=40, aint=1,
        procName="Flame Strike")
    model = GearModel()
    proxy = GearFilter()
    proxy.setSourceModel(model)
    model.set_items([low, high, wrong_class])
    model.set_prices([
        {"n": "High Crown", "t": 0, "a30": 5000, "t30": 12}])

    proxy.set_gear_filter("class", 8192)
    proxy.set_gear_filter("race", 32)
    proxy.sort(3, Qt.SortOrder.DescendingOrder)
    assert proxy.rowCount() == 2
    assert proxy.data(proxy.index(0, 0)) == "High Crown"
    assert proxy.data(proxy.index(0, 1)) == "Worn: Flowing Thought II"
    assert proxy.data(proxy.index(0, 2)) == "5,000 pp"

    model.set_active_stat("aint")
    proxy.sort(3, Qt.SortOrder.DescendingOrder)
    assert proxy.data(proxy.index(0, 3)) == "+12"

    proxy.set_effect_filter("worn")
    assert proxy.rowCount() == 1
    proxy.set_query("flowing thought")
    assert proxy.data(proxy.index(0, 0)) == "High Crown"


def test_gear_catalog_filters_drop_status_and_wiki_era():
    droppable = _gear("Classic Sword", era="classic", nodrop=0)
    nodrop = _gear("Velious Crown", era="velious", nodrop=1)
    unknown = _gear("Unindexed Trinket", era="", nodrop=0)
    model = GearModel()
    proxy = GearFilter()
    proxy.setSourceModel(model)
    model.set_items([droppable, nodrop, unknown])

    proxy.set_tradeability_filter("nodrop")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 0)) == "Velious Crown"

    proxy.set_tradeability_filter("")
    proxy.set_era_filter("classic")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 0)) == "Classic Sword"


def test_gear_primary_columns_prioritize_name_and_effects():
    assert GearModel.COLUMNS[:4] == (
        ("Item", "name"), ("Effects", "effects"),
        ("30d price", "price"), ("Best AC", "selected"))
    assert GEAR_COLUMN_DEFAULT_WIDTHS["name"] >= 200
    assert GEAR_COLUMN_DEFAULT_WIDTHS["effects"] >= 220


def test_price_results_can_be_found_by_equipment_effect_name():
    model = MarketModel()
    proxy = MarketFilter()
    proxy.setSourceModel(model)
    item = {"n": "High Crown", "t": 0, "a30": 5000}
    model.set_items([item])
    proxy.set_gear({
        "high crown": _gear("High Crown", wornName="Flowing Thought II")})

    proxy.set_query("flowing thought")

    assert proxy.rowCount() == 1
