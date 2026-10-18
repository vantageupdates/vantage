"""DKP provenance is personal tick evidence, never raid-wide award totals."""

import copy
import math

import pytest

from vantage.helpers.dkp_history import build_dkp_history, summarize_dkp_history


def history(raids=(), adjustments=(), items=(), **kwargs):
    return build_dkp_history(raids, adjustments, items,
                             character_id=163372, character_name="Mindflux", **kwargs)


def raid(ticks, **kwargs):
    return {"RaidId": 12, "RaidName": "Temple raid", "PoolName": "SoV",
            "Timestamp": "2026-10-01T20:00:00Z", "Ticks": ticks,
            "DKPAwarded": 999, **kwargs}


def ledger_row(kind="Raid", **kwargs):
    return {"SourceType": kind, "CharacterId": 163372, "CharacterName": "Mindflux",
            "SourceId": 12, "TickId": 4, "Value": 2,
            "Date": "2026-10-01T20:30:00Z", "Source": "Temple raid - First kill",
            **kwargs}


def test_detail_from_different_pool_cannot_supply_tick_value():
    rows = history([raid([{"TickId": 4, "Attended": 1}], PoolId=1, PoolName="Main")],
        raid_details={"12": {"RaidId": 12, "Pool": {"PoolId": 2, "Name": "Other"},
            "Ticks": [{"TickId": 4, "Value": 100,
                       "Characters": [{"Name": "Mindflux", "CharacterId": 163372}]}]}})
    assert rows[0]["pool"] == "Main"
    assert rows[0]["amount"] is None


def test_loot_source_and_item_name_are_separate_and_unresolved_links_stay_empty():
    rows = history(items=[{"ItemName": "White Dragon Helm", "RaidID": 12, "DkpValue": 40}],
        dkp=[ledger_row("Item", Source="Temple raid - White Dragon Helm", Value=-40)])
    assert rows[0]["source"] == "Temple raid - White Dragon Helm"
    assert rows[0]["item_name"] == "White Dragon Helm"
    rows = history(dkp=[ledger_row("Item", Source="Temple raid - Unknown item", Value=-40)])
    assert rows[0]["item_name"] == ""


def test_public_character_raid_shape_enriches_attended_tick_from_personal_ledger():
    rows = history([raid([{"TickId": 4, "Attended": 1},
                          {"TickId": 5, "Attended": 0}])], dkp=[ledger_row()])
    assert len(rows) == 1
    row = rows[0]
    assert row["amount"] == 2
    assert row["pool"] == "SoV"
    assert row["pool_key"] == "name:sov"
    assert row["raid_id"] == "12"
    assert row["source"] == "Temple raid"
    assert row["ticks"][0]["source"] == "Temple raid - First kill"
    assert row["ticks"][0]["timestamp"] == "2026-10-01T20:30:00Z"
    assert row["ticks"][1]["amount"] == 0


def test_missing_award_and_missing_attendance_are_unknown_not_zero():
    assert history([raid([{"TickId": 4, "Attended": 1}])])[0]["amount"] is None
    assert history([raid([{"TickId": 4, "Value": 20}])])[0]["amount"] is None
    assert history([raid([])])[0]["amount"] is None
    assert history([raid([{"TickId": 4}])], dkp=[ledger_row()])[0]["amount"] is None
    assert history([], dkp=[ledger_row()]) == []


def test_explicitly_absent_raids_are_omitted_but_attended_zero_awards_remain():
    assert history([raid([{"TickId": 4, "Attended": 0, "Value": 20}])]) == []
    assert history([raid([{"TickId": 4, "Attended": True, "Value": 0}])])[0]["amount"] == 0


@pytest.mark.parametrize("value", [None, "", "bad", float("nan"), float("inf"),
                                   float("-inf"), "NaN", "Infinity", True])
