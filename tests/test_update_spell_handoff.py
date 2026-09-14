import json
import time

from vantage.helpers.update_handoff import (
    consume_spell_handoff, read_spell_handoff, write_spell_handoff)


def _buff(name="Focus of Spirit", deadline=None, **extra):
    row = {
        "deadline": float(deadline or time.time() + 600),
        "target": "__you__",
        "target_created_order": 1,
        "target_marker": "",
        "character": "Spiritflux",
        "server": "P1999 Green",
        "spell": {
            "name": name,
            "runtime_key": name.casefold(),
            "duration_seconds": 600,
        },
    }
    row.update(extra)
    return row


def test_handoff_is_update_only_bounded_and_drops_expired_or_secret_fields(
        tmp_path):
    path = tmp_path / "handoff.json"
    now = time.time()
    live = _buff(deadline=now + 600, password="must-not-leave-config")
    live["spell"]["api_token"] = "must-not-leave-config"
    expired = _buff("Expired", deadline=now - 1)

    written = write_spell_handoff([live, expired], path=path, now=now)

    assert read_spell_handoff(path=path, now=now + 1) is None
    restored = read_spell_handoff(
        updated_from="1.44.85", path=path, now=now + 1)
    assert len(written) == len(restored) == 1
    assert restored[0]["spell"]["name"] == "Focus of Spirit"
    assert "password" not in restored[0]
    assert "api_token" not in restored[0]["spell"]


def test_damaged_handoff_is_rejected_without_partial_restore(tmp_path):
    path = tmp_path / "handoff.json"
    now = time.time()
    write_spell_handoff([_buff(deadline=now + 600)], path=path, now=now)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][0]["spell"]["name"] = "Tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_spell_handoff(
        updated_from="1.44.85", path=path, now=now + 1) is None
    assert path.exists()


def test_handoff_is_consumed_only_after_matching_restoration(tmp_path):
    path = tmp_path / "handoff.json"
    now = time.time()
    expected = write_spell_handoff(
        [_buff(deadline=now + 600)], path=path, now=now)

    assert consume_spell_handoff(
        expected, [], path=path, now=now + 1) is False
    assert path.exists()

    # SpellContainer restores integer seconds, so a harmless sub-second
    # deadline shift is accepted while a different identity is not.
    restored = [dict(expected[0], deadline=expected[0]["deadline"] + 0.8)]
    assert consume_spell_handoff(
        expected, restored, path=path, now=now + 1) is True
    assert not path.exists()


def test_valid_empty_handoff_clears_stale_rows_without_reviving_on_normal_start(
        tmp_path):
    path = tmp_path / "handoff.json"
    now = time.time()
    write_spell_handoff([], path=path, now=now)

    assert read_spell_handoff(path=path, now=now + 1) is None
    assert read_spell_handoff(
        updated_from="1.44.85", path=path, now=now + 1) == []
    assert consume_spell_handoff([], [], path=path, now=now + 1) is True
