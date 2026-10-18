"""Pure, conservative provenance for the character history loaded from OpenDKP.

These are loaded records, never a reconstructed account or lifetime balance.
Raid totals use attended tick evidence only. The public character DKP ledger
can supply values omitted by character raid history, but cannot establish
attendance by itself. Unidentified pools are never added together.
"""

from __future__ import annotations

import math

from vantage.helpers.raid_ledger import parse_timestamp


def _text(value):
    return " ".join(str(value if value is not None else "").split())


def _first(row, *keys):
    return next((row[key] for key in keys
                 if row.get(key) is not None and row.get(key) != ""), None)


def _id(value):
    value = _text(value)
    return value if value and value not in ("0", "-1", "True", "False") else ""


def _rows(payload):
    if isinstance(payload, (list, tuple)):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("Models", "Data", "data", "Rows", "rows", "Items"):
            if isinstance(payload.get(key), list):
                return _rows(payload[key])
    return []


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _sum(values):
    try:
        return _finite(math.fsum(values))
    except (OverflowError, ValueError):
        return None


def _identity(row, character_id, character_name, member=False):
    """False rejects an explicit different identity; None has no identity."""
    row_id = _id(_first(row, "CharacterId", "CharacterID", "characterId"))
    name_keys = ("CharacterName", "PlayerName", "MemberName", "ToonName", "characterName")
    row_name = _text(_first(row, *name_keys, *(("Name",) if member else ()))).casefold()
    if row_id and character_id and row_id != character_id:
        return False
    if row_name and character_name and row_name != character_name:
        return False
    if (row_id and character_id) or (row_name and character_name):
        return True
    return None


def _pool_parts(row):
    nested = row.get("Pool")
    nested = nested if isinstance(nested, dict) else {}
    pool_id = _id(_first(row, "PoolId", "PoolID", "DkpPoolId") or
                  _first(nested, "PoolId", "PoolID", "Id"))
    name = _text(_first(row, "PoolName", "DkpPoolName") or
                 _first(nested, "Name", "PoolName") or
                 (row.get("Pool") if isinstance(row.get("Pool"), str) else ""))
    return pool_id, name


def _pool_resolver(rows):
    names = {}
    for row in rows:
        pool_id, name = _pool_parts(row)
        if pool_id and name:
            names.setdefault(name.casefold(), set()).add(pool_id)

    def resolve(row, fallback=("", "Unknown pool")):
        pool_id, name = _pool_parts(row)
        if not pool_id and name and len(names.get(name.casefold(), ())) == 1:
            pool_id = next(iter(names[name.casefold()]))
        if pool_id:
            return "id:" + pool_id, name or "Pool " + pool_id
        if name:
            if len(names.get(name.casefold(), ())) > 1:
                return "", name + " (pool unclear)"
            return "name:" + name.casefold(), name
        return fallback

    return resolve


def _timestamp(row):
    return _text(_first(row, "Timestamp", "Date", "RaidDate",
                        "StartTimestamp", "StartTime", "CreatedAt"))


def _raid_id(row):
    return _id(_first(row, "RaidId", "RaidID", "raid_id", "Id", "id"))


def _attendance(tick, character_id, character_name):
    evidence = []
    if "Attended" in tick:
        value = _text(tick["Attended"]).casefold()
        if value not in ("0", "1", "false", "true"):
            return None
        evidence.append(value in ("1", "true"))
    members = _first(tick, "Characters", "characters")
    if isinstance(members, list):
        identities = [_identity(member, character_id, character_name, True)
                      for member in members if isinstance(member, dict)]
        if any(value is True for value in identities):
            evidence.append(True)
        elif len(identities) != len(members) or any(
                value is None for value in identities):
            return None
        else:
            evidence.append(False)
    if not evidence or len(set(evidence)) != 1:
        return None
    return evidence[0]


def _entry(kind, row, pool, source, description, amount, raid_id="", ticks=None):
    return {
        "kind": kind, "timestamp": _timestamp(row), "source": source,
        "description": description, "amount": amount,
        "pool_key": pool[0], "pool": pool[1], "raid_id": raid_id,
        "raw": row, "ticks": ticks or [],
    }