def test_nonfinite_and_invalid_tick_values_stay_unknown(value):
    rows = history([raid([{"TickId": 4, "Attended": 1, "Value": value}])])
    assert rows[0]["amount"] is None


def test_unknown_one_of_multiple_attended_ticks_never_reports_partial_raid_total():
    rows = history([raid([{"TickId": 4, "Attended": 1, "Value": 3},
                          {"TickId": 5, "Attended": 1}])])
    assert rows[0]["amount"] is None
    assert rows[0]["ticks"][0]["amount"] == 3


def test_duplicate_tick_ids_count_once_and_conflicting_values_stay_unknown():
    tick = {"TickId": 4, "Attended": 1, "Value": 3}
    rows = history([raid([tick, dict(tick)])])
    assert rows[0]["amount"] == 3
    assert len(rows[0]["ticks"]) == 1
    assert history([raid([tick, {**tick, "Value": 5}])])[0]["amount"] is None
    assert history([raid([tick, {**tick, "Attended": 0}])])[0]["amount"] is None


def test_distinct_ticks_without_ids_are_not_collapsed():
    tick = {"Attended": 1, "Value": 3, "Description": "Attendance"}
    rows = history([raid([tick, dict(tick)])])
    assert rows[0]["amount"] == 6
    assert len(rows[0]["ticks"]) == 2


def test_duplicate_raids_merge_tick_evidence_with_conflicts_unknown():
    first = raid([{"TickId": 4, "Attended": 1, "Value": 3}])
    assert len(history([first, copy.deepcopy(first)])) == 1
    assert history([first, copy.deepcopy(first)])[0]["amount"] == 3
    conflicting = raid([{"TickId": 4, "Attended": 1, "Value": 5}])
    assert history([first, conflicting])[0]["amount"] is None


def test_detail_membership_resolves_values_and_normalizes_public_pool_shape():
    detail = {"RaidId": 12, "Pool": {"PoolId": 4, "Name": "SoV"},
              "Description": "Boss night", "Ticks": [
                  {"TickId": 4, "Value": 3, "Description": "First kill",
                   "Characters": [{"Name": "Mindflux", "CharacterId": 163372}]},
                  {"TickId": 5, "Value": 100,
                   "Characters": [{"Name": "Someone else", "CharacterId": 9}]},
              ]}
    rows = history([raid([{"TickId": 4}, {"TickId": 5}])], raid_details={12: detail})
    assert rows[0]["amount"] == 3
    assert rows[0]["pool_key"] == "id:4"
    assert rows[0]["ticks"][0]["description"] == "First kill"
    assert "Boss night" in rows[0]["description"]


def test_detail_with_missing_character_identity_cannot_prove_absence():
    detail = {"RaidId": 12, "Ticks": [
        {"TickId": 4, "Value": 3, "Characters": [{"Unknown": "Mindflux"}]}]}
    assert history([raid([{"TickId": 4}])], raid_details={12: detail})[0]["amount"] is None


def test_detail_with_mismatched_raid_id_is_ignored():
    detail = {"RaidId": 99, "Ticks": [
        {"TickId": 4, "Value": 3, "Characters": [{"CharacterId": 163372}]}]}
    assert history([raid([{"TickId": 4}])], raid_details={12: detail})[0]["amount"] is None


def test_detail_membership_and_explicit_attendance_conflicts_stay_unknown():
    detail = {"RaidId": 12, "Ticks": [
        {"TickId": 4, "Value": 3, "Characters": [{"CharacterId": 99}]}]}
    assert history([raid([{"TickId": 4, "Attended": 1}])],
                   raid_details={12: detail})[0]["amount"] is None


def test_same_name_different_character_id_is_never_personal_membership():
    detail = {"RaidId": 12, "Ticks": [
        {"TickId": 4, "Value": 3,
         "Characters": [{"CharacterId": 99, "Name": "Mindflux"}]}]}
    assert history([raid([{"TickId": 4}])], raid_details={12: detail}) == []


