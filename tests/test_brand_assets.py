import struct
from pathlib import Path

from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]


def test_selected_brand_artwork_builds_crisp_transparent_app_icons():
    source = QImage(str(ROOT / "data/assets/vantage-companion-logo-source.png"))
    master = QImage(str(ROOT / "data/ui/icon-master.png"))
    icon = QImage(str(ROOT / "data/ui/icon.png"))

    assert (source.width(), source.height()) == (1254, 1254)
    assert (master.width(), master.height()) == (1254, 1254)
    assert (icon.width(), icon.height()) == (256, 256)
    assert master.hasAlphaChannel()
    assert icon.hasAlphaChannel()
    assert master.pixelColor(0, 0).alpha() == 0
    assert icon.pixelColor(0, 0).alpha() == 0

    colors = [icon.pixelColor(x, y) for y in range(256) for x in range(256)]
    assert sum(
        color.alpha() > 220 and color.red() > 145
        and color.green() > 85 and color.blue() < 105
        for color in colors) > 2_000
    assert sum(
        color.alpha() > 220 and color.green() > color.red() * 1.12
        and color.blue() > color.red() * 1.08
        for color in colors) > 180


def test_windows_icon_contains_all_required_hd_and_small_frames():
    payload = (ROOT / "data/ui/icon.ico").read_bytes()
    reserved, icon_type, count = struct.unpack_from("<HHH", payload)
    assert (reserved, icon_type, count) == (0, 1, 9)
    sizes = []
    for index in range(count):
        width, height = struct.unpack_from("<BB", payload, 6 + index * 16)
        sizes.append((width or 256, height or 256))
    assert sizes == [
        (16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
        (48, 48), (64, 64), (128, 128), (256, 256),
    ]


def test_brand_is_shared_by_native_mobile_pwa_and_github_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    mobile = (ROOT / "src/vantage/helpers/mobile_share.py").read_text(
        encoding="utf-8")
    pwa = (ROOT / "companion-web/index.html").read_text(encoding="utf-8")
    assert ('src="data/ui/icon-master.png" width="168" '
            'alt="Vantage Companion') in readme
    assert 'src="/icon.png" alt=""' in mobile
    assert 'src="icon-256.png" alt=""' in pwa
    assert not (ROOT / "data/assets/icon.xcf").exists()
