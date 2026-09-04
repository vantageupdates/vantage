import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.parsers.quests import (
    _step_key, parse_quest_catalog_payload, parse_quest_wikitext)


ROOT = Path(__file__).parents[1]


ACCESSIBILITY_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
import vantage.parsers.quests as quests_module

announcements = []
quests_module._announce_accessible = (
    lambda _widget, text, assertive=False:
    announcements.append([str(text), bool(assertive)]))
app = VantageApp([])
window = app._parsers_dict['quests']
window._set_catalog(['Zlandicar Quest', 'Aegis Quest'], 'test')
window.show()
app.processEvents()
search_focus = window.search.hasFocus()

window.search.setText('aeg')
QTest.qWait(320)
app.processEvents()
filter_state = [window.match_count.text(), list(announcements)]

window._show_quest({
    'title': 'Aegis Quest', 'summary': 'Summary',
    'steps': ['First step', 'Second step'],
    'wiki_url': 'https://wiki.project1999.com/Aegis_Quest',
})
window._open_checklist()
app.processEvents()
checklist_focus = window._checklist._boxes[0].hasFocus()
QTest.keyClick(window._checklist, Qt.Key_Escape)
app.processEvents()
return_focus = window.checklist_button.hasFocus()

announcements.clear()
window._checklist._boxes[0].setChecked(True)
window._checklist._boxes[1].setChecked(True)
QTest.qWait(280)
app.processEvents()
progress_messages = list(announcements)

print(json.dumps({
    'search_focus': search_focus,
    'filter_state': filter_state,
    'checklist_focus': checklist_focus,
    'return_focus': return_focus,
    'progress_messages': progress_messages,
}))
app.quit()
"""


QUEST_PAGE = r"""
{{Classic Era}}
{| class="questTopTable"
! ''' Start Zone: '''
| [[Oggok]]
|-
! ''' Quest Giver: '''
| [[Clurg (NPC)|Clurg]]
|-
! ''' Minimum Level: '''
| 4+
|-
! ''' Classes: '''
| All ([[Enchanter]], [[Rogue]], [[Bard]])
|}

== Reward ==
* {{:Stein of Moggok}}
* [[Faction]]

== TLDR; Walkthrough ==
* '''Get [[Kiola Nut]]'''
** Go to [[Ocean of Tears]] and purchase a [[Kiola Nut]].
* '''Get [[Barkeep Compendium]]'''
** Give the four ingredients to [[Gregor Nasin]] at the same time.

== Full Walkthrough ==
This longer section must not replace the concise walkthrough.

[[Category: Quests]]
"""


def test_catalog_supports_modern_mediawiki_continuation():
    titles, continuation = parse_quest_catalog_payload({
        "continue": {"cmcontinue": "page|next", "continue": "-||"},
        "query": {"categorymembers": [
            {"pageid": 1, "title": "A Job for Nanrum"},
            {"pageid": 2, "title": "Aegis of Life Quest"},
        ]},
    })
    assert titles == ["A Job for Nanrum", "Aegis of Life Quest"]
    assert continuation == "page|next"


def test_catalog_supports_project1999_legacy_continuation():
    titles, continuation = parse_quest_catalog_payload({
        "query-continue": {
            "categorymembers": {"cmcontinue": "page|legacy"}},
        "query": {"categorymembers": [{"title": "10th Coldain Ring Quest"}]},
    })
    assert titles == ["10th Coldain Ring Quest"]
    assert continuation == "page|legacy"


def test_quest_page_becomes_summary_and_actionable_steps():
    quest = parse_quest_wikitext(QUEST_PAGE, "Exotic Drinks")
    assert quest["title"] == "Exotic Drinks"
    assert quest["metadata"]["Start Zone"] == "Oggok"
    assert quest["metadata"]["Quest Giver"] == "Clurg"
    assert "Start Zone: Oggok" in quest["summary"]
    assert "Faction" in quest["rewards"]
    assert quest["steps"] == [
        "Get Kiola Nut",
        "↳ Go to Ocean of Tears and purchase a Kiola Nut.",
        "Get Barkeep Compendium",
        "↳ Give the four ingredients to Gregor Nasin at the same time.",
    ]
    assert quest["wiki_url"].endswith("/Exotic_Drinks")


def test_checklist_keys_are_stable_and_ignore_case():
    assert _step_key("Get Kiola Nut") == _step_key(" get kiola nut ")
    assert _step_key("Get Kiola Nut") != _step_key("Get Honey Jum")


def test_unstructured_page_has_safe_fallback():
    quest = parse_quest_wikitext("A community note without sections.", "Odd Quest")
    assert quest["steps"] == []
    assert "community note" in quest["summary"]


def test_quest_keyboard_focus_counts_and_coalesced_announcements(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", ACCESSIBILITY_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["search_focus"] is True
    assert result["filter_state"][0] == "1 matching quest"
    assert result["filter_state"][1][-1] == ["1 matching quest", False]
    assert result["checklist_focus"] is True
    assert result["return_focus"] is True
    assert result["progress_messages"] == [["2 of 2 steps complete", False]]
