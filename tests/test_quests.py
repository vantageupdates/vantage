import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.parsers.quests import (
    _plain_wiki, _section, _step_key, parse_quest_catalog_payload,
    parse_quest_wikitext)


ROOT = Path(__file__).parents[1]


ACCESSIBILITY_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from vantage.helpers import config
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

long_step = ('Travel to the hidden grove beside the Skyfire zone line at '
             '3234, 2871, then speak with Telin Darkforest and say action '
             'while invisible. ' + 'Keep the exact location context. ' * 12)
records = [
    {'text': 'Acquire the Worn Note', 'depth': 0, 'kind': 'group', 'group': ''},
    {'text': long_step, 'depth': 1, 'kind': 'action',
     'group': 'Acquire the Worn Note'},
    {'text': 'Give the Worn Note to Faelin Bloodbriar.', 'depth': 1,
     'kind': 'action', 'group': 'Acquire the Worn Note'},
]
window._show_quest({
    'title': 'Aegis Quest', 'summary': 'Summary',
    'steps': records,
    'wiki_url': 'https://wiki.project1999.com/Aegis_Quest',
})
window._open_checklist()
app.processEvents()
checklist_focus = window._checklist._boxes[0].hasFocus()
first_box = window._checklist._boxes[0]
first_row = first_box.parentWidget()
wrap_state = {
    'label_wrap': first_row.label.wordWrap(),
    'horizontal_off': window._checklist.steps_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarAlwaysOff,
    'accessible_full': long_step.strip() in first_box.accessibleName(),
    'persisted_full': json.loads(
        config.data['quests']['checklist']['steps'][1])['text'] == long_step.strip(),
}
QTest.mouseClick(first_row.label, Qt.LeftButton)
label_toggled = first_box.isChecked()
first_box.setFocus()
QTest.keyClick(first_box, Qt.Key_Space)
QTest.keyClick(first_box, Qt.Key_Space)
keyboard_toggled = first_box.isChecked()
window._checklist._boxes[1].setFocus()
window._checklist.set_quest('Aegis Quest', records,
                            config.data['quests']['checklist']['checked'],
                            save=False)
app.processEvents()
rebuild_focus = window._checklist._boxes[1].hasFocus()
reworded = [records[0], records[1], dict(records[2], text='Reworded final turn-in.')]
window._checklist.set_quest('Aegis Quest', reworded, save=False)
app.processEvents()
reworded_focus = window._checklist._boxes[1].hasFocus()
window._checklist.set_quest('Aegis Quest', records[:2], save=False)
app.processEvents()
previous_focus = window._checklist._boxes[0].hasFocus()
window._checklist.set_quest('Aegis Quest', [], save=False)
app.processEvents()
stable_focus = window._checklist.reset_button.hasFocus()
window._checklist.set_quest('Aegis Quest', records, save=False)
app.processEvents()
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
    'wrap_state': wrap_state,
    'label_toggled': label_toggled,
    'keyboard_toggled': keyboard_toggled,
    'rebuild_focus': rebuild_focus,
    'reworded_focus': reworded_focus,
    'previous_focus': previous_focus,
    'stable_focus': stable_focus,
    'nested_name': window._checklist._boxes[0].accessibleName(),
    'nested_description': window._checklist._boxes[0].accessibleDescription(),
    'return_focus': return_focus,
    'progress_messages': progress_messages,
}))
app.quit()
"""


QUEST_NETWORK_RECOVERY_SCRIPT = r"""
import json
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
import vantage.parsers.quests as quests_module

quests_module.NETWORK_TIMEOUT_MS = 80

class FakeReply(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.payload = b'{}'
        self.aborted = False
    def abort(self):
        self.aborted = True
        self.finished.emit()
    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError
                if self.aborted else QNetworkReply.NetworkError.NoError)
    def errorString(self):
        return 'cancelled' if self.aborted else ''
    def readAll(self):
        return self.payload

class FakeNetwork:
    def __init__(self):
        self.replies = []
    def get(self, _request):
        reply = FakeReply()
        self.replies.append(reply)
        return reply

def catalog_payload(*titles):
    return json.dumps({'query': {'categorymembers': [
        {'pageid': index + 1, 'ns': 0, 'title': title}
        for index, title in enumerate(titles)
    ]}}).encode()

def quest_payload(title, action):
    wiki = ('== Checklist ==\n* ' + action + '\n== Rewards ==\n* Test reward')
    return json.dumps({'parse': {
        'title': title, 'wikitext': {'*': wiki}
    }}).encode()

app = VantageApp([])
window = app._parsers_dict['quests']
network = FakeNetwork()
window._network = network

