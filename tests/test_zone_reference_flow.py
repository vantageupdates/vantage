"""Exercise the actual dropdown-to-request-to-table path and quest rewards."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from vantage.helpers.wiki_mirror_details import zone_reference_title
from vantage.parsers.quests import parse_quest_html


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name,title', [
    ('Temple Of Veeshan', 'Temple of Veeshan'),
    ("Velketor'S Labyrinth", "Velketor's Labyrinth"),
    ('the nektulos forest', 'Nektulos Forest'),
    ('castle mistmoore', 'Mistmoore Castle'),
    ('lost temple of cazic-thule', 'Cazic Thule (Zone)'),
    ('north qeynos', 'Qeynos'), ('south qeynos', 'Qeynos'),
    ('The Burning Wood', 'Burning Wood'), ("ak'anon", "Ak'Anon"),
    ('Chardok (Post-Revamp)', 'Chardok'),
])
def test_zone_reference_aliases_preserve_real_article_casing(name, title):
    assert zone_reference_title(name) == title


REWARDS = '''<table class="questTopTable"><tr><th>Reward:</th><td>
<a href="/Example_Sword">Example Sword</a></td></tr></table>
<h2>Quest Rewards</h2><ul><li>500 experience points</li><li>10 gold pieces</li>
<li>Faction with <a href="/Example_Guards">Example Guards</a> increases.</li></ul>
<div class="itemtopbg"><div class="itemtitle">Example Shield</div></div>
<div class="itemdata"><p>AC: 5<br>Class: ALL</p></div>
<h2>Walkthrough</h2><p>Give the document to the guard.</p>'''


def test_rewards_include_infobox_inline_item_and_non_item_rewards():
    result = parse_quest_html(REWARDS, 'Example Quest')
    assert set(result['rewards']) == {
        'Example Sword', 'Example Shield', '500 experience points',
        '10 gold pieces', 'Faction with Example Guards increases.'}
    assert {entry['name'] for entry in result['reward_links']} == {'Example Sword', 'Example Shield'}
    assert 'AC: 5' not in str(result['rewards'])


def test_rewards_do_not_silently_drop_items_after_twelve():
    result = parse_quest_html('<h2>Rewards</h2><ul>' + ''.join(
        f'<li><a href="/Example_{i}">Example {i}</a></li>' for i in range(17)) + '</ul>', 'Example Quest')
    assert len(result['rewards']) == 17


@pytest.mark.parametrize('content', [
    '<a href="/Example_Sword">Example Sword</a> and 500 experience points.',
    '<a href="/Example_Sword">Example Sword</a> and <a href="/Experience">experience</a>.',
    '<a href="/Example_Sword">Example Sword</a>, 10 gold pieces, and faction with <a href="/Example_Guards">Example Guards</a>.',
    'Faction with <a href="/Example_Guards">Example Guards</a> increases, and you receive <a href="/Example_Sword">Example Sword</a>.',
])
def test_mixed_reward_paragraph_keeps_item_link_without_linking_xp_or_faction(content):
    result = parse_quest_html('<h2>Rewards</h2><p>' + content + '</p>', 'Example Quest')
    assert {entry['target'] for entry in result['reward_links']} == {'Example Sword'}
    assert 'Example Sword' in result['rewards']
    assert any('experience' in text.lower() or 'faction' in text.lower() for text in result['rewards'])


def test_delayed_zone_retry_cannot_replace_a_new_selection(monkeypatch):
    from vantage.parsers import zones
    scheduled, started = [], []
    monkeypatch.setattr(zones.QTimer, 'singleShot', lambda _delay, callback: scheduled.append(callback))
    monkeypatch.setattr(zones, 'wiki_access', SimpleNamespace(status=lambda: ''))
    def unavailable(*_args, **_kwargs):
        raise ValueError('Unavailable fixture page')
    monkeypatch.setattr(zones, 'read_wiki_reply', unavailable)
    properties = {'zoneRequested': 'Chardok', 'zoneRequestId': 1, 'zoneAttempt': 0}
    reply = SimpleNamespace(property=lambda key: properties.get(key), deleteLater=lambda: None)
    status = SimpleNamespace(setText=lambda _text: None, setAccessibleName=lambda _text: None,
                             text=lambda: '')
    selected = ['Chardok']
    host = SimpleNamespace(sender=lambda: reply, _zone_reply=reply, _zone_request_id=1,
        zone_summary=status, _selected_wiki_name=lambda: selected[0],
        _start_zone_request=lambda *args: started.append(args))
    zones.Zones._zone_finished(host)
    assert len(scheduled) == 1
    host._zone_request_id = 2
    selected[0] = 'Nektulos Forest'
    scheduled[0]()
    assert not started
    host._zone_request_id = 1
    scheduled[0]()
    assert not started
    selected[0] = 'Chardok'
    scheduled[0]()
    assert len(started) == 1 and started[0][0] == 'Chardok'


NATIVE_FLOW = r'''
import json
from PySide6.QtCore import QIODevice, QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtTest import QTest
from vantage.helpers.application import VantageApp
from vantage.helpers.wiki_source import page_url
from vantage.parsers.quests import parse_quest_html

app = VantageApp([])
zones = app._parsers_dict['zones']
routes = {
 'chardok':'Chardok', 'temple of veeshan':'Temple of Veeshan',
 'the nektulos forest':'Nektulos Forest', 'north qeynos':'Qeynos',
 'south qeynos':'Qeynos', "velketor's labyrinth":"Velketor's Labyrinth"}
titles = {page_url(title): title for title in routes.values()}

class NativeReply(QNetworkReply):
    def __init__(self, request, parent):
        super().__init__(parent)
        self.setUrl(request.url())
        title = titles.get(request.url().toString())
        self.setAttribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute, 200 if title else 404)
        if not title:
            self.setError(QNetworkReply.NetworkError.ContentNotFoundError, 'Unrecognized article URL')
        self.body = (f'<h1 id="firstHeading">{title or "Missing"}</h1><div id="mw-content-text">'
            '<p>A synthetic zone reference.</p><table><tr><th>Unique Items:</th><td><a href="/Example_Blade">Example Blade</a></td></tr></table>'
            '<h2>What is in this zone?</h2><table><tr><th>NPC Name</th><th>Race</th><th>Class</th><th>Level</th><th>Location</th><th>Known Loot</th></tr>'
            '<tr><td><a href="/Example_Mob">Example Mob</a></td><td>Human</td><td>Warrior</td><td>20</td><td>1,2</td><td><a href="/Example_Blade">Example Blade</a></td></tr></table></div>').encode()
        self.open(QIODevice.OpenModeFlag.ReadOnly)
        QTimer.singleShot(0, self.finish)
    def readData(self, size):
        chunk,self.body=self.body[:size],self.body[size:]
        return chunk
    def bytesAvailable(self): return len(self.body)+super().bytesAvailable()
    def abort(self): pass
    def finish(self):
        self.setFinished(True)
        self.finished.emit()

class Network(QObject):
    def __init__(self): super().__init__(zones);self.urls=[]
    def get(self,request):
        self.urls.append(request.url().toString())
        return NativeReply(request,self)

zones._network = Network()
zones._select_zone('chardok')
zones._restore_zone_on_show = True
zones.show()
QTest.qWait(45)
assert len(zones._network.urls) == 1, 'Restored zone did not load when opened'
results=[]
for key,title in routes.items():
    index=zones.zone_selector.findData(key)
    assert index>=0
    zones.zone_selector.setCurrentIndex(index)
    QTest.qWait(45)
    results.append({'zone':key,'selected':zones._selected_zone_name(),
        'url':zones._network.urls[-1], 'mobs':zones.mob_table.rowCount(),
        'items':zones.item_table.rowCount(),'loading':zones._zone_reply is not None,
        'reload':zones.zone_load_button.isEnabled(),'map':zones.zone_map_button.isEnabled()})
quests=app._parsers_dict['quests']
record=parse_quest_html('<h2>Rewards</h2><ul><li><a href="/Example_Blade">Example Blade</a></li><li>500 experience points</li></ul><h2>Walkthrough</h2><p>Give the document to the guard.</p>','Example Quest')
quests._show_quest(record,announce=False)
opened=[]
app._parsers_dict['market']._show_wiki_item_name=lambda target:opened.append(target)
quests.rewards.anchorClicked.emit(QUrl('vantage://item/Example%20Blade'))
assert quests._open_reward_link(QUrl('https://evil.test/Example')) is False
reward_text, reward_html = quests.rewards.toPlainText(), quests.rewards.toHtml()
legacy = dict(record, rewards=['500 experience points', 'Faction with Example Guards increases.', '10 gold pieces', 'Example Blade'])
legacy.pop('reward_links')
quests._show_quest(legacy,announce=False)
assert '500 experience points' in quests.rewards.toPlainText()
assert 'vantage://item/' not in quests.rewards.toHtml(), 'Untyped cached rewards became fabricated item links'
print(json.dumps({'zones':results,'reward_text':reward_text,
    'reward_html':reward_html,'tabs':[quests.tabs.tabText(i) for i in range(quests.tabs.count())],
    'opened':opened}))
zones._cancel_network_requests()
app.quit()
'''


def test_native_zone_selection_loads_html_and_quest_rewards_open_item_details(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1',
               VANTAGE_DATA_DIR=str(tmp_path/'profile'), PYTHONPATH=str(ROOT/'src'))
    result = subprocess.run([sys.executable, '-B', '-c', NATIVE_FLOW], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(data['zones']) == 6
    for row in data['zones']:
        assert row['mobs'] == row['items'] == 1, row
        assert row['selected'] == row['zone'], row
        assert not row['loading'] and row['reload'] and row['map'], row
        assert '&redirects=' not in row['url']
    assert 'Rewards' in data['tabs']
    assert 'Example Blade' in data['reward_text'] and '500 experience points' in data['reward_text']
    assert 'vantage://item/500' not in data['reward_html']
    assert data['opened'] == ['Example Blade']
