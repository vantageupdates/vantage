"""Saved alt identities and read-only attendance union (never DKP balances)."""
import math


def sanitize_attendance_alts(value):
    if not isinstance(value, list):
        return []
    result, seen = [], set()
    for entry in value[:200]:
        if not isinstance(entry, dict):
            continue
        try:
            char_id = int(entry.get("character_id", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        name = " ".join(str(entry.get("name") or "").split())[:80]
        if not 0 < char_id <= 2147483647 or not name or char_id in seen:
            continue
        seen.add(char_id)
        result.append({"character_id": char_id, "name": name})
        if len(result) == 24:
            break
    return result


def _amount(value):
    try:
        amount = float(value)
        return amount if math.isfinite(amount) else None
    except (TypeError, ValueError, OverflowError):
        return None


def pool_raid_attendance(character_rows):
    """Union by raid ID, retaining members and unique attended tick IDs.

    Dates/unknown evidence are filtered by the caller. A raid without a stable
    ID is not merged across characters. DKP is a tick award, not a balance.
    """
    from vantage.helpers.raid_ledger import character_raid_attendance, remote_raid_id
    groups = {}
    for name, rows in character_rows.items():
        for index, raid in enumerate(rows):
            count, _ = character_raid_attendance(raid)
            if not count:
                continue
            key = remote_raid_id(raid) or (name.casefold(), index)
            group = groups.setdefault(key, {"raid": dict(raid), "members": {}, "ticks": {}, "missing_ids": False})
            group["members"][name] = count
            for tick_index, tick in enumerate(raid["Ticks"]):
                if not isinstance(tick, dict) or str(tick.get("Attended")).casefold() not in ("1", "true"):
                    continue
                tick_id = str(tick.get("TickId") or "").strip()
                if not tick_id:
                    group["missing_ids"] = True
                tick_key = tick_id or (name.casefold(), tick_index)
                amount = _amount(tick.get("Value"))
                if tick_key in group["ticks"] and group["ticks"][tick_key].get("Value") != amount:
                    amount = None  # conflicting values cannot become an invented award
                group["ticks"][tick_key] = {"TickId": tick_id, "Attended": 1, "Value": amount}
    result = []
    for group in groups.values():
        raid = group["raid"]
        raid["Ticks"] = list(group["ticks"].values())
        raid["_attendance_members"] = dict(sorted(group["members"].items(), key=lambda pair: pair[0].casefold()))
        uncertain = group["missing_ids"] and len(group["members"]) > 1
        raid["_attendance_tick_count"] = None if uncertain else len(raid["Ticks"])
        amounts = [tick["Value"] for tick in raid["Ticks"]]
        raid["_attendance_dkp"] = (sum(amounts) if not uncertain and
                                   all(amount is not None for amount in amounts) else None)
        result.append(raid)
    return result


def pooled_tick_evidence(payload, names):
    from vantage.helpers.raid_ledger import remote_tick_evidence
    import json
    ticks, members = {}, {}
    for name in names:
        matches, _ = remote_tick_evidence(payload, name)
        members[name] = len(matches)
        for tick in matches:
            key = str(tick.get("TickId") or "") or json.dumps(tick, sort_keys=True, default=str)
            ticks[key] = tick
    amounts = [_amount(tick.get("Value")) for tick in ticks.values()]
    return len(ticks), (sum(amounts) if ticks and all(amount is not None for amount in amounts) else None), members