# A reply that never emits finished is bounded by Vantage's own watchdog and
# retried. The successful retry completes the catalog deterministically.
window._fetch_catalog(force=True)
catalog_hung = network.replies[-1]
catalog_generation = window._catalog_generation
QTest.qWait(100)
app.processEvents()
catalog_retry = network.replies[-1]
catalog_retry.payload = catalog_payload('Aegis Quest', 'Zlandicar Quest')
catalog_retry.finished.emit()
catalog_recovered = (
    window._catalog == ['Aegis Quest', 'Zlandicar Quest']
    and not window._catalog_loading)

# Exhausting both bounded attempts keeps a previously usable offline catalog
# and exposes a clear manual retry action instead of an endless spinner.
window._set_catalog(['Offline Quest'], 'cached')
window._fetch_catalog(force=True)
offline_first = network.replies[-1]
offline_generation = window._catalog_generation
window._catalog_page_timed_out(offline_first, offline_generation)
offline_second = network.replies[-1]
window._catalog_page_timed_out(offline_second, offline_generation)
offline_fallback = (
    window._catalog == ['Offline Quest']
    and 'offline quest catalog' in window.catalog_status.text()
    and 'Refresh catalog to retry' in window.catalog_status.text())

# A cached quest opens immediately while offline and does not create a network
# request. Cache is the first fallback, not a second loading state.
cached_path = window._quest_cache_path('Cached Quest')
cached_path.parent.mkdir(parents=True, exist_ok=True)
cached_path.write_text(json.dumps({
    'title': 'Cached Quest',
    'wikitext': '== Checklist ==\n* Obtain the cached item.',
}), encoding='utf-8')
requests_before_cache = len(network.replies)
window._load_quest('Cached Quest')
quest_cache_fallback = (
    window.quest_title.text() == 'Cached Quest'
    and len(network.replies) == requests_before_cache
    and 'cached item' in window.steps.item(0).text().lower())

# Detail timeout retries once and then succeeds.
window._load_quest('Recovered Quest')
quest_hung = network.replies[-1]
quest_generation = window._quest_generation
QTest.qWait(100)
app.processEvents()
quest_retry = network.replies[-1]
quest_retry.payload = quest_payload(
    'Recovered Quest', 'Travel to Qeynos and give the note to Guard Nash.')
quest_retry.finished.emit()
quest_recovered = (
    window.quest_title.text() == 'Recovered Quest'
    and 'Travel to Qeynos' in window.steps.item(0).text()
    and not window.retry_quest_button.isVisible())

# A superseded response cannot replace the newly selected quest.
window._load_quest('Old Quest')
old_reply = network.replies[-1]
window._load_quest('New Quest')
new_reply = network.replies[-1]
old_reply.payload = quest_payload('Old Quest', 'Kill the old target.')
old_reply.finished.emit()
new_reply.payload = quest_payload('New Quest', 'Kill the new target.')
new_reply.finished.emit()
stale_safe = (
    window.quest_title.text() == 'New Quest'
    and 'new target' in window.steps.item(0).text().lower())

# With no completion on either attempt, loading still settles into an explicit
# recoverable state.
window._load_quest('Unavailable Quest')
missing_first = network.replies[-1]
missing_generation = window._quest_generation
window._quest_timed_out(missing_first, missing_generation)
missing_second = network.replies[-1]
window._quest_timed_out(missing_second, missing_generation)
detail_settled = (
    'could not be loaded' in window.summary.toPlainText()
    and window.retry_quest_button.isVisible())

