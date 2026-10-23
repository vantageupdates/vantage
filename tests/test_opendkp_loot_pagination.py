"""Guild loot is complete, asynchronous and isolated from real network/auth."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from vantage.helpers import opendkp


class Reply:
    def __init__(self, operation, path):
        self.operation, self.path = operation, path
        self.payload, self.status, self.aborted, self.deleted = {}, 200, False, False

    def attribute(self, _key):
        return self.status

    def readAll(self):
        return json.dumps(self.payload).encode()

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def errorString(self):
        return "Synthetic failure"

    def abort(self):
        self.aborted = True

    def deleteLater(self):
        self.deleted = True


@pytest.fixture
def fixture(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(opendkp, "read_refresh_token", lambda _slug: ("", ""))
    client = opendkp.OpenDkpClient()
    requests, responses, failures, progress, busy = [], [], [], [], []

    def request(operation, method, path, *args, **kwargs):
        assert method == "GET" and not args and not kwargs
        reply = Reply(operation, path)
        requests.append(reply)
        client._replies[reply] = {"operation": operation, "kind": "api", "auth": False}
        client._begin_busy(operation)
        return reply

    monkeypatch.setattr(client, "_request", request)
    client.response.connect(lambda *args: responses.append(args))
    client.failed.connect(lambda *args: failures.append(args))
    client.loot_progress.connect(lambda *args: progress.append(args))
    client.busy_changed.connect(lambda *args: busy.append(args))
    client.set_guild("example")

    def deliver(payload, status=200, reply=None):
        reply = reply or requests[-1]
        reply.payload, reply.status = payload, status
        client._reply_finished(reply)

    yield SimpleNamespace(client=client, requests=requests, responses=responses,
                          failures=failures, progress=progress, busy=busy,
                          deliver=deliver, events=app.processEvents)
    client.close()
    QCoreApplication.processEvents()
    client.deleteLater()


def rows(start, count):
    return [{"TransactionId": index, "ItemName": "Repeated legitimate item",
             "ItemID": 42, "GameItemId": 42, "CharacterId": 7, "DKP": 10}
            for index in range(start, start + count)]


def page(data, current, total, pages):
    return {"Items": data, "CurrentPage": current, "TotalItems": total, "TotalPages": pages}


def test_all_pages_over_500_publish_once_and_short_last_page_completes(fixture):
    f = fixture
    f.client.fetch_all_guild_loot()
    assert f.requests[-1].path.endswith("page=1&ItemsPerPage=500")
    f.deliver(page(rows(1, 500), 1, 1203, 3))
    assert not f.responses and len(f.requests) == 1  # scheduled, not a blocking loop
    f.events()
    assert f.requests[-1].path.endswith("page=2&ItemsPerPage=500")
    f.deliver(page(rows(501, 500), 2, 1203, 3)); f.events()
    assert not f.responses and all(value for value, _ in f.busy)
    f.deliver(page(rows(1001, 203), 3, 1203, 3)); f.events()
    assert len(f.requests) == 3 and len(f.responses) == 1
    operation, payload = f.responses[0]
    assert operation == "items" and len(payload["Items"]) == 1203
    assert payload["Complete"] and payload["GuildSlug"] == "example"
    assert payload["Generation"] == f.client.loot_generation
    assert [value[1]["loaded"] for value in f.progress] == [0, 500, 1000, 1203]
    assert f.progress[-1][1]["complete"] and not f.busy[-1][0]


def test_legacy_short_pages_continue_until_empty_without_a_fixed_cap(fixture):
    f = fixture; f.client.fetch_all_guild_loot()
    for index in range(4):
        f.deliver(rows(index * 300 + 1, 300)); f.events()
        assert not f.responses
    f.deliver([]); f.events()
    assert len(f.responses[0][1]["Items"]) == 1200
    assert len(f.requests) == 5


def test_page_failure_keeps_last_complete_payload_and_retry_starts_fresh(fixture):
    f = fixture; f.client.fetch_all_guild_loot()
    f.deliver(page(rows(1, 1), 1, 1, 1))
    previous = f.responses[-1]
    f.client.fetch_all_guild_loot()
    f.deliver(page(rows(1, 500), 1, 700, 2)); f.events()
    f.deliver({"message": "Unavailable"}, status=503); f.events()
    assert f.responses == [previous]
    assert f.failures[-1][0] == "items" and f.failures[-1][2] == 503
    assert "previous complete history is unchanged" in f.failures[-1][1]
    f.client.fetch_all_guild_loot()
    assert f.requests[-1].path.endswith("page=1&ItemsPerPage=500")
    f.deliver(page(rows(1, 2), 1, 2, 1))
    assert len(f.responses) == 2 and len(f.responses[-1][1]["Items"]) == 2


@pytest.mark.parametrize("replacement", ["guild", "refresh", "close"])
def test_stale_requests_and_queued_pages_cannot_publish_after_cancellation(fixture, replacement):
    f = fixture; f.client.fetch_all_guild_loot()
    stale = f.requests[-1]
    if replacement == "guild":
        f.client.set_guild("other"); f.client.fetch_all_guild_loot()
    elif replacement == "refresh":
        f.client.fetch_all_guild_loot()
    else:
        f.client.close()
    assert stale.aborted
    current_requests = len(f.requests)
    f.deliver(page(rows(1, 500), 1, 501, 2), reply=stale); f.events()
    assert not f.responses and not f.failures and len(f.requests) == current_requests
    if replacement != "close":
        f.deliver(page(rows(900, 1), 1, 1, 1)); f.events()
        assert f.responses[-1][1]["Items"][0]["TransactionId"] == 900
    f.client.fetch_all_guild_loot()
    f.deliver(page(rows(1, 500), 1, 501, 2))
    count = len(f.requests); f.client.close(); f.events()
    assert len(f.requests) == count


def test_redundant_finished_notification_does_not_append_or_publish_twice(fixture):
    f = fixture; f.client.fetch_all_guild_loot(); reply = f.requests[-1]
    f.deliver(page(rows(1, 1), 1, 1, 1), reply=reply)
    f.deliver(page(rows(1, 1), 1, 1, 1), reply=reply)
    assert len(f.responses) == 1 and not f.failures


def test_only_true_purchase_ids_deduplicate_and_unidentified_repeats_remain(fixture):
    f = fixture; f.client.fetch_all_guild_loot()
    unidentified = {"ItemID": 42, "GameItemId": 42, "ItemName": "Helm", "DKP": 10}
    f.deliver({"Items": rows(1, 2), "CurrentPage": 1, "TotalItems": 5, "TotalPages": 2}); f.events()
    f.deliver(page([*rows(2, 2), unidentified, dict(unidentified)], 2, 5, 2))
    result = f.responses[-1][1]["Items"]
    assert len(result) == 5 and result[-2:] == [unidentified, unidentified]


@pytest.mark.parametrize("bad", ["repeat", "wrong_page", "changed_total", "early_empty", "invalid", "conflict", "no_new"])
def test_incomplete_or_nonadvancing_pages_fail_without_partial_publication(fixture, bad):
    f = fixture; f.client.fetch_all_guild_loot()
    f.deliver(page(rows(1, 2), 1, 4, 2)); f.events()
    payload = {
        "repeat": page(rows(1, 2), 2, 4, 2),
        "wrong_page": page(rows(3, 2), 1, 4, 2),
        "changed_total": page(rows(3, 2), 2, 5, 2),
        "early_empty": page([], 2, 4, 2),
        "invalid": {"message": "Not a purchase page"},
        "conflict": page([{**rows(1, 1)[0], "DKP": 99}, *rows(3, 1)], 2, 4, 2),
        "no_new": page(rows(1, 1), 2, 4, 2),
    }[bad]
    f.deliver(payload); f.events()
    assert not f.responses and len(f.failures) == 1 and len(f.requests) == 2


def test_refresh_public_routes_only_guild_loot_through_pagination(fixture):
    f = fixture; assert f.client.refresh_public()
    assert [reply.operation.split("|")[0] for reply in f.requests] == ["dkp", "characters", "raids", "guild_loot", "auctions"]
    assert f.requests[2].path.endswith("/raids?page=1&ItemsPerPage=250")
    assert f.requests[-1].path.endswith("/auctions?page=1&ItemsPerPage=500")


def test_all_reported_pages_are_required_even_without_purchase_total(fixture):
    f = fixture; f.client.fetch_all_guild_loot()
    f.deliver({"Items": rows(1, 2), "CurrentPage": 1, "TotalPages": 3}); f.events()
    f.deliver({"Items": [], "CurrentPage": 2, "TotalPages": 3})
    assert not f.responses and "reported pages" in f.failures[-1][1]


def test_large_history_has_no_page_count_cap_and_yields_between_pages(fixture):
    f = fixture; f.client.fetch_all_guild_loot()
    for index in range(61):
        count = min(500, 30362 - index * 500)
        f.deliver(page(rows(index * 500 + 1, count), index + 1, 30362, 61))
        assert len(f.requests) == index + 1
        if index < 60:
            assert not f.responses
        f.events()
    assert len(f.responses) == 1 and len(f.responses[0][1]["Items"]) == 30362
    assert len(f.requests) == 61 and not f.failures
