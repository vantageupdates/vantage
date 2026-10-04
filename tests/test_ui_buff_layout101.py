"""Native source/paint regressions; actual client rendering still needs a reload."""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
STATES = ('Normal', 'Pressed', 'Flyby', 'Disabled', 'PressedFlyby')


def xml(filename):
    return ET.parse(SKIN / filename).getroot()


def item(root, tag, name):
    matches = root.findall(f"{tag}[@item='{name}']")
    assert len(matches) == 1
    return matches[0]


def pixel(data, x, y):
    pos = 18 + 4 * (y * 64 + x)
    return tuple(data[pos:pos + 4])


@pytest.mark.parametrize('filename,prefix,parent,count', [
    ('EQUI_BuffWindow.xml', 'BW', 'BuffWindow', 25),
    ('EQUI_ShortDurationBuffWindow.xml', 'SDBW', 'ShortDurationBuffWindow', 12),
])
def test_buff_buttons_have_explicit_preset_locations_and_native_bindings(filename, prefix, parent, count):
    root = xml(filename)
    screen = item(root, 'Screen', parent)
    pieces = [p.text for p in screen.findall('Pieces')]
    names = [f'{prefix}_Buff{i}_Button' for i in range(count)]
    assert [p for p in pieces if p in names] == names
    for i, name in enumerate(names):
        button = item(root, 'Button', name)
        assert button.findtext('ScreenID') == f'Buff{i}'
        assert button.findtext('RelativePosition') == 'true'
        # The main window is the optional UI103 horizontal preset. The
        # disabled short-duration window keeps its original vertical source.
        bounds = (6 + 28 * i, 4, 24, 24) if prefix == 'BW' else (175, 1 + 25 * i, 24, 24)
        assert tuple(int(button.findtext(p)) for p in
                     ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY')) == bounds
        assert button.findtext('Style_Transparent') == 'true'
        assert button.findtext('Style_Border') == 'false'
        assert button.findtext('ButtonDrawTemplate/NormalDecal') == 'BuffIcons'
        assert [button.findtext('ButtonDrawTemplate/' + state) for state in STATES] == [
            'CleanBuff' + state for state in STATES]
        assert tuple(int(button.findtext(p)) for p in
                     ('DecalOffset/X', 'DecalOffset/Y', 'DecalSize/CX', 'DecalSize/CY')) == (2, 2, 20, 20)
        assert pieces.count(name) == 1
        label = item(root, 'Label', f'{prefix}_Buff{i}_Label')
        assert label.findtext('ScreenID') == f'Buff{i}Label'
        assert label.findtext('EQType') == str((500 if prefix == 'BW' else 600) + i)
        assert label.findtext('Location/X') == ('4' if prefix == 'BW' else '30')
        assert label.findtext('Size/CX') == ('0' if prefix == 'BW' else '142')
        assert label.findtext('AlignRight') == label.findtext('NoWrap') == 'true'
        # Both presets keep name labels outside every native icon hit box.
        assert int(label.findtext('Location/X')) + int(label.findtext('Size/CX')) < bounds[0]
    assert screen.findtext('Style_Transparent') == ('false' if prefix == 'BW' else 'true')
    assert screen.findtext('Style_Border') == ('true' if prefix == 'BW' else 'false')


def test_all_buff_chrome_states_are_fully_transparent_including_hover():
    root = xml('EQUI_BuffWindow.xml')
    data = (SKIN / 'Buff_Background.tga').read_bytes()
    assert data[:3] == bytes((0, 0, 2))
    assert data[12:18] == bytes((64, 0, 128, 0, 32, 40))
    assert len(data) == 18 + 64 * 128 * 4
    for state_index, state in enumerate(STATES):
        frame = item(root, 'Ui2DAnimation', 'CleanBuff' + state).find('Frames')
        assert frame.findtext('Texture') == 'Buff_Background.tga'
        assert tuple(int(frame.findtext(p)) for p in
                     ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY')) == (32, 24 * state_index, 24, 24)
        cell = [pixel(data, 32 + x, 24 * state_index + y) for y in range(24) for x in range(24)]
        assert set(cell) == {(0, 0, 0, 0)}, state


def test_numbered_holders_have_separate_crisp_native_contours():
    data = (SKIN / 'Buff_Background.tga').read_bytes()
    for row in range(5):
        y = 1 + 25 * row
        assert pixel(data, 1, y) == (0, 0, 0, 0)
        assert pixel(data, 13, y + 12)[3] == 255
        assert pixel(data, 13, y)[2] > pixel(data, 13, y + 12)[2] + 40
        if row < 4:
            assert all(pixel(data, 1 + x, y + 24)[3] == 0 for x in range(24))


def test_buff_atlas_bytes_outside_reviewed_cells_are_preserved():
    data = (SKIN / 'Buff_Background.tga').read_bytes()
    outside = data[:18] + b''.join(
        bytes(pixel(data, x, y)) for y in range(128) for x in range(64)
        if not (1 <= x < 25 and 1 <= y < 125 or 32 <= x < 56 and y < 120))
    assert hashlib.sha256(outside).hexdigest() == '9d51559547acd5ddb414c6262c703d376e2272396149a16a67b65e1ee9cea1a9'
