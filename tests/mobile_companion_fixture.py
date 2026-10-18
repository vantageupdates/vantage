"""Loopback-only permanent PWA fixture with synthetic catalogs and import data.

python tests/mobile_companion_fixture.py --port 8876
Optional --data points at a folder containing production-shaped catalog JSON.
POST /__fixture__/mode with {"fail":["items"],"invalid":["spells"]} controls
catalog failures without modifying any files. Empty lists restore normal replies.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/vantage/companion/"
CATALOGS = {
    "items": {"items": [{"name": "Jade Mace", "price": 5000, "posts": 12,
        "classes": 512, "races": 4096, "slots": 8192, "nodrop": False,
        "era": "kunark", "id": 1, "peqId": 1, "stats": {"ac": 15},
        "effects": [{"type": "Proc", "name": "Light Strike"}],
        "wiki": "https://wiki.project1999.com/Jade_Mace"}]},
    "spells": {"spells": [{"id": 42, "name": "Clarity", "levels": [["Enchanter", 29]],
        "icon": 5, "summary": "Improves mana regeneration.",
        "wiki": "https://wiki.project1999.com/Clarity"},
        {"id": 43, "name": "Torpor", "levels": [["Shaman", 60]], "icon": 6,
         "summary": "Powerful healing.", "wiki": "https://wiki.project1999.com/Torpor"}]},
    "zones": {"zones": [{"name": "South Karana", "wiki": "https://wiki.project1999.com/South_Karana"},
        {"name": "West Commonlands", "wiki": "https://wiki.project1999.com/West_Commonlands"}]},
    "quests": {"quests": [{"name": "Jboots", "wiki": "https://wiki.project1999.com/Jboots"},
        {"name": "Druid Epic Quest", "wiki": "https://wiki.project1999.com/Druid_Epic_Quest"}]},
    "meta": {"generatedAt": "2026-10-14T00:00:00+00:00", "priceSource": "Synthetic PigParse",
        "spellSource": "Synthetic classic spells", "itemCount": 1, "spellCount": 2},
}


class Handler(BaseHTTPRequestHandler):
    failures = set()
    invalid = set()
    data_directory = None

    def log_message(self, *_args):
        pass

    def send(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/fixture-copy.json":
            return self.send(200, (ROOT / "tests/fixtures/companion-offline.json").read_bytes(), "application/json")
        if not path.startswith(PREFIX):
            return self.send(404, b"not found", "text/plain")
        target = path[len(PREFIX):] or "index.html"
        if target.startswith("data/") and target.endswith(".json"):
            key = Path(target).stem
            if key in self.failures:
                return self.send(503, b"temporarily unavailable", "text/plain")
            if key in self.invalid:
                return self.send(200, b'{"unexpected":true}', "application/json")
            if key not in CATALOGS:
                return self.send(404, b"missing catalog", "text/plain")
            payload = ((self.data_directory / f"{key}.json").read_bytes() if self.data_directory
                       else json.dumps(CATALOGS[key]).encode())
            return self.send(200, payload, "application/json")
        allowed = {"index.html", "app.css", "app.js", "storage.js", "offline.js", "sw.js", "manifest.webmanifest",
                   "dkp.js", "guild-dkp.js", "guild-dkp.css"}
        if target in {"icon-256.png", "icon-1254.png"}:
            file = ROOT / "data/ui" / ("icon.png" if target == "icon-256.png" else "icon-master.png")
        elif target in allowed:
            file = ROOT / "companion-web" / target
        else:
            return self.send(404, b"not found", "text/plain")
        content_type = {".js": "text/javascript", ".css": "text/css", ".html": "text/html",
                        ".png": "image/png", ".webmanifest": "application/manifest+json"}[file.suffix]
        self.send(200, file.read_bytes(), content_type)

    def do_POST(self):
        if self.path != "/__fixture__/mode":
            return self.send(404, b"not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 2048:
                raise ValueError("invalid body")
            data = json.loads(self.rfile.read(length))
            Handler.failures = set(data.get("fail", [])) & set(CATALOGS)
            Handler.invalid = set(data.get("invalid", [])) & set(CATALOGS)
        except (ValueError, TypeError):
            return self.send(400, b"invalid mode", "text/plain")
        self.send(200, b'{"ok":true}', "application/json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    Handler.data_directory = args.data
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{server.server_port}{PREFIX}", flush=True)
    server.serve_forever()