def _deduplicate(entries, identity):
    """Only real event IDs in identified pools are safe duplicate keys."""
    result, seen = [], {}
    for entry in entries:
        event_id = identity(entry["raw"])
        key = (entry["pool_key"], event_id)
        if not event_id or not key[0] or key not in seen:
            result.append(entry)
            if event_id and key[0]:
                seen[key] = entry
        elif seen[key]["amount"] != entry["amount"]:
            seen[key]["amount"] = None
            seen[key]["description"] += " · Conflicting source amounts"
    return result


def build_dkp_history(raids, adjustments, items, *, character_id,
                      character_name, raid_details=None, dkp=None):
    """Return newest-first raid/adjustment/loot dictionaries for one character.

    ``raids``, ``adjustments`` and ``items`` must come from character endpoints.
    ``raid_details`` maps raid IDs to public raid details. Optional ``dkp`` is
    the personal transaction endpoint: its raid rows enrich attended ticks,
    while its adjustment/item rows are the primary records for those kinds
    when supplied. This avoids counting both endpoint copies of a transaction.

    Each entry has kind, timestamp, source, description, amount, pool,
    pool_key, raid_id, raw and ticks. Amount is finite signed DKP or None.
    Tick dictionaries additionally expose tick_id, attended and evidence.
    No source input is changed. A known zero award is distinct from unknown.
    """
    character_id = _id(character_id)
    character_name = _text(character_name).casefold()
    if not character_id and not character_name:
        return []
    matches = lambda row: _identity(row, character_id, character_name)
    raids = [row for row in _rows(raids) if matches(row) is not False]
    adjustments = [row for row in _rows(adjustments) if matches(row) is not False]
    items = [row for row in _rows(items) if matches(row) is not False]
    ledger = [row for row in _rows(dkp) if matches(row) is True]
    details = {}
    for key, detail in (raid_details or {}).items():
        if isinstance(detail, dict) and matches(detail) is not False:
            detail_id = _raid_id(detail)
            if not detail_id or detail_id == _id(key):
                details[_id(key)] = detail
    all_rows = [*raids, *adjustments, *items, *ledger, *details.values()]
    for row in [*raids, *details.values()]:
        all_rows.extend(_rows(row.get("Ticks")))
    pool_for = _pool_resolver(all_rows)
    raid_pools = {}
    for row in [*raids, *details.values()]:
        raid_id = _raid_id(row)
        pool = pool_for(row)
        if raid_id and pool[0]:
            raid_pools.setdefault(raid_id, {})[pool[0]] = pool

    def related_pool(row, raid_id=""):
        pools = raid_pools.get(raid_id, {})
        fallback = (next(iter(pools.values())) if len(pools) == 1
                    else ("", "Unknown pool"))
        return pool_for(row, fallback)

    ledger_ticks = {}
    for row in ledger:
        if _text(row.get("SourceType")).casefold() != "raid":
            continue
        raid_id, tick_id = _id(row.get("SourceId")), _id(row.get("TickId"))
        if raid_id and tick_id:
            ledger_ticks.setdefault((raid_id, tick_id), []).append(row)

    # Merge copies of identified raids, retaining all tick evidence so
    # contradictory duplicate ticks cannot silently become earned DKP.
    raid_groups = []
    group_index = {}
    for row in raids:
        raid_id = _raid_id(row)
        detail = details.get(raid_id, {})
        pool = related_pool(row, raid_id)
        key = (raid_id, pool[0])
        if raid_id and pool[0] and key in group_index:
            group_index[key][2].append(row)
        else:
            group = [row, detail, [row], pool]
            raid_groups.append(group)
            if raid_id and pool[0]:
                group_index[key] = group

    result = []
    for row, detail, copies, raid_pool in raid_groups:
        raid_id = _raid_id(row)
        if detail and pool_for(detail, raid_pool)[0] != raid_pool[0]:
            # A reused raid/tick ID in a different pool cannot verify this award.
            detail = {}
        source = _text(_first(row, "RaidName", "Name", "EventName")) or "Raid"
        detail_ticks = _rows(detail.get("Ticks"))
        tick_groups, tick_index = [], {}
        for copy in copies:
            for tick in _rows(copy.get("Ticks")):
                tick_id = _id(tick.get("TickId"))
                pool = pool_for(tick, raid_pool)
                key = (pool[0], tick_id)
                if tick_id and key in tick_index:
                    tick_index[key][0].append(tick)
                else:
                    group = [[tick], pool]
                    tick_groups.append(group)
                    if tick_id:
                        tick_index[key] = group
        if not tick_groups:
            for tick in detail_ticks:
                tick_id = _id(tick.get("TickId"))
                pool = pool_for(tick, raid_pool)
                key = (pool[0], tick_id)
                if tick_id and key in tick_index:
                    tick_index[key][0].append(tick)
                else:
                    group = [[tick], pool]
                    tick_groups.append(group)
                    if tick_id:
                        tick_index[key] = group
        grouped = {}
        for ticks, pool in tick_groups:
            tick = ticks[0]
            tick_id = _id(tick.get("TickId"))
            evidence = list(ticks)
            if tick_id:
                evidence.extend(candidate for candidate in detail_ticks
                                if _id(candidate.get("TickId")) == tick_id
                                and pool_for(candidate, raid_pool)[0] == pool[0]
                                and candidate not in evidence)
            attended_values = [_attendance(item, character_id, character_name)
                               for item in evidence]
            known_attendance = {value for value in attended_values if value is not None}
            malformed = any("Attended" in item and _text(item["Attended"]).casefold()
                            not in ("0", "1", "false", "true") for item in evidence)
            attended = (next(iter(known_attendance)) if len(known_attendance) == 1
                        and not malformed else None)
            # Missing evidence can be resolved by a matching public detail,
            # but contradictory identified membership remains unresolved.
            if any(("Characters" in item or "characters" in item) and _attendance(
                    item, character_id, character_name) is None for item in evidence):
                attended = None
            awards = [award for award in ledger_ticks.get((raid_id, tick_id), [])
                      if related_pool(award, raid_id)[0] == pool[0]]
            values = [_finite(item["Value"]) for item in [*evidence, *awards]
                      if "Value" in item]
            amount = (values[0] if values and None not in values
                      and len(set(values)) == 1 and attended is True else None)
            if attended is False:
                amount = 0.0
            description = _text(_first(tick, "Description", "Name"))
            if not description:
                description = next((_text(item.get("Description")) for item in evidence
                                    if item.get("Description")), "")
            award_source = next((_text(award.get("Source")) for award in awards
                                 if award.get("Source")), "")
            normalized = {
                "tick_id": tick_id, "attended": attended, "amount": amount,
                "description": description or award_source or "Raid tick",
                "source": award_source or source,
                "timestamp": _timestamp(awards[0]) if awards else _timestamp(row),
                "raw": tick, "evidence": [*evidence, *awards],
                "pool": pool[1], "pool_key": pool[0],
            }
            grouped.setdefault(pool, []).append(normalized)
        if not grouped:
            grouped[raid_pool] = []
        for pool, ticks in grouped.items():
            if ticks and all(tick["attended"] is False for tick in ticks):
                continue
            amounts = [tick["amount"] for tick in ticks]
            amount = _sum(amounts) if amounts and None not in amounts else None
            attended_count = sum(tick["attended"] is True for tick in ticks)
            description = _text(_first(row, "Description", "Notes") or
                                _first(detail, "Description", "Notes"))
            description = " · ".join(filter(None, (
                description, f"{attended_count} attended tick" +
                ("s" if attended_count != 1 else ""),
                "Award unknown" if amount is None else "")))
            result.append(_entry("raid", row, pool, source, description,
                                 amount, raid_id, ticks))

    ledger_adjustments = [row for row in ledger
                          if _text(row.get("SourceType")).casefold() == "adjustment"]
    adjustment_entries = []
    for row in ledger_adjustments or adjustments:
        from_ledger = row in ledger_adjustments
        adjustment_id = _id(row.get("SourceId") if from_ledger else row.get("AdjustmentId"))
        candidates = [item for item in adjustments
                      if adjustment_id and _id(item.get("AdjustmentId")) == adjustment_id]
        candidate_pools = {pool_for(item) for item in candidates if pool_for(item)[0]}
        fallback = next(iter(candidate_pools)) if len(candidate_pools) == 1 else ("", "Unknown pool")
        pool = pool_for(row, fallback)
        supplemental = candidates[0] if len(candidates) == 1 else {}
        source = _text(_first(row, "Name", "Source")) or "Adjustment"
        description = _text(_first(row, "Description", "Notes") or
                            _first(supplemental, "Description", "Notes", "Name")) or source
        adjustment_entries.append(_entry(
            "adjustment", row, pool, source, description,
            _finite(_first(row, "Value", "Amount", "DKP"))))
    result.extend(_deduplicate(adjustment_entries, lambda row: _id(
        _first(row, "AdjustmentId", "SourceId"))))

    ledger_items = [row for row in ledger
                    if _text(row.get("SourceType")).casefold() in ("item", "loot")]
    loot_entries = []
    for row in ledger_items or items:
        from_ledger = row in ledger_items
        raid_id = (_id(row.get("SourceId")) if from_ledger else
                   _id(_first(row, "RaidId", "RaidID")))
        amount = (_finite(row.get("Value")) if from_ledger else
                  _finite(_first(row, "DkpValue", "DKPValue", "DKP", "Cost", "Value", "Amount")))
        source = _text(_first(row, "ItemName", "Source", "Name")) or "Loot"
        description = " · ".join(filter(None, (
            _text(_first(row, "Raid", "RaidName")),
            _text(_first(row, "Notes", "Description"))))) or source
        entry = _entry(
            "loot", row, related_pool(row, raid_id), source, description,
            (amount if from_ledger else -amount) if amount is not None else None, raid_id)
        # The transaction Source can be "Raid - Item"; it is not an item name.
        # Link only an explicit item name or an unambiguous catalog match from
        # this character's purchases in the same raid.
        item_name = _text(row.get("ItemName"))
        if not item_name and from_ledger:
            names = {_text(item.get("ItemName")) for item in items
                     if raid_id and _id(_first(item, "RaidId", "RaidID")) == raid_id
                     and _text(item.get("ItemName")) and (
                         source.casefold() == _text(item["ItemName"]).casefold() or
                         source.casefold().endswith(" - " + _text(item["ItemName"]).casefold()))}
            if len(names) == 1:
                item_name = next(iter(names))
        entry["item_name"] = item_name
        loot_entries.append(entry)
    # ItemID/GameItemId identifies an item type, and ledger SourceId a raid.
    # Neither identifies a purchase: identical purchases must remain distinct.
    result.extend(_deduplicate(loot_entries, lambda row: _id(
        _first(row, "PurchaseId", "CharacterItemId", "LootId", "TransactionId"))))

    def sort_key(entry):
        stamp = parse_timestamp(entry["timestamp"])
        return stamp.timestamp() if stamp is not None else float("-inf")

    return sorted(result, key=sort_key, reverse=True)