def test_other_character_payload_rows_and_ledger_values_are_rejected():
    assert history([raid([], CharacterId=99)]) == []
    assert history(adjustments=[{"CharacterId": 99, "Value": 5}]) == []
    assert history(items=[{"CharacterName": "SomeoneElse", "DkpValue": 5}]) == []
    rows = history([raid([{"TickId": 4, "Attended": 1}])],
                   dkp=[ledger_row(CharacterId=99)])
    assert rows[0]["amount"] is None


def test_personal_ledger_may_include_linked_alts_but_their_awards_are_excluded():
    rows = history([raid([{"TickId": 4, "Attended": 1}])], dkp=[
        ledger_row(Value=2),
        ledger_row(CharacterId=999, CharacterName="Linkedalt", Value=20),
        ledger_row("Adjustment", CharacterId=999, CharacterName="Linkedalt", Value=50),
        ledger_row("Item", CharacterId=999, CharacterName="Linkedalt", Value=-100)])
    assert len(rows) == 1
    assert rows[0]["amount"] == 2


def test_adjustments_preserve_signed_values_and_source_descriptions():
    rows = history(adjustments=[
        {"AdjustmentId": 6, "Name": "Key bonus", "Description": "First keyed alt",
         "CharacterId": 163372, "Value": "20", "PoolName": "SoV",
         "Timestamp": "2026-10-01T15:00:00Z"},
        {"AdjustmentId": 7, "Name": "Correction", "Value": -2, "PoolName": "SoV"},
    ])
    assert rows[0]["source"] == "Key bonus"
    assert rows[0]["description"] == "First keyed alt"
    assert [row["amount"] for row in rows] == [20, -2]
    assert summarize_dkp_history(rows)["net"] == 18


def test_personal_ledger_is_primary_adjustment_and_loot_coverage_without_double_counting():
    rows = history(
        [raid([{"TickId": 4, "Attended": 0}])],
        adjustments=[{"AdjustmentId": 30, "Name": "Bonus", "Description": "Quest credit",
                      "Value": 5, "PoolName": "SoV"}],
        items=[{"ItemID": 24961, "ItemName": "Helm", "RaidID": 12, "DkpValue": 8}],
        dkp=[ledger_row("Adjustment", SourceId=30, Value=5, Source="Bonus"),
             ledger_row("Adjustment", SourceId=31, Value=2, Source="Later bonus"),
             ledger_row("Item", Value=-8, Source="Temple raid - Helm")])
    assert len(rows) == 3
    assert [row["amount"] for row in rows] == [5, 2, -8]
    assert rows[0]["description"] == "Quest credit"
    assert rows[0]["pool_key"] == "name:sov"
    assert rows[1]["pool_key"] == ""
    assert rows[2]["pool_key"] == "name:sov"


def test_same_catalog_item_and_identical_ledger_purchases_are_not_deduplicated():
    item = {"ItemID": 24961, "GameItemId": 24961, "ItemName": "Helm",
            "RaidID": 12, "DkpValue": 8}
    rows = history(items=[item, dict(item)])
    assert len(rows) == 2
    assert [row["amount"] for row in rows] == [-8, -8]
    purchase = ledger_row("Item", Value=-8)
    assert len(history(dkp=[purchase, dict(purchase)])) == 2


def test_loot_credit_preserves_signed_transaction_or_negative_cost():
    assert history(dkp=[ledger_row("Item", Value=8)])[0]["amount"] == 8
    assert history(items=[{"ItemName": "Returned helm", "DkpValue": -8}])[0]["amount"] == 8


