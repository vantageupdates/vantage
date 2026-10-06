"""Matching scope survives native sharing without broadening old packs."""
import json

import pytest

from vantage.helpers.gina_import import (
    GinaImportError, import_vantage_package_bytes, serialize_gina_package,
    serialize_vantage_package)
from vantage.helpers.trigger_sharing import (
    create_trigger_share_code, decode_trigger_share_code, trigger_share_url)
from vantage.parsers.spells import (
    CustomTrigger, compile_trigger_pattern, match_trigger_pattern)


def _matches(trigger, line):
    pattern = compile_trigger_pattern(
        trigger.text, raw_regex=trigger.regex, match_mode=trigger.match_mode)
    return bool(match_trigger_pattern(
        pattern, line, raw_regex=trigger.regex, match_mode=trigger.match_mode))


def test_full_line_export_remains_schema_one_and_older_reader_compatible():
    original = CustomTrigger(name="Precise", text="{Mob} roars", audio_muted=True)
    content, warnings = serialize_vantage_package([original])
    data = json.loads(content)
    assert data["version"] == 1
    assert len(data["triggers"][0]["values"]) == 49
    assert not warnings
    restored = import_vantage_package_bytes(content)[0]
    assert restored.match_mode == "full" and restored.audio_muted
    assert _matches(restored, "Tangrin roars")
    assert not _matches(restored, "You hear Tangrin roars nearby")


@pytest.mark.parametrize("transport", ["bytes", "code", "link"])
def test_mixed_pack_retains_each_matching_scope_and_reviewed_disabled_state(transport):
    keyword = CustomTrigger(name="Keyword", text="the tangrin", match_mode="contains")
    precise = CustomTrigger(name="Precise", text="{Mob} roars")
    content, warnings = serialize_vantage_package([keyword, precise])
    data = json.loads(content)
    assert data["version"] == 2
    assert [len(row["values"]) for row in data["triggers"]] == [50, 49]
    assert any(warning["code"] == "minimum-version" and
               "1.44.127" in warning["message"] for warning in warnings)
    if transport != "bytes":
        code = create_trigger_share_code(content)
        content = decode_trigger_share_code(
            trigger_share_url(code) if transport == "link" else code)
    batch = import_vantage_package_bytes(content)
    assert [trigger.match_mode for trigger in batch] == ["contains", "full"]
    assert all(not trigger.enabled for trigger in batch)
    assert _matches(batch[0], "You have slain THE TANGRIN!")
    assert not _matches(batch[1], "You hear Tangrin roars nearby")


@pytest.mark.parametrize("bad_mode", ["unexpected", "CONTAINS", "", None, True])
def test_native_pack_does_not_silently_normalize_an_unsupported_scope(bad_mode):
    content, _ = serialize_vantage_package([
        CustomTrigger(name="Keyword", text="tangrin", match_mode="contains")])
    data = json.loads(content)
    data["triggers"][0]["values"][49] = bad_mode
    with pytest.raises(GinaImportError, match="no compatible trigger records"):
        import_vantage_package_bytes(json.dumps(data).encode())


def test_contains_mode_cannot_be_smuggled_into_schema_one():
    content, _ = serialize_vantage_package([
        CustomTrigger(name="Keyword", text="tangrin", match_mode="contains")])
    data = json.loads(content)
    data["version"] = 1
    with pytest.raises(GinaImportError, match="requires native pack schema 2"):
        import_vantage_package_bytes(json.dumps(data).encode())


def test_gina_export_warns_that_keyword_scope_needs_native_sharing():
    content, warnings = serialize_gina_package([
        CustomTrigger(name="Keyword", text="the tangrin", match_mode="contains")])
    assert content.startswith(b"PK")
    assert any(warning["code"] == "gina-settings-loss" and
               "Contains text" in warning["message"] and
               "native JSON" in warning["message"] for warning in warnings)