print(json.dumps({
    'catalog_recovered': catalog_recovered,
    'offline_fallback': offline_fallback,
    'quest_cache_fallback': quest_cache_fallback,
    'quest_recovered': quest_recovered,
    'stale_safe': stale_safe,
    'detail_settled': detail_settled,
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


DRUID_EPIC = r"""
== Checklist ==
{{CheckboxList}}
* '''Acquire a [[Shiny Tin Bowl]]'''
:* Speak with [[Telin Darkforest]] in [[Burning Wood]] and say "I will take action" to receive a [[Worn note]].
:* Give [[Sionae]] (-2300, -930 in [[East Karana]]) the [[Braided Grass Amulet]].
:* '''CAUTION, INTERCEPT THE ENEMY''': Give [[Teloa]] (-3800, -2860 in [[East Karana]]) the amulet, spawning the [[Dark Elf Corruptor]] at (-700, -1450).
:* Kill the [[Dark Elf Corruptor]], loot [[Fleshbound Tome]].
* '''Forage the [[Hardened Mixture]]'''
:* Forage the following four items:
::* [[Chilled Tundra Root]] from [[Everfrost]].
::* [[Ripened Heartfruit]] from [[Greater Faydark]].
:* Combine all four items in the [[Shiny Tin Bowl]] to make a [[Hardened Mixture]].
== Short Walkthrough ==
'''Telin Darkforest'''
This less structured section must not replace the real checklist.
"""


BONE_CHIPS_QEYNOS = r"""
== Walkthrough ==
''Note - He only takes two bone chips.''
You say, 'Hail, Lashun Novashine'
: Lashun Novashine says 'I wish to spread His word.'
'''Turn in two [[Bone Chips]], unstacked.'''
* Your faction standing with [[Priests of Life]] got better.
'''Hand [[Lashun Novashine]] 2 Gold.''' (Copper may work.)
"""


TENTH_RING = r"""
Overview: Hand the [[Dirk of the Dain]] back to [[Dain Frostreaver IV]] to receive the [[Declaration of War]].
==== Obtaining the Orders ====
: Dain Frostreaver IV says, 'Gather your army and follow me.'
'''Take the [[Declaration of War]] to [[Sentry Badain]] in [[Great Divide]], at -1080, +140. Hand Sentry Badain the Declaration and [[Coldain Hero's Insignia Ring]] to start the war.'''
'''Give [[Seneschal Aldikar]] your ring 9. He gives it back with [[Orders of engagement]].'''
==== Triggering the War ====
'''Give the [[Orders of engagement]] to [[Zrelik]] (not the one in Thurgadin).'''
==== The War ====
<b>Round 1 Mobs</b>
* [[Kromrif Spearman]]
* [[Kromrif Captain]]
Kill [[Narandi the Wretched]] and loot his head.
==== Turn-In for the 10th Ring ====
'''Once you have won, turn in ring 9 and [[Narandi's head]] to [[Seneschal Aldikar]] to receive [[Ring of Dain Frostreaver IV]].'''
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
    assert [step["text"] for step in quest["steps"]] == [
        "Get Kiola Nut", "Go to Ocean of Tears and purchase a Kiola Nut.",
        "Get Barkeep Compendium",
        "Give the four ingredients to Gregor Nasin at the same time."]
    assert [step["kind"] for step in quest["steps"]] == [
        "group", "action", "group", "action"]
    assert quest["wiki_url"].endswith("/Exotic_Drinks")


def test_checklist_keys_are_stable_and_ignore_case():
    assert _step_key("Get Kiola Nut") == _step_key(" get kiola nut ")
    assert _step_key("Get Kiola Nut") != _step_key("Get Honey Jum")


def test_unstructured_page_has_safe_fallback():
    quest = parse_quest_wikitext("A community note without sections.", "Odd Quest")
    assert quest["steps"] == []
    assert "community note" in quest["summary"]


def test_section_keeps_nested_subsections_until_peer_heading():
    source = "== Checklist ==\nfirst\n==== Part A ====\nsecond\n== Other ==\nno"
    assert _section(source, ("Checklist",)) == \
        "first\n==== Part A ====\nsecond"


def test_parameterized_wiki_templates_preserve_meaningful_context():
    assert _plain_wiki("Meet at {{Loc|123|-456|7}}") == \
        "Meet at 123, -456, 7"
    assert _plain_wiki("Meet at {{Loc|x=123|y=-456|z=7}}") == \
        "Meet at 123, -456, 7"
    nested = _plain_wiki(
        "Find {{NPC|Telin Darkforest|zone=[[Burning Wood]]|"
        "loc={{Loc|3234|2871}}}}")
    assert nested == (
        "Find Telin Darkforest (zone: Burning Wood; loc: 3234, 2871)")
    assert _plain_wiki(
        "Loot {{Item|Worn Note|source=Telin Darkforest}}") == \
        "Loot Worn Note (source: Telin Darkforest)"
    assert _plain_wiki("{{Mystery|item=Bone Chips|count=2}}") == \
        "Mystery: item: Bone Chips; count: 2"
    assert "open the full Wiki page" in _plain_wiki("{{UnresolvedTemplate}}")


def test_druid_epic_prefers_checklist_and_keeps_every_nested_action():
    steps = parse_quest_wikitext(DRUID_EPIC, "Druid Epic Quest")["steps"]
    actions = [step["text"] for step in steps if step["kind"] == "action"]
    assert "Speak with Telin Darkforest in Burning Wood and say \"I will take action\" to receive a Worn note." in actions
    assert "Give Sionae (-2300, -930 in East Karana) the Braided Grass Amulet." in actions
    assert any("Give Teloa" in action and "-3800, -2860" in action
               and "Dark Elf Corruptor" in action for action in actions)
    assert "Forage Chilled Tundra Root from Everfrost." in actions
    assert "Forage Ripened Heartfruit from Greater Faydark." in actions
    assert "Combine all four items in the Shiny Tin Bowl to make a Hardened Mixture." in actions
    assert any(step["kind"] == "group" and
               step["text"] == "Forage the Hardened Mixture" for step in steps)


def test_bone_chips_extracts_unbulleted_bold_turnins_not_dialogue_or_faction():
    steps = parse_quest_wikitext(
        BONE_CHIPS_QEYNOS, "Bone Chips Qeynos")["steps"]
    actions = [step["text"] for step in steps if step["kind"] == "action"]
    assert "Turn in two Bone Chips, unstacked." in actions
    assert "Hand Lashun Novashine 2 Gold. (Copper may work.)" in actions
    assert not any("faction standing" in action.casefold() for action in actions)
    assert not any("says '" in action for action in actions)


def test_tenth_ring_extracts_full_actions_and_excludes_mob_name_rows():
    steps = parse_quest_wikitext(
        TENTH_RING, "10th Coldain Ring Quest")["steps"]
    actions = [step["text"] for step in steps if step["kind"] == "action"]
    assert any("Take the Declaration of War" in action and
               "-1080, +140" in action for action in actions)
    assert any("Hand Sentry Badain" in action and
               "Coldain Hero's Insignia Ring" in action for action in actions)
    assert "Give the Orders of engagement to Zrelik (not the one in Thurgadin)." in actions
    assert "Kill Narandi the Wretched and loot his head." in actions
    assert any("turn in ring 9" in action and "Narandi's head" in action
               for action in actions)
    assert "Kromrif Spearman" not in actions
    assert "Kromrif Captain" not in actions


def test_structured_and_legacy_checklist_steps_survive_config_roundtrip(
        tmp_path):
    destination = tmp_path / "vantage.config.json"
    original_data = config.data
    original_filename = config._filename
    long_text = (
        "Travel to Burning Wood at 3234, 2871 and speak with Telin Darkforest. "
        + "Preserve this location and turn-in context exactly. " * 18)
    structured = json.dumps({
        "text": long_text, "depth": 2, "kind": "action",
        "group": "Acquire the Worn Note"}, ensure_ascii=False,
        separators=(",", ":"))
    legacy = "Give Faelin Bloodbriar the Worn Note."
    try:
        config._filename = str(destination)
        config.data = {"quests": {"checklist": {
            "title": "Druid Epic Quest",
            "steps": [structured, legacy, "{broken-json", 42,
                      "x" * (17 * 1024)],
            "checked": ["1234567890abcdef", None, {"bad": "key"}],
            "geometry": [80, 80, 380, 480],
        }}}
        config.verify_settings()
        saved_steps = config.data["quests"]["checklist"]["steps"]
        assert len(saved_steps) == 2
        assert json.loads(saved_steps[0])["text"] == long_text.strip()
        assert len(json.loads(saved_steps[0])["text"]) > 360
        assert saved_steps[1] == legacy
        assert config.data["quests"]["checklist"]["checked"] == [
            "1234567890abcdef"]
        config.save()

        config.load(str(destination))
        config.verify_settings()
        roundtrip = config.data["quests"]["checklist"]["steps"]
        assert json.loads(roundtrip[0])["text"] == long_text.strip()
        assert roundtrip[1] == legacy

        config.data = {"quests": ["malformed", "container"]}
        config.verify_settings()
        assert config.data["quests"]["checklist"]["steps"] == []
    finally:
        config.data = original_data
        config._filename = original_filename


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
    assert result["wrap_state"] == {
        "label_wrap": True, "horizontal_off": True,
        "accessible_full": True, "persisted_full": True}
    assert result["label_toggled"] is True
    assert result["keyboard_toggled"] is True
    assert result["rebuild_focus"] is True
    assert result["reworded_focus"] is True
    assert result["previous_focus"] is True
    assert result["stable_focus"] is True
    assert result["nested_name"].startswith(
        "Under Acquire the Worn Note, substep 1:")
    assert result["nested_description"] == (
        "Checklist hierarchy depth 1; parent group Acquire the Worn Note")
    assert result["return_focus"] is True
    assert result["progress_messages"] == [["2 of 2 steps complete", False]]


def test_quest_network_requests_timeout_retry_fallback_and_ignore_stale_replies(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", QUEST_NETWORK_RECOVERY_SCRIPT], cwd=ROOT,
        env=env, check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "catalog_recovered": True,
        "offline_fallback": True,
        "quest_cache_fallback": True,
        "quest_recovered": True,
        "stale_safe": True,
        "detail_settled": True,
    }
