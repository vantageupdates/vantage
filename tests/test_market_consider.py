import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.market import considered_name


ROOT = Path(__file__).resolve().parents[1]


def test_consider_parser_matches_all_original_faction_phrases():
    examples = (
        "Dain Frostreaver IV regards you as an ally -- You could probably win.",
        "a frost giant looks upon you warmly.",
        "Kromrif recruiter kindly considers you.",
        "Kromzek warrior judges you amiably.",
        "the banker regards you indifferently.",
        "a guard looks your way apprehensively.",
        "a sentinel glowers at you dubiously.",
        "a drake glares at you threateningly.",
        "Vulak`Aerr scowls at you, ready to attack -- what would you like your tombstone to say?",
    )
    assert [considered_name(line) for line in examples] == [
        "Dain Frostreaver IV", "a frost giant", "Kromrif recruiter",
        "Kromzek warrior", "the banker", "a guard", "a sentinel",
        "a drake", "Vulak`Aerr"]
    assert considered_name("You say, 'regards you as an ally'") == "You say, '"


SCRIPT = r"""
import datetime
import json
from types import SimpleNamespace
from vantage.helpers.application import VantageApp
from vantage.helpers import config

class Card:
    def __init__(self):
        self.visible = True
        self.raised = 0
        self.closed = 0
    def isVisible(self): return self.visible
    def raise_(self): self.raised += 1
    def close(self): self.visible = False; self.closed += 1

app = VantageApp([])
market = app._parsers_dict['market']
config.data['market']['auto_consider_lookup'] = True
cards = []
def show(target, label, kind):
    cards.append([target, label, kind, Card()])
    return cards[-1][3]
market._show_wiki_entity = show
stamp = datetime.datetime(2026, 8, 30, 12, 0, 0)
market.parse(stamp, 'Dain Frostreaver IV regards you indifferently.')
market.parse(stamp, 'Dain Frostreaver IV glares at you threateningly.')
raised = cards[0][3].raised
market._character_context = SimpleNamespace(pet_name='Gabtik')
market.parse(stamp, 'Gabtik regards you indifferently.')
print(json.dumps({
    'calls': [[value[0], value[1], value[2]] for value in cards],
    'raised': raised,
    'status': market.status.text(),
}))
app.quit()
"""


def test_consider_lookup_reuses_card_and_routes_active_pet_locally(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["calls"] == [[
        "Dain Frostreaver IV", "Dain Frostreaver IV", "npc"]]
    assert result["raised"] == 1
    assert result["status"] == "/consider · Gabtik · active pet · local EQ log"
