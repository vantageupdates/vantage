"""Refresh the small, read-only P99 reference catalogs bundled with Vantage.

Runtime code never crawls the whole Wiki: it uses the generated catalogs
immediately, then refreshes only the page a user actually opens.
"""

from __future__ import annotations

import configparser
import json
from pathlib import Path
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "reference"
API = "https://wiki.project1999.com/api.php"
USER_AGENT = "VantageReferenceBuilder/1.0 (vantagecompanion@gmail.com)"


def _get(parameters):
    url = API + "?" + urllib.parse.urlencode(parameters)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def quest_titles():
    titles = set()
    continuation = ""
    for _ in range(20):
        parameters = {
            "action": "query", "list": "categorymembers",
            "cmtitle": "Category:Quests", "cmnamespace": "0",
            "cmlimit": "max", "format": "json",
        }
        if continuation:
            parameters["cmcontinue"] = continuation
        payload = _get(parameters)
        titles.update(
            str(item.get("title") or "").strip()
            for item in payload.get("query", {}).get("categorymembers", [])
            if str(item.get("title") or "").strip())
        continuation = str(
            payload.get("continue", {}).get("cmcontinue") or
            payload.get("query-continue", {}).get(
                "categorymembers", {}).get("cmcontinue") or "")
        if not continuation:
            break
    return sorted(titles, key=str.casefold)


def zones():
    parser = configparser.ConfigParser()
    source = ROOT / "data" / "maps" / "map_keys.ini"
    parser.read_string("[zones]\n" + source.read_text(encoding="utf-8"))
    return [
        {"name": name.title(), "value": name, "map": short_name}
        for name, short_name in sorted(
            parser["zones"].items(), key=lambda pair: pair[0].casefold())
    ]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    quests = quest_titles()
    zone_rows = zones()
    (OUTPUT / "quest_catalog.json").write_text(json.dumps({
        "version": 1,
        "source": "Project 1999 Wiki Category:Quests",
        "titles": quests,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "zone_catalog.json").write_text(json.dumps({
        "version": 1,
        "source": "Vantage bundled P99 map index",
        "zones": zone_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {len(quests)} quests and {len(zone_rows)} zone aliases.")


if __name__ == "__main__":
    main()