def test_real_event_ids_only_deduplicate_within_identified_pool():
    adjustment = {"AdjustmentId": 4, "PoolName": "SoV", "Value": 5}
    assert len(history(adjustments=[adjustment, dict(adjustment)])) == 1
    assert len(history(adjustments=[adjustment, {**adjustment, "PoolName": "Kunark"}])) == 2
    conflict = history(adjustments=[adjustment, {**adjustment, "Value": 8}])
    assert len(conflict) == 1
    assert conflict[0]["amount"] is None
    assert len(history(adjustments=[{"AdjustmentId": 4, "Value": 5}] * 2)) == 2
    assert len(history(adjustments=[{"PoolName": "SoV", "Value": 5}] * 2)) == 2


def test_per_tick_pools_are_separate_even_when_tick_ids_match():
    rows = history([raid([
        {"TickId": 4, "Attended": 1, "Value": 3, "PoolName": "SoV"},
        {"TickId": 4, "Attended": 1, "Value": 8, "PoolName": "Kunark"}])])
    assert len(rows) == 2
    assert {row["pool"]: row["amount"] for row in rows} == {"SoV": 3, "Kunark": 8}
    assert summarize_dkp_history(rows)["net"] is None


def test_same_pool_name_with_multiple_explicit_ids_does_not_guess_pool_identity():
    rows = history(adjustments=[
        {"Value": 1, "Pool": {"Name": "Raid", "PoolId": 1}},
        {"Value": 2, "Pool": {"Name": "Raid", "PoolId": 2}},
        {"Value": 3, "PoolName": "Raid"}])
    assert [row["pool_key"] for row in rows] == ["id:1", "id:2", ""]
    assert summarize_dkp_history(rows)["unknown_pool_count"] == 1


def test_summary_counts_unknown_and_does_not_mix_unknown_or_different_pools():
    rows = history(adjustments=[
        {"PoolName": "SoV", "Value": 5}, {"PoolName": "SoV", "Value": -2},
        {"PoolName": "SoV", "Value": None}])
    summary = summarize_dkp_history(rows)
    assert summary["credits"] == 5
    assert summary["debits"] == 2
    assert summary["net"] == 3
    assert summary["unknown_count"] == 1
    mixed = summarize_dkp_history(rows + history(adjustments=[{"Value": 100}]))
    assert mixed["net"] is None
    assert mixed["unknown_pool_count"] == 1
    assert mixed["by_pool"][0]["net"] == 3
    assert mixed["by_pool"][1]["net"] is None
    assert summarize_dkp_history([])["net"] is None


def test_overflow_never_leaks_infinite_amounts_or_summaries():
    rows = history([raid([{"Attended": 1, "Value": 1e308}] * 2)])
    assert rows[0]["amount"] is None
    summary = summarize_dkp_history(history(adjustments=[
        {"PoolName": "SoV", "Value": 1e308}] * 2))
    assert summary["credits"] is None
    assert summary["net"] is None
    assert all(value is None or math.isfinite(value)
               for value in (summary["credits"], summary["debits"], summary["net"]))


def test_inputs_are_unchanged_and_rows_are_sorted_by_actual_timestamp():
    payload = {"Models": [raid([{"TickId": 4, "Attended": 1, "Value": 3}])]}
    before = copy.deepcopy(payload)
    rows = history(payload, adjustments=[
        {"Timestamp": "2026-10-01T18:00:00-04:00", "Value": 5, "Name": "Later"},
        {"Timestamp": "invalid", "Value": 1, "Name": "Unknown date"}])
    assert payload == before
    assert [row["source"] for row in rows] == ["Later", "Temple raid", "Unknown date"]


def test_conflicting_personal_ledger_values_do_not_pick_one_arbitrarily():
    rows = history([raid([{"TickId": 4, "Attended": 1}])],
                   dkp=[ledger_row(Value=2), ledger_row(Value=4)])
    assert rows[0]["amount"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "bad"])
def test_adjustment_and_loot_nonfinite_values_are_unknown(value):
    assert history(adjustments=[{"Value": value}])[0]["amount"] is None
    assert history(items=[{"DkpValue": value}])[0]["amount"] is None
