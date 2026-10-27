"""Public refreshes stay scoped and do not crowd out current selections."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from vantage.helpers import opendkp
from vantage.parsers.opendkp import OpenDKP


class Reply:
    def __init__(self, request):
        self.path = request.url().path() + "?" + request.url().query()
        self.payload, self.status = {}, 200
        self.aborted, self.deleted, self.read = False, False, False
        self.callbacks = []
        self.finished = SimpleNamespace(connect=self.callbacks.append)

    def attribute(self, _key):
        return self.status

    def readAll(self):
        self.read = True
        return json.dumps(self.payload).encode()

    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError if self.aborted
                else QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return "Synthetic response"

    def finish(self, payload=None):
        self.payload = payload or {}
        for callback in self.callbacks:
            callback()

    def abort(self):
        self.aborted = True
        self.finish()

    def deleteLater(self):
        self.deleted = True


@pytest.fixture
def client(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(opendkp, "read_refresh_token", lambda _slug: ("", ""))
    value = opendkp.OpenDkpClient()
    requests, responses, failures = [], [], []

    def request(request, *_args):
        reply = Reply(request)
        requests.append(reply)
        return reply

    value.network = SimpleNamespace(get=request, post=request)
    value.response.connect(lambda *args: responses.append(args))
    value.failed.connect(lambda *args: failures.append(args))
    value.set_guild("first")
    yield SimpleNamespace(value=value, requests=requests, responses=responses,
                          failures=failures, app=app)
    value.close()
    value.deleteLater()
    app.processEvents()


def test_identical_public_requests_share_one_pending_reply_then_refresh_again(client):
    f = client
    first = f.value._request("dkp", "GET", "/clients/first/dkp")
    assert f.value._request("dkp", "GET", "/clients/first/dkp") is first
    assert len(f.requests) == 1 and f.value._busy_count == 1
    first.finish([{"CharacterName": "Current"}])
    assert len(f.responses) == 1 and f.value._busy_count == 0
    assert f.value._request("dkp", "GET", "/clients/first/dkp") is not first
    assert len(f.requests) == 2


def test_guild_switch_cancels_all_old_public_requests_without_failure(client):
    f = client
    f.value.load_guild("first")
    f.value.refresh_public()
    old = list(f.requests)
    f.value.load_guild("second")
    assert all(reply.aborted for reply in old)
    assert not f.failures and not f.responses
    assert f.value._busy_count == 1  # Only the new guild request remains.
    for reply in old:
        reply.finish({"Name": "Old guild", "Models": [{"CurrentDKP": 999}]})
    assert not f.failures and not f.responses
    f.requests[-1].finish({"Name": "Second"})
    assert f.value.client_details == {"Name": "Second"}
    assert f.responses == [("client", {"Name": "Second"})]
    assert f.value._busy_count == 0


def test_public_reply_from_a_removed_guild_is_dropped_before_decoding(client):
    f = client
    old = f.value._request("dkp", "GET", "/clients/first/dkp")
    f.value.slug = ""
    old.finish([{"CharacterName": "Old"}])
    assert not old.read and old.deleted
    assert not f.responses and not f.failures and f.value._busy_count == 0


def test_repeat_refresh_keeps_pages_in_flight_and_does_not_duplicate_public_reads(client):
    f = client
    f.value.refresh_public()
    loot = next(reply for reply in f.requests if "/items?" in reply.path)
    loot.finish({"Items": [{"TransactionId": 1}], "TotalItems": 2,
                 "TotalPages": 2, "CurrentPage": 1})
    f.app.processEvents()
    generation = f.value.loot_generation
    count = len(f.requests)
    f.value.refresh_public()
    assert len(f.requests) == count == 6
    assert f.value.loot_generation == generation
    current = f.requests[-1]
    assert "page=2" in current.path and not current.aborted
    current.finish({"Items": [{"TransactionId": 2}], "TotalItems": 2,
                    "TotalPages": 2, "CurrentPage": 2})
    assert f.responses[-1][0] == "items"
    assert [row["TransactionId"] for row in f.responses[-1][1]["Items"]] == [1, 2]


def test_new_character_history_cancels_old_selection_but_preserves_attendance(client):
    f = client
    f.value.fetch_character_details(1, 90, "old")
    f.value.fetch_history_raid(9, "old")
    old = list(f.requests)
    f.value.fetch_attendance(3, request_token="attendance")
    attendance = f.requests[-1]
    f.value.fetch_character_details(2, 30, "current")
    assert all(reply.aborted for reply in old)
    assert not attendance.aborted
    assert not f.failures and not f.responses
    assert f.value._busy_count == 5
    f.value.fetch_character_details(2, 30, "current")
    assert len(f.requests) == 10 and f.value._busy_count == 5
    f.requests[-1].finish({"Raids": []})
    assert f.responses == [("character_raids|current|2", {"Raids": []})]


def test_public_coalescing_does_not_change_authorized_requests_or_writes(client):
    f = client
    for _ in range(2):
        f.value._request("active_auctions", "GET", "/clients/first/auctions/active",
                         headers={"Authorization": "Bearer synthetic"})
        f.value._request("place_bid", "POST", "/clients/first/bids", {"Value": 1})
    f.value._cancel_public_requests()
    assert len(f.requests) == 4 and not any(reply.aborted for reply in f.requests)


def test_refresh_updates_finished_standings_while_guild_loot_continues(client):
    f = client
    f.value.refresh_public()
    standings = f.requests[0]
    standings.finish([{"CharacterName": "Hero", "CurrentDKP": 1}])
    loot = next(reply for reply in f.requests if "/items?" in reply.path)
    f.value.refresh_public()
    assert len(f.requests) == 6 and not loot.aborted
    f.requests[-1].finish([{"CharacterName": "Hero", "CurrentDKP": 2}])
    assert f.responses[-1][1][0]["CurrentDKP"] == 2


def test_refresh_stays_available_during_large_background_requests():
    enabled = []
    harness = SimpleNamespace(client=SimpleNamespace(slug="guild"),
        progress=SimpleNamespace(setVisible=lambda _visible: None,
                                 setAccessibleName=lambda _name: None),
        refresh_button=SimpleNamespace(setEnabled=enabled.append),
        _update_raid_action_state=lambda: None)
    OpenDKP._busy_changed(harness, True, "guild_loot|1|guild|50")
    assert enabled == [True]
    harness.client.slug = ""
    OpenDKP._busy_changed(harness, False, "items")
    assert enabled == [True, False]


def _history_harness(client):
    selected = {"character": 1, "days": 90}
    harness = SimpleNamespace(
        client=client, _history_identity=None, _history_token="",
        _history_sources_ready=set(), _history_details={},
        _history_detail_status="", _history_states={},
        _datasets={key: [] for key in ("character_dkp", "character_items",
                                      "character_adjustments", "character_raids")},
        character_selector=SimpleNamespace(currentData=lambda: selected["character"]),
        history_view=SimpleNamespace(period=SimpleNamespace(
            currentData=lambda: selected["days"])),
        _update_overview=lambda: None, _adjustments_loaded=False,
        _guild_name=lambda: "First", _set_status=lambda *_args: None)
    harness._load_character_history = lambda **kwargs: OpenDKP._load_character_history(
        harness, **kwargs)
    return harness, selected


def test_repeated_refresh_keeps_same_personal_requests_and_generation(client):
    f = client
    harness, _selected = _history_harness(f.value)
    harness._load_character_history(force=True)
    token = harness._history_token
    personal = list(f.requests)
    assert len(personal) == 4 and f.value.character_history_pending(1, token)

    for _ in range(3):
        OpenDKP._refresh_all(harness)

    assert harness._history_token == token
    assert len(f.requests) == 9  # Four personal plus five public reads.
    assert all(not reply.aborted for reply in personal)
    assert not f.value.character_history_pending(2, token)
    assert not f.value.character_history_pending(1, "old-token")


def test_partial_refresh_retries_finished_endpoints_without_aborting_pending(client):
    f = client
    harness, _selected = _history_harness(f.value)
    harness._load_character_history(force=True)
    token = harness._history_token
    original = list(f.requests)
    original[0].finish({"Models": []})
    original[1].status = 503
    original[1].finish({"message": "Temporarily unavailable"})
    details = {"raid": {"Name": "Existing detail"}}
    harness._history_details = details

    harness._load_character_history(force=True)

    assert len(f.requests) == 6  # Retry only the two that finished.
    assert harness._history_token == token and harness._history_details is details
    assert all(not reply.aborted for reply in original[2:])
    assert f.requests[4].path == original[0].path
    assert f.requests[5].path == original[1].path
    # Once the previous reads finish, explicit refresh starts a fresh generation.
    for reply in list(f.value._replies):
        reply.finish({"Models": []})
    assert not f.value.character_history_pending(1, token)
    harness._load_character_history(force=True)
    assert len(f.requests) == 10
    assert harness._history_token != token and harness._history_details == {}


@pytest.mark.parametrize("changed,value", [("character", 2), ("days", 30)])
def test_different_character_or_period_still_invalidates_pending_history(client, changed, value):
    f = client
    harness, selected = _history_harness(f.value)
    harness._load_character_history(force=True)
    token = harness._history_token
    old = list(f.requests)
    selected[changed] = value

    harness._load_character_history(force=True)

    assert harness._history_token != token
    assert len(f.requests) == 8 and all(reply.aborted for reply in old)
    assert not f.failures
