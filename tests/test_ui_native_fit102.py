"""Native source fit and bounded paint evidence; not game-renderer certification."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
STATES = ('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled')
DONE_CELLS = tuple((380, 24 + 24 * i, 80, 22) for i in range(5))
# Decoded RGBA outside the reserved cells and normalized XML measured before
# this change. No historical checkout or Git executable is needed by tests.
PROTECTED_RGBA = '23a1c4fe567ad6b4d56ecf10c6c3dde6d45d01bd353d9dcddc033ea7ba738dc4'
SPELLBOOK_XML = 'b5c8ecb9a4b10afcf1a81af70379241221331d45393f4857c6c46fecea0925da'
HOTBAR_XML = 'c35b1b59d485e54f93868e54dd2b987cfaaa725e1ef992ddc76d9d624a944141'
SHARED_ART = {
    'window_pieces03_modern.png': '8c250d5f7a1e199360d1910a702f570ba965df972e0b19db4b9f4910dfd00529',
    'classic_pieces01.tga': 'b8fc8eebe8e463e88e60538efc21ff51e416177336309ab8d54a5535bbec2e56',
}


def digest(data):
    return sha256(data).hexdigest()


def signature(node):
    return (node.tag, sorted(node.attrib.items()), (node.text or '').strip(),
            [signature(child) for child in node])


def xml_digest(root):
    return digest(json.dumps(signature(root), separators=(',', ':')).encode())


def item(root, tag, name):
    nodes = root.findall(f"{tag}[@item='{name}']")
    assert len(nodes) == 1
    return nodes[0]


def rect(node):
    return tuple(int(node.findtext(path)) for path in
                 ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))


def image_rgba(path):
    qt = pytest.importorskip('PySide6.QtGui')
    image = qt.QImage(str(path)).convertToFormat(qt.QImage.Format.Format_RGBA8888)
    assert not image.isNull()
    assert image.bytesPerLine() == image.width() * 4
    return image.width(), image.height(), bytes(image.constBits())


def pixel(data, x, y, width=512):
    pos = 4 * (y * width + x)
    return data[pos:pos + 4]


def protected_pixels(data):
    allowed = {(x, y) for cx, cy, cw, ch in DONE_CELLS
               for y in range(cy, cy + ch) for x in range(cx, cx + cw)}
    return b''.join(pixel(data, x, y) for y in range(256) for x in range(512)
                    if (x, y) not in allowed)


def test_spellbook_done_art_matches_native_size_and_preserves_all_existing_fields():
    root = ET.parse(SKIN / 'EQUI_SpellBookWnd.xml').getroot()
    done = item(root, 'Button', 'SBW_DoneButton')
    assert rect(done) == (142, 189, 80, 22)
    assert done.findtext('ScreenID') == 'DoneButton'
    assert done.findtext('Text') == 'Done'
    assert rect(item(root, 'Ui2DAnimation', 'SBW_A_ModernPanel').find('Frames')) == (0, 0, 364, 215)
    assert len([n for n in root.findall('Ui2DAnimation')
                if n.attrib['item'].startswith('SBW_A_Done')]) == 5
    texture = item(root, 'TextureInfo', 'spellbook_modern.png')
    assert tuple(int(texture.findtext(path)) for path in ('Size/CX', 'Size/CY')) == (512, 256)
    for state, cell in zip(STATES, DONE_CELLS):
        name = 'SBW_A_Done' + state
        assert done.findtext('ButtonDrawTemplate/' + state) == name
        animation = item(root, 'Ui2DAnimation', name)
        assert animation.findtext('Cycle') == 'false'
        frames = animation.findall('Frames')
        assert len(frames) == 1
        assert frames[0].findtext('Texture') == 'spellbook_modern.png'
        assert rect(frames[0]) == cell
        assert (frames[0].findtext('Hotspot/X'), frames[0].findtext('Hotspot/Y')) == ('0', '0')
        assert frames[0].findtext('Duration') == '1000'
        root.remove(animation)
        done.find('ButtonDrawTemplate/' + state).text = 'A_Btn' + state
    # Normalizing only the five allowed additions/reference changes restores
    # the entire original tree: native IDs, parent/order, text and all fields.
    assert xml_digest(root) == SPELLBOOK_XML


def test_exactly_forty_hotbar_spell_gems_use_native_square_background_only():
    root = ET.parse(SKIN / 'EQUI_HotButtonWnd.xml').getroot()
    shared = ET.parse(SKIN / 'EQUI_Animations.xml').getroot()
    background = item(shared, 'Ui2DAnimation', 'A_SquareBtnFlyby').find('Frames')
    assert rect(background) == (40, 120, 40, 40)
    assert background.findtext('Texture') == 'window_pieces03_modern.png'
    holder = item(root, 'Ui2DAnimation', 'HB_SpellGemHolder').find('Frames')
    assert rect(holder) == (40, 117, 40, 40)
    assert holder.findtext('Texture') == 'classic_pieces01.tga'
    gems = root.findall('SpellGem')
    assert len(gems) == 40
    expected = []
    for index in range(4):
        prefix = 'HB' if index == 0 else f'HB{index + 1}'
        names = [f'{prefix}_SpellGem{i}' for i in range(1, 11)]
        expected.extend(names)
        screen_name = 'HotButtonWnd' + (str(index + 1) if index else '')
        pieces = [n.text for n in item(root, 'Screen', screen_name).findall('Pieces')]
        assert [n for n in pieces if n in names] == names
        assert all(pieces.count(n) == 1 for n in names)
    assert [n.attrib['item'] for n in gems] == expected
    for gem in gems:
        assert gem.findtext('ScreenID') == gem.attrib['item']
        assert (gem.findtext('Size/CX'), gem.findtext('Size/CY')) == ('40', '40')
        assert (gem.findtext('SpellIconOffsetX'), gem.findtext('SpellIconOffsetY')) == ('7', '7')
        assert gem.findtext('SpellGemDrawTemplate/Holder') == 'HB_SpellGemHolder'
        assert gem.findtext('SpellGemDrawTemplate/Background') == 'A_SquareBtnFlyby'
        gem.find('SpellGemDrawTemplate/Background').text = 'A_BtnFlyby'
    assert xml_digest(root) == HOTBAR_XML
    for name, baseline in SHARED_ART.items():
        assert digest((SKIN / name).read_bytes()) == baseline


def test_spellbook_protected_rgba_and_clear_padded_cells_are_preserved():
    width, height, data = image_rgba(SKIN / 'spellbook_modern.png')
    assert (width, height) == (512, 256)
    assert digest(protected_pixels(data)) == PROTECTED_RGBA
    for cx, cy, cw, ch in DONE_CELLS:
        for x, y in ((cx, cy), (cx + cw - 1, cy),
                     (cx, cy + ch - 1), (cx + cw - 1, cy + ch - 1)):
            assert pixel(data, x, y) == b'\0\0\0\0'
        for y in range(cy - 1, cy + ch + 1):
            assert pixel(data, cx - 1, y) == pixel(data, cx + cw, y) == b'\0\0\0\0'
        for x in range(cx - 1, cx + cw + 1):
            assert pixel(data, x, cy - 1) == pixel(data, x, cy + ch) == b'\0\0\0\0'


def test_five_native_done_states_have_thin_coverage_rims_and_distinct_depth():
    _, _, data = image_rgba(SKIN / 'spellbook_modern.png')
    centers, rims, payloads = [], [], []
    for cx, cy, cw, ch in DONE_CELLS:
        center = pixel(data, cx + cw // 2, cy + ch // 2)
        rim = pixel(data, cx + cw // 2, cy)
        assert center[3] == 255 and center[0] == center[1] == center[2]
        assert 0 < rim[3] < 255
        assert rim[0] > rim[1] > rim[2] > center[2]
        assert pixel(data, cx + cw // 2, cy + 1)[3] == 255
        assert len(set(pixel(data, cx + cw // 2, cy + 1)[:3])) == 1
        assert all(pixel(data, cx + x, cy + y)[3] == pixel(data, cx + cw - 1 - x, cy + y)[3]
                   for y in range(ch) for x in range(cw))
        payloads.append(b''.join(pixel(data, cx + x, cy + y)
                                 for y in range(ch) for x in range(cw)))
        centers.append(center[0])
        rims.append(rim[0])
    assert len(set(payloads)) == len(set(centers)) == 5
    assert centers[1] > centers[0] > centers[2] > centers[4]
    assert centers[3] > centers[2]
    assert rims[1] > rims[0] > rims[4]
    assert rims[3] > rims[2] > rims[4]
    for index in (0, 1):
        cx, cy, _, _ = DONE_CELLS[index]
        assert pixel(data, cx + 40, cy + 3)[0] > pixel(data, cx + 40, cy + 18)[0]
    for index in (2, 3):
        cx, cy, _, _ = DONE_CELLS[index]
        assert pixel(data, cx + 40, cy + 3)[0] < pixel(data, cx + 40, cy + 18)[0]


def ps_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def test_done_generator_reproduces_faces_is_idempotent_and_preserves_protected_rgba(tmp_path):
    powershell = (Path(os.environ.get('SystemRoot', r'C:\Windows'))
                  / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    if os.name != 'nt' or not powershell.is_file():
        pytest.skip('Native System.Drawing verification requires Windows PowerShell 5.')
    qt = pytest.importorskip('PySide6.QtGui')
    shipping = SKIN / 'spellbook_modern.png'
    rendered = tmp_path / shipping.name
    shutil.copyfile(shipping, rendered)
    sentinel_folder = tmp_path / 'sentinel'
    sentinel_folder.mkdir()
    sentinel = sentinel_folder / shipping.name
    image = qt.QImage(str(shipping)).convertToFormat(qt.QImage.Format.Format_RGBA8888)
    image.setPixelColor(500, 200, qt.QColor(18, 52, 86, 0))
    image.setPixelColor(40, 100, qt.QColor(21, 43, 65, 87))
    for cx, cy, cw, ch in DONE_CELLS:
        for y in range(cy, cy + ch):
            for x in range(cx, cx + cw):
                image.setPixelColor(x, y, qt.QColor(0, 0, 0, 0))
    assert image.save(str(sentinel), 'PNG')
    original = image_rgba(sentinel)[2]
    invalid_folder = tmp_path / 'invalid'
    invalid_folder.mkdir()
    invalid = invalid_folder / shipping.name
    wrong_size = qt.QImage(512, 255, qt.QImage.Format.Format_RGBA8888)
    wrong_size.fill(0)
    assert wrong_size.save(str(invalid), 'PNG')
    invalid_bytes = invalid.read_bytes()
    wrong_name = tmp_path / 'unrelated.png'
    shutil.copyfile(shipping, wrong_name)
    lines = ["$ErrorActionPreference = 'Stop'",
             'Add-Type -TypeDefinition (Get-Content ' + ps_quote(ROOT / 'scripts' / 'ui_spellbook_done_controls.cs')
             + ' -Raw) -ReferencedAssemblies System.Drawing']
    for path in (rendered, sentinel):
        render = '[VantageSpellbookDoneControls]::Render(' + ps_quote(path) + ')'
        lines.extend((render,
                      '$firstBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes(' + ps_quote(path) + '))',
                      render,
                      '$secondBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes(' + ps_quote(path) + '))',
                      "if ($firstBytes -ne $secondBytes) { throw 'Rendering changed on repeat.' }"))
    for path in (invalid, wrong_name):
        lines.extend(('$rejected = $false',
                      'try { [VantageSpellbookDoneControls]::Render(' + ps_quote(path)
                      + ') } catch { $rejected = $true }',
                      "if (-not $rejected) { throw 'Invalid atlas was accepted.' }"))
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-Command', '\n'.join(lines)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert rendered.read_bytes() == shipping.read_bytes()
    actual = image_rgba(sentinel)[2]
    expected = image_rgba(shipping)[2]
    assert protected_pixels(actual) == protected_pixels(original)
    assert pixel(actual, 500, 200) == b'\x12\x34\x56\0'
    for cx, cy, cw, ch in DONE_CELLS:
        for y in range(cy, cy + ch):
            for x in range(cx, cx + cw):
                assert pixel(actual, x, y) == pixel(expected, x, y)
    assert invalid.read_bytes() == invalid_bytes
    assert wrong_name.read_bytes() == shipping.read_bytes()