def summarize_dkp_history(entries):
    """Summarize known amounts for the supplied rows, without mixing pools.

    Credits and debits are positive magnitudes; net is credits minus debits.
    Unknown amounts are counted and excluded from known subtotals. Top-level
    monetary totals are None for mixed or unidentified pools. The unidentified
    bucket itself also has None totals: it may conceal several different pools.
    """
    entries = _rows(entries)
    groups = {}
    for entry in entries:
        key = _text(entry.get("pool_key"))
        groups.setdefault(key, []).append(entry)
    summaries = []
    for key, rows in groups.items():
        amounts = [_finite(row.get("amount")) for row in rows]
        credits = _sum(value for value in amounts if value is not None and value > 0)
        debits = _sum(-value for value in amounts if value is not None and value < 0)
        summaries.append({
            "pool_key": key, "pool": rows[0].get("pool") or "Unknown pool",
            "count": len(rows), "unknown_count": amounts.count(None),
            "credits": credits if key else None, "debits": debits if key else None,
            "net": _sum((credits, -debits)) if key and credits is not None
            and debits is not None else None,
        })
    single = summaries[0] if len(summaries) == 1 and summaries[0]["pool_key"] else {}
    return {
        "count": len(entries), "credits": single.get("credits"),
        "debits": single.get("debits"), "net": single.get("net"),
        "unknown_count": sum(row["unknown_count"] for row in summaries),
        "unknown_pool_count": len(groups.get("", [])), "by_pool": summaries,
    }
