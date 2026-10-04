import pytest
from PySide6.QtNetwork import QNetworkRequest

from vantage.helpers.updater import (
    ASSET_NAME, RELEASE_HISTORY_API, UpdateController,
    parse_release_payload, select_companion_release)


def _release(**changes):
    payload = {
        "tag_name": "v1.44.0",
        "name": "Vantage 1.44.0",
        "body": "Updater and clicky tracking.",
        "published_at": "2026-09-01T12:00:00Z",
        "html_url": "https://github.com/vantageupdates/vantage/releases/tag/v1.44.0",
        "draft": False,
        "prerelease": False,
        "assets": [{
            "name": ASSET_NAME,
            "size": 66_000_000,
            "digest": "sha256:" + "a" * 64,
            "browser_download_url": (
                "https://github.com/vantageupdates/vantage/releases/"
                "download/v1.44.0/Vantage.exe"),
        }],
    }
    payload.update(changes)
    return payload


def test_release_payload_requires_exact_verified_vantage_asset():
    info = parse_release_payload(_release())

    assert str(info.version) == "1.44.0"
    assert info.size == 66_000_000
    assert info.digest == "sha256:" + "a" * 64
    assert info.notes == "Updater and clicky tracking."


@pytest.mark.parametrize("asset_change", [
    {"size": 0},
    {"digest": ""},
    {"name": "something.exe"},
    {"browser_download_url": "https://example.com/Vantage.exe"},
])
def test_release_payload_rejects_untrusted_or_incomplete_asset(asset_change):
    payload = _release()
    payload["assets"][0].update(asset_change)

    with pytest.raises(ValueError):
        parse_release_payload(payload)


def test_release_payload_rejects_prerelease():
    with pytest.raises(ValueError):
        parse_release_payload(_release(prerelease=True))


def test_history_selects_newest_exact_companion_and_skips_ui_namespace():
    older = _release()
    newer = _release(tag_name="v1.45.0")
    newer["assets"][0]["browser_download_url"] = newer["assets"][0][
        "browser_download_url"].replace("/v1.44.0/", "/v1.45.0/")
    ui_release = _release(tag_name="vantage-ui-v9.0.0")
    assert str(select_companion_release(
        [older, ui_release, newer]).version) == "1.45.0"


def test_history_skips_later_ui_draft_and_prerelease_companion_entries():
    stable = _release(tag_name="v1.45.0")
    stable["assets"][0]["browser_download_url"] = stable["assets"][0][
        "browser_download_url"].replace("/v1.44.0/", "/v1.45.0/")
    draft = _release(tag_name="v9.0.0", draft=True)
    prerelease = _release(tag_name="v8.0.0", prerelease=True)
    ui_release = _release(tag_name="vantage-ui-v99.0.0")

    selected = select_companion_release(
        [ui_release, draft, prerelease, stable])

    assert selected.tag == "v1.45.0"


def test_release_history_request_bypasses_stale_network_cache():
    request = UpdateController._request(None, RELEASE_HISTORY_API)

    assert bytes(request.rawHeader("Cache-Control")) == b"no-cache"
    assert request.attribute(
        QNetworkRequest.Attribute.CacheLoadControlAttribute) == (
            QNetworkRequest.CacheLoadControl.AlwaysNetwork)
    assert request.attribute(
        QNetworkRequest.Attribute.CacheSaveControlAttribute) is False


def test_newest_named_companion_asset_malformed_fails_not_fallback():
    newest = _release(tag_name="v1.45.0")
    newest["assets"][0]["digest"] = ""
    with pytest.raises(ValueError, match="SHA-256"):
        select_companion_release([_release(), newest])


@pytest.mark.parametrize("tag", [
    "1.44.0", "V1.44.0", "v1.44", "v1.44.0-beta", "vantage-ui-v1.44.0"])
def test_companion_parser_requires_exact_stable_namespace(tag):
    with pytest.raises(ValueError, match="exact v<semver>"):
        parse_release_payload(_release(tag_name=tag))


def test_companion_asset_url_is_pinned_to_selected_tag():
    payload = _release(tag_name="v1.45.0")
    with pytest.raises(ValueError, match="exact tag"):
        parse_release_payload(payload)
