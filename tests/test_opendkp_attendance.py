"""Public character history fixtures match the real OpenDKP response shape."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QListWidget, QPushButton, QTabWidget, QWidget

from vantage.helpers.opendkp import OpenDkpClient
from vantage.helpers.raid_ledger import character_raid_attendance
from vantage.parsers.opendkp import OpenDKP, _attendance_event_name


def raid(raid_id=1, attended=1, value=None):
    tick = {"TickId": raid_id, "Attended": attended}
    if value is not None:
        tick["Value"] = value
    return {"RaidId": raid_id, "RaidName": f"Event {raid_id}",
            "PoolName": "Main", "Timestamp": "2026-09-27T14:07:00Z", "Ticks": [tick]}


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])

    class Harness(OpenDKP):
        event = QWidget.event
        resizeEvent = QWidget.resizeEvent
        closeEvent = QWidget.closeEvent
        enterEvent = QWidget.enterEvent
        leaveEvent = QWidget.leaveEvent
        showEvent = QWidget.showEvent
        def __init__(self):
            QWidget.__init__(self)
            self.raid_workspace_tabs = QTabWidget(self)
            self.requests = []
            self._save_profile = lambda **_kwargs: None
            self.client = SimpleNamespace(
                slug="example", fetch_attendance=lambda *args: self.requests.append(args) or True,
                fetch_attendance_detail=lambda *args: self.requests.append(args) or True)
            self._build_attendance_workspace()

    widget = Harness()
    widget.attendance_character.addItem("Mindflux", 163372)
    widget.attendance_from.setDate(QDate(2026, 9, 1))
    widget.attendance_to.setDate(QDate.currentDate())
    yield widget
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("payload,expected", [
    (raid(), (1, None)), (raid(value=0.5), (1, 0.5)),
    (raid(attended=0), (0, 0)), (raid(attended="false"), (0, 0)),
    (raid(attended="true", value=2), (1, 2)),
    ({"Name": "Guild-only event"}, (None, None)),
    ({"Ticks": [{"Attended": "unknown"}]}, (None, None)),
    ({"Ticks": []}, (None, None)),
])
def test_attendance_requires_explicit_tick_evidence(payload, expected):
    assert character_raid_attendance(payload) == expected


def test_direct_request_is_public_and_bounds_lookback():
    requests = []
    client = SimpleNamespace(slug="any-guild", _request=lambda *args: requests.append(args))
    assert OpenDkpClient.fetch_attendance(client, 42, 999999, "token")
    assert requests == [("attendance|token", "GET",
                         "/clients/any-guild/characters/42/raids?lookback=3650")]


def test_attendance_without_local_raid_filters_nonattendees_and_unknown(panel):
    assert panel._search_attendance()
    assert panel.requests[0][0] == 163372
    token = panel._attendance_token
    panel._response(f"attendance|{token}", [raid(), raid(2, 0), {"RaidName": "Unknown"}])
    assert panel.attendance_table.rowCount() == 1
    assert panel.attendance_table.item(0, 1).text() == "Event 1"
    assert panel.attendance_table.item(0, 4).text() == "—"
    assert "1 attended raids" in panel.attendance_status.text()
    assert "not counted" in panel.attendance_status.text()
    assert panel.attendance_search.isEnabled()


def test_searches_all_rows_before_pagination_not_first_100(panel):
    panel._search_attendance()
    panel._response(f"attendance|{panel._attendance_token}", [raid(i) for i in range(1, 758)])
    assert len(panel._attendance_rows) == 757
    assert panel.attendance_table.rowCount() == 250
    assert "of 4" in panel.attendance_page_label.text()
    panel._attendance_move(3)
    assert panel.attendance_table.rowCount() == 7
    panel.attendance_query.setText("Event 757")
    assert panel.attendance_table.rowCount() == 1
    assert panel.attendance_table.item(0, 1).text() == "Event 757"


def test_stale_search_guild_switch_and_character_edit_ignored(panel):
    panel._search_attendance()
    old = panel._attendance_token
    panel._search_attendance()
    panel._response(f"attendance|{old}", [raid()])
    assert not panel._attendance_rows
    current = panel._attendance_token
    panel.client.slug = "other"
    panel._response(f"attendance|{current}", [raid()])
    assert not panel._attendance_rows
    panel.client.slug = "example"
    panel.attendance_character.setEditText("Someone else")
    panel._response(f"attendance|{current}", [raid()])
    assert not panel._attendance_rows
    assert panel.attendance_search.isEnabled()


def test_failure_retries_and_empty_is_not_failure(panel):
    panel._search_attendance()
    panel._failed(f"attendance|{panel._attendance_token}", "Timeout", 0)
    assert "Try Search attendance again" in panel.attendance_status.text()
    assert panel.attendance_search.isEnabled()
    panel._search_attendance()
    panel._response(f"attendance|{panel._attendance_token}", [])
    assert "0 attended raids" in panel.attendance_status.text()
    panel._search_attendance()
    panel._response(f"attendance|{panel._attendance_token}", {"Error": "bad"})
    assert "response unavailable" in panel.attendance_status.text()


def test_selected_details_resolve_dkp_from_public_ticks(panel):
    panel._search_attendance()
    token = panel._attendance_token
    panel._response(f"attendance|{token}", [raid()])
    panel.attendance_table.selectRow(0)
    assert panel._check_attendance_detail()
    panel._response(f"attendance_detail|{token}|1", {"Ticks": [
        {"Value": 0.5, "Characters": [{"Name": "Mindflux"}]},
        {"Value": 8, "Characters": [{"Name": "Someone else"}]}]})
    assert panel.attendance_table.item(0, 4).text() == "0.5"
    assert "1 verified ticks" in panel.attendance_status.text()


def test_invalid_dates_and_unresolved_character_make_no_request(panel):
    panel.attendance_from.setDate(QDate.currentDate().addDays(1))
    assert panel._search_attendance() is False
    panel.attendance_from.setDate(QDate(2026, 9, 1))
    panel.attendance_character.setEditText("Not a guild character")
    assert panel._search_attendance() is False
    assert panel.requests == []


def test_readable_event_keeps_original_evidence_in_tooltip(panel):
    payload = raid()
    payload['RaidName'] = '9-27 14:07 09-27 Vindi PM no kill https://discord.com/channels/123'
    assert _attendance_event_name(payload) == 'Vindi PM no kill'
    panel._search_attendance()
    panel._response(f"attendance|{panel._attendance_token}", [payload])
    assert panel.attendance_table.item(0, 1).toolTip() == payload['RaidName']
    panel.attendance_query.setText('channels/123')
    assert panel.attendance_table.rowCount() == 1


def test_overview_uses_personal_evidence_and_full_character_directory(panel):
    page = panel._build_overview()
    panel._profile = lambda: {'character_id': 163372}
    panel._datasets = {
        'dkp': [{'CharacterId': 163372, 'CharacterName': 'Mindflux', 'CurrentDKP': 42}],
        'characters': [{'CharacterId': 999, 'Name': 'NoDkpYet'}],
        'character_items': [], 'items': [],
        'character_raids': [raid(i) for i in range(1, 202)] + [raid(999, 0)],
        'raids': [raid(888)]}
    panel._populate_characters()
    assert panel.attendance_character.findText('NoDkpYet') >= 0
    assert panel.character_raids.rowCount() == 201
    assert panel.character_raids.item(0, 1).text().startswith('Event')
    assert panel.character_raids.item(0, 3).text() == '—'
    panel._datasets['character_raids'] = []
    panel._update_overview()
    assert panel.character_raids.rowCount() == 0  # no guild fallback masquerading as attendance
    page.deleteLater()


def add_alts(panel):
    panel.attendance_character.addItem('Wildflux', 2)
    panel.attendance_character.addItem('Fistflux', 3)
    panel.attendance_character.addItem('Spiritflux', 4)
    panel._attendance_alts = [{'character_id': i, 'name': name} for i, name in
                              ((2, 'Wildflux'), (3, 'Fistflux'), (4, 'Spiritflux'))]


def test_alt_union_correlates_out_of_order_and_bounds_concurrency(panel):
    add_alts(panel)
    panel._search_attendance()
    token = panel._attendance_token
    assert len(panel.requests) == 2
    panel._response(f'attendance|{token}|2', [raid(1, value=0.5), raid(2, value=1)])
    assert len(panel.requests) == 3
    assert not panel.attendance_search.isEnabled()
    panel._response(f'attendance|{token}|163372', [raid(1, value=0.5)])
    assert len(panel.requests) == 4
    panel._response(f'attendance|{token}|3', [raid(3, value=1)])
    panel._response(f'attendance|{token}|4', [raid(1, value=0.5)])
    assert len(panel._attendance_rows) == 3
    assert '3 attended raids' in panel.attendance_status.text()
    assert '3 unique ticks' in panel.attendance_status.text()
    shared = next(row for row in panel._attendance_rows if row['RaidId'] == 1)
    assert shared['_attendance_members'] == {'Mindflux': 1, 'Spiritflux': 1, 'Wildflux': 1}
    assert shared['_attendance_dkp'] == 0.5
    panel.attendance_query.setText('Spiritflux')
    assert panel.attendance_table.rowCount() == 1
    assert 'Spiritflux' in panel.attendance_table.item(0, 5).text()
    assert panel.attendance_search.isEnabled()


def test_partial_alt_failure_survives_and_retry_does_not_mix_generations(panel):
    add_alts(panel)
    panel._search_attendance()
    old = panel._attendance_token
    panel._failed(f'attendance|{old}|2', 'Timeout', 0)
    panel._response(f'attendance|{old}|163372', [raid()])
    panel._response(f'attendance|{old}|3', [])
    panel._response(f'attendance|{old}|4', [])
    assert len(panel._attendance_rows) == 1
    assert 'Partial results' in panel.attendance_status.text()
    assert 'Wildflux (Timeout)' in panel.attendance_status.text()
    panel._search_attendance()
    panel._response(f'attendance|{old}|2', [raid(999)])
    assert panel._attendance_rows == []


def test_opt_out_and_duplicate_main_do_not_request_it_twice(panel):
    add_alts(panel)
    panel._attendance_alts.append({'character_id': 163372, 'name': 'Mindflux'})
    panel._search_attendance()
    assert len(panel._attendance_members) == 4
    panel.attendance_include_alts.setChecked(False)
    panel._search_attendance()
    assert len(panel._attendance_members) == 1
    assert panel.requests[-1][0] == 163372


def test_removed_alt_and_wrong_guild_do_not_pollute_pool(panel):
    add_alts(panel)
    panel._search_attendance()
    token = panel._attendance_token
    panel.client.slug = 'other'
    panel._response(f'attendance|{token}|2', [raid()])
    assert not panel._attendance_rows
    panel.client.slug = 'example'
    panel._attendance_alts = [{'character_id': 999999, 'name': 'NotHere'}]
    assert panel._search_attendance() is False
    assert 'not in this guild' in panel.attendance_status.text()


def test_manage_alts_add_remove_save_and_cancel(panel, monkeypatch):
    add_alts(panel)
    panel._attendance_alts = [{'character_id': 3, 'name': 'Fistflux'}]
    writes = []
    panel._save_profile = lambda **values: writes.append(values)

    def edit(dialog):
        chooser = dialog.findChild(QComboBox)
        saved = dialog.findChild(QListWidget)
        add = next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Add alt')
        remove = next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Remove selected')
        chooser.setCurrentText('wildflux')
        add.click()
        add.click()
        assert saved.count() == 2
        saved.setCurrentRow(0)
        remove.click()
        assert saved.count() == 1
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, 'exec', edit)
    assert panel._edit_attendance_alts()
    assert writes == [{'attendance_alts': [{'character_id': 2, 'name': 'Wildflux'}]}]
    assert panel.attendance_alt_summary.text() == 'Wildflux'
    monkeypatch.setattr(QDialog, 'exec', lambda _dialog: QDialog.DialogCode.Rejected)
    assert panel._edit_attendance_alts() is False
    assert len(writes) == 1


def test_alt_preferences_restore_per_guild_and_persist_include_toggle(panel):
    profiles = {'example': {'attendance_alts': [{'character_id': 2, 'name': 'Wildflux'}],
                            'attendance_include_alts': False}, 'other': {}}
    panel._profile = lambda: profiles[panel.client.slug]
    writes = []
    panel._save_profile = lambda **values: writes.append(values)
    panel._restore_attendance_alts()
    assert panel._attendance_alts[0]['name'] == 'Wildflux'
    assert panel.attendance_include_alts.isChecked() is False
    assert not writes
    panel.attendance_include_alts.setChecked(True)
    assert writes == [{'attendance_include_alts': True}]
    panel.client.slug = 'other'
    panel._restore_attendance_alts()
    assert panel._attendance_alts == []
    assert panel.attendance_alt_summary.text() == 'No alts added'


def test_group_detail_counts_shared_award_once(panel):
    add_alts(panel)
    panel._search_attendance()
    token = panel._attendance_token
    for char_id in (163372, 2, 3, 4):
        panel._response(f'attendance|{token}|{char_id}', [raid()])
    panel._response(f'attendance_detail|{token}|1', {'Ticks': [
        {'TickId': 1, 'Value': 0.5, 'Characters': [{'Name': 'Mindflux'}, {'Name': 'Wildflux'}]},
        {'TickId': 2, 'Value': 1, 'Characters': [{'Name': 'Spiritflux'}]}]})
    assert panel.attendance_table.item(0, 4).text() == '1.5'
    assert '2 verified ticks' in panel.attendance_status.text()
    assert 'Wildflux: 1' in panel.attendance_status.text()
