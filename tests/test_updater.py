import pytest

from vantage.helpers.updater import ASSET_NAME, parse_release_payload


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

