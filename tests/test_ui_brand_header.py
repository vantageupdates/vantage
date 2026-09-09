"""Final-size header art and native-label checks; not an in-game render test."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'


def pixel(x, y):
    data = (SKIN / 'VantageBrandHeader.tga').read_bytes()
    pos = 18 + 4 * (256 * (y + 2) + x + 2)
    return tuple(data[pos:pos + 4])  # BGRA, header-local coordinates


def test_brand_texture_is_small_flat_and_does_not_pack_reference_version_digits():
    data = (SKIN / 'VantageBrandHeader.tga').read_bytes()
    assert len(data) == 18 + 256 * 32 * 4
    assert data[:3] == bytes((0, 0, 2))
    assert data[12:18] == bytes((0, 1, 32, 0, 32, 40))
    # The entire version label's interior is blank; future native digits replace
    # the release label, never an image containing the concept's old version.
    assert all(pixel(x, y) == (16, 16, 16, 255)
               for x in range(128, 184) for y in range(4, 16))
    assert not list(SKIN.glob('*approved*'))


def test_wordmark_keeps_gold_shapes_and_a_clear_gutter_before_badge():
    gold = [pixel(x, y) for x in range(18, 112) for y in range(20)
            if pixel(x, y)[2] - pixel(x, y)[0] > 20]
    assert len(gold) > 500
    assert len(set(gold)) > 100  # Actual shaded artwork, not a plain label.
    assert all(pixel(x, y) == (16, 16, 16, 255)
               for x in range(114, 124) for y in range(2, 18))


def test_diamond_is_visible_to_the_left_at_native_size_with_a_tapered_silhouette():
    def gold(x,y):
        return pixel(x,y)[2] - pixel(x,y)[0] > 20
    # Previously this space was blank; the diamond is real artwork, not a label.
    assert sum(gold(x,y) for x in range(12,18) for y in range(20)) >= 20
    rows = [sum(gold(x,y) for x in range(12,25)) for y in range(20)]
    assert rows[8] >= 10
    assert rows[8] > rows[2] > rows[0]
    assert rows[8] > rows[14] > rows[17]
    assert rows[18] == rows[19] == 0
    assert len({pixel(x,y) for x in range(12,25) for y in range(18) if gold(x,y)}) > 50


def test_diamond_source_is_kept_outside_the_client_payload():
    source=SKIN.parent/'artwork'/'vantage-ui-diamond.png'
    assert source.is_file()
    assert not (SKIN/source.name).exists()
    data=source.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert (int.from_bytes(data[16:20],'big'),int.from_bytes(data[20:24],'big')) == (2172,724)


def test_version_frame_is_single_subtle_rounded_line():
    # Corners are background; center of the long edges has a fine, soft rim.
    assert pixel(124, 1) == pixel(187, 1) == (16, 16, 16, 255)
    for x in range(133, 178):
        assert 45 < pixel(x, 1)[2] < 160
        assert pixel(x, 3) == pixel(x, 16) == (16, 16, 16, 255)
    for x in (0, 201):
        for y in (0, 19):
            assert pixel(x, y) == (0, 0, 0, 0)


def test_logo_change_does_not_touch_existing_control_art():
    expected = {
        'VantageControlEdges.tga': 'bb5c99fa1973a6b6446cf16f43fd8534254f047593ddcae090d38141f86efe04',
        'VantageSlotHints.tga': '0e214c71cc332db388c12ddf10db55896e7fcf761549f75d0d41313fd0c3fadf',
        'classic_pieces01.tga': 'b8fc8eebe8e463e88e60538efc21ff51e416177336309ab8d54a5535bbec2e56',
        'quickbar_frames.tga': 'efdc8c0053136d4c1827b1840bdf00a850d62897ea80c1b7c915eaf9ced6f477',
        'v3_controls.tga': '394e51ed575f895b6c35a367b0f783aec7aebc18002a2a6e3e1989ac2b8e5ace',
    }
    for name, digest in expected.items():
        assert hashlib.sha256((SKIN / name).read_bytes()).hexdigest() == digest


def test_native_version_is_static_readable_and_in_its_own_frame():
    root = ET.parse(SKIN / 'EQUI_HotButtonWnd.xml').getroot()
    label = root.find("Label[@item='HB_VantageVersionLabel']")
    assert label.findtext('Font') == '2'
    assert label.findtext('NoWrap') == label.findtext('AlignCenter') == 'true'
    assert label.find('EQType') is None
    assert (int(label.findtext('Location/X')), int(label.findtext('Size/CX'))) == (129, 56)
    rgb = [int(label.findtext('TextColor/' + c)) / 255 for c in 'RGB']
    def linear(v):
        return v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
    luminance = sum(linear(v) * w for v, w in zip(rgb, (.2126, .7152, .0722)))
    assert (luminance + .05) / (linear(16 / 255) + .05) > 9
