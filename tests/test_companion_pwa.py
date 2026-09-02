import importlib.util
import json
from pathlib import Path
import sqlite3

from vantage.helpers.mobile_share import COMPANION_URL


ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / "companion-web"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "vantage_companion_builder", COMPANION / "build_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_companion_is_installable_at_the_permanent_github_pages_address():
    manifest = json.loads(
        (COMPANION / "manifest.webmanifest").read_text(encoding="utf-8"))
    html = (COMPANION / "index.html").read_text(encoding="utf-8")
    worker = (COMPANION / "sw.js").read_text(encoding="utf-8")

    assert COMPANION_URL == "https://vantageupdates.github.io/vantage/companion/"
    assert manifest["start_url"] == "/vantage/companion/#market"
    assert manifest["display"] == "standalone"
    assert len(manifest["icons"]) >= 2
    assert 'id="install"' in html
    assert "Add to Home Screen" in html
    assert "Needs the PC QR session" in html
    assert "data/items.json" not in worker
    assert "'/data/'" in worker


def test_static_item_builder_preserves_price_stats_and_correct_binding(tmp_path):
    builder = load_builder()
    fields = (
        "id", "peqId", "name", "classes", "races", "slots", "nodrop",
        *builder.STAT_FIELDS,
        *(field for _label, field in builder.EFFECT_FIELDS),
    )
    columns = ", ".join(
        f"`{field}` {'TEXT' if field in {'name', *[value for _label, value in builder.EFFECT_FIELDS]} else 'INTEGER'}"
        for field in fields)
    database_path = tmp_path / "items.sqlite"
    with sqlite3.connect(database_path) as database:
        database.execute(f"CREATE TABLE items ({columns})")
        values = {field: 0 for field in fields}
        values.update({
            "id": 770, "peqId": 14701,
            "name": "Black Sapphire Electrum Earring",
            "classes": 16383, "races": 8191, "slots": 18,
            "nodrop": 1, "ac": 2, "hp": 35, "mana": 25,
            "clickName": "Test Effect",
        })
        database.execute(
            f"INSERT INTO items ({', '.join(f'`{field}`' for field in fields)}) "
            f"VALUES ({', '.join('?' for _field in fields)})",
            [values[field] for field in fields])
    eras = tmp_path / "eras.json"
    eras.write_text(json.dumps({
        "items": {"black sapphire electrum earring": "classic"}}))
    rows = builder.load_items(database_path, [{
        "n": "Black Sapphire Electrum Earring", "a30": 599,
        "t30": 975, "l": "recent",
    }], eras)

    assert rows == [{
        "name": "Black Sapphire Electrum Earring",
        "price": 599, "posts": 975, "last": "recent",
        "classes": 16383, "races": 8191, "slots": 18,
        "nodrop": False, "era": "classic", "id": 770, "peqId": 14701,
        "stats": {"ac": 2, "hp": 35, "mana": 25},
        "effects": [{"type": "Click", "name": "Test Effect"}],
        "wiki": "https://wiki.project1999.com/Black_Sapphire_Electrum_Earring",
    }]
