"""Blocked Wiki requests must leave spell facts and saved guides usable."""
import datetime
import hashlib
import json

from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication
import pytest

import vantage.helpers.spell_library as library
import vantage.helpers.wiki_access as access


class Finished:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in tuple(self.callbacks):
            callback()


class Reply:
    def __init__(self, payload=b'', status=200, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.headers = headers or {}
        self.finished = Finished()
        self.running = True
        self.deleted = False

    def readAll(self):
        payload, self.payload = self.payload, b''
        return payload

    def bytesAvailable(self):
        return len(self.payload)

    def attribute(self, _attribute):
        return self.status

    def rawHeader(self, key):
        return self.headers.get(key, b'')

    def error(self):
        return (QNetworkReply.NetworkError.ContentAccessDenied if self.status >= 400
                else QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return 'Error transferring https://wiki.project1999.com/api.php?private-query - 403'

    def isRunning(self):
        return self.running

    def abort(self):
        self.running = False
        self.finished.emit()

    def complete(self, payload, status=200, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status, self.headers, self.running = status, headers or {}, False
        self.finished.emit()

    def deleteLater(self):
        self.deleted = True


class Network:
    def __init__(self):
        self.requests = []

    def get(self, request):
        reply = Reply()
        self.requests.append((request, reply))
        return reply


@pytest.fixture
def panel(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    gate = access.WikiAccess(clock=lambda: 100.0)
    monkeypatch.setattr(access, 'wiki_access', gate)
    monkeypatch.setattr(library, 'wiki_access', gate)
    def cache(name, server='Green'):
        digest = hashlib.sha256((server + name).encode()).hexdigest()
        return tmp_path / (digest + '.json')
    monkeypatch.setattr(library, '_cache_path', cache)
    monkeypatch.setattr(library, '_skills_cache_path', cache)
    monkeypatch.setattr(library, '_skill_detail_cache_path', cache)
    dialog = library.SpellLibraryDialog()
    dialog._network = Network()
    monkeypatch.setattr(dialog, 'isVisible', lambda: True)
    dialog._selection_timer.stop()
    dialog._skill_selection_timer.stop()
    yield dialog, gate, cache
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def select(dialog, name='Burst of Flame'):
    dialog._pending = dialog._entries_by_name[name.casefold()]
    dialog._load_pending()
    return dialog._pending


def challenge(reply):
    reply.complete(b'<!DOCTYPE html><title>Just a moment...</title>', 403,
                   {b'cf-mitigated': b'challenge'})


def saved_record(name='Burst of Flame'):
    return {'name': name, 'wiki_html': '<p>Previously saved spell details.</p>',
            'acquisition': 'A saved merchant', 'auction': {},
            'fetched_at': '2020-01-01T00:00:00+00:00'}


def test_challenge_retains_local_spell_facts_and_stops_followup_requests(panel):
    dialog, gate, _cache = panel
    entry = select(dialog)
    challenge(dialog._network.requests[-1][1])
    body = dialog.body.toPlainText()
    assert entry.levels_text in body
    assert f'Mana: {entry.mana}' in body and 'Cast time:' in body
    assert 'Loading' not in body
    assert 'LOCAL SPELL DATA AVAILABLE' in dialog.source.text()
    assert 'api.php' not in dialog.source.text() + dialog.source.toolTip()
    assert gate.status()
    dialog._refresh_current()
    dialog._refresh_current()
    select(dialog, 'Clarity')
    assert len(dialog._network.requests) == 1
    assert 'Clarity' in dialog.body.toPlainText()
    assert dialog.refresh_button.isEnabled()


@pytest.mark.parametrize('payload,status', [
    (b'<!DOCTYPE html><title>Just a moment...</title>', 403),
    ({'parse': {'text': {'*': ''}, 'wikitext': {'*': ''}}}, 200),
    ({'error': {'code': 'missingtitle'}}, 200),
])
def test_failed_refresh_preserves_saved_spell_card_and_file(panel, payload, status):
    dialog, _gate, cache = panel
    path = cache('Burst of Flame')
    original = json.dumps(saved_record()).encode()
    path.write_bytes(original)
    select(dialog)
    before = dialog.body.toHtml()
    dialog._network.requests[-1][1].complete(payload, status)
    assert dialog.body.toHtml() == before
    assert path.read_bytes() == original
    assert 'SAVED SPELL DETAILS AVAILABLE' in dialog.source.text()
    assert 'api.php' not in dialog.source.text()


def test_valid_response_saves_atomic_cache_metadata(panel):
    dialog, _gate, cache = panel
    select(dialog)
    dialog._network.requests[-1][1].complete({'parse': {
        'text': {'*': '<p>A spell description.</p>'},
        'wikitext': {'*': 'A spell description.'}}})
    record = json.loads(cache('Burst of Flame').read_text())
    assert record['_wiki_cache']['source'] == 'Project 1999 Wiki'
    assert 'A spell description.' in dialog.body.toPlainText()
    assert 'UPDATED NOW' in dialog.source.text()


def test_cached_selection_invalidates_older_reply(panel):
    dialog, _gate, cache = panel
    select(dialog)
    old = dialog._network.requests[-1][1]
    old_generation = dialog._request_generation
    old_entry = dialog._current
    record = saved_record('Clarity')
    record['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache('Clarity').write_text(json.dumps(record))
    select(dialog, 'Clarity')
    before = dialog.body.toHtml()
    dialog._finished(Reply({'parse': {'text': {'*': 'Old'}, 'wikitext': {'*': 'Old'}}}),
                     old_entry, old_generation)
    assert dialog.body.toHtml() == before and dialog._current.name == 'Clarity'
    assert old.deleted and not old.running
    assert dialog.refresh_button.isEnabled()


def test_shared_pause_preserves_class_table_even_on_force_refresh(panel):
    dialog, gate, cache = panel
    name = str(dialog.skill_class_filter.currentData())
    record = {'class': name, 'skills': [
        {'level': 4, 'name': 'Meditate', 'category': 'Casting', 'trained': 'Yes',
         'cap_50': '235', 'cap_60': '252', 'target': 'Skill Meditate'}]}
    cache(name).write_text(json.dumps(record))
    gate.pause('Wiki access temporarily restricted', challenge=True)
    assert dialog._load_selected_class_skills(force=True)
    assert dialog.skill_table.rowCount() == 1
    assert dialog.skill_table.item(0, 1).text() == 'Meditate'
    assert dialog._network.requests == []
    assert 'saved skills available' in dialog.skill_summary.text()


def test_linked_page_uses_shared_pause_without_raw_network_error(panel):
    dialog, gate, _cache = panel
    gate.pause('Wiki access temporarily restricted', challenge=True)
    dialog._fetch_linked_page('Old Sebilis')
    assert not dialog._network.requests
    assert 'refresh paused' in dialog.body.toPlainText().casefold()
    assert 'api.php' not in dialog.body.toPlainText() + dialog.source.text()


def test_linked_page_challenge_sets_pause_and_allows_back_to_saved_spell(panel):
    dialog, gate, cache = panel
    record = saved_record()
    record['fetched_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache('Burst of Flame').write_text(json.dumps(record))
    select(dialog)
    dialog._fetch_linked_page('Old Sebilis')
    challenge(dialog._network.requests[-1][1])
    assert gate.status()
    assert 'api.php' not in dialog.body.toPlainText() + dialog.source.text()
    dialog._return_to_spell()
    assert 'Previously saved spell details.' in dialog.body.toPlainText()
    assert len(dialog._network.requests) == 1


def test_skill_guide_challenge_preserves_class_facts(panel):
    dialog, gate, _cache = panel
    skill = {'level': 4, 'name': 'Meditate', 'category': 'Casting', 'trained': 'Yes',
             'cap_50': '235', 'cap_60': '252', 'target': 'Skill Meditate'}
    dialog._skills_data = {'class': 'Enchanter'}
    dialog._current_skill = skill
    dialog._load_skill_detail()
    before = dialog.skill_body.toPlainText()
    challenge(dialog._network.requests[-1][1])
    assert gate.status()
    assert dialog.skill_body.toPlainText() == before
    assert '235' in before and '252' in before and 'level 4' in before
    assert 'api.php' not in dialog.skill_source.text() + dialog.skill_source.toolTip()
    dialog._load_skill_detail()
    assert len(dialog._network.requests) == 1


def test_large_response_keeps_existing_details(panel):
    dialog, _gate, cache = panel
    cache('Burst of Flame').write_text(json.dumps(saved_record()))
    select(dialog)
    before = dialog.body.toHtml()
    dialog._network.requests[-1][1].complete(b'x' * 2_000_001)
    assert dialog.body.toHtml() == before
    assert 'SAVED SPELL DETAILS AVAILABLE' in dialog.source.text()
