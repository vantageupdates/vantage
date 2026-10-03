"""Bounded native art changes; pixel evidence is not game-renderer certification."""
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'ui' / 'skin'
STATES = ('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled')
SLOTS = (
    (2, 2, 6, 1), (10, 2, 1, 1), (13, 2, 6, 1),
    (21, 2, 1, 5), (24, 2, 1, 1), (27, 2, 1, 5),
    (30, 2, 6, 1), (38, 2, 1, 1), (41, 2, 6, 1),
    (49, 2, 1, 5), (52, 2, 1, 1), (55, 2, 1, 5),
)
ACTIONS = tuple((352, 4 + 24 * state, 128, 18) for state in range(5))
PET = tuple((x, y, 62, 18) for x, y in
            ((128, 34), (256, 34), (256, 54), (256, 74), (256, 94)))
COMPACT = tuple((x, y + 23 * state, w, h)
                for x, y, w, h in
                ((2, 2, 123, 20), (130, 2, 61, 20),
                 (2, 128, 60, 20), (67, 128, 50, 20))
                for state in range(5))
GROUP = tuple((2, 2 + 20 * state, 56, 16) for state in range(5))
ATLASES = (
    ('VantageControlEdges.tga', 512, 128, SLOTS + ACTIONS + PET, ACTIONS + PET),
    ('VantageCompactControls.tga', 256, 256, COMPACT, COMPACT),
    ('VantageGroupControls.tga', 128, 128, GROUP, GROUP),
)

# Measured directly from committed 1.44.100 art at 8a6ed18. These hashes pin
# every alpha byte, header/protected pixels, clear-pixel BGRA and inner faces.
# Tests need no Git executable or historical checkout at runtime.
BASELINE = {
    'VantageControlEdges.tga': (
        '32ee3fd82e7976a3f9cc2303672dfdfe9c88d5c2940f1687a4e2ee0ca0b65b3f',
        '004dcbcb588c9930cf04fcc7a9ced53767dda2545d53767644a33a28bb647dd0',
        'ed6b703a94754b6235139fa05ffa469d92ddecfc70900ee702b848842579ae2c',
        '42ab7212d43bc41acaef4f908fc8ededef7f741d50cc5903fb4003a2530c1f57',
    ),
    'VantageCompactControls.tga': (
        '4eb4f075f2bf1dc9e51a2080ce4492a7dc5648ffd3ea8ce625d3889aea2ccfe5',
        '364229aeb0db29b66b566567cd56236983bb4691821d1ac2a1cadeb71e130395',
        'e651960ec67ad241a233e0ef6da54efd8bd7c235b1cf1eaf5eaf4e91c566bd04',
        '481ab599eb0a97f35805132a3a1decc7d7be391620e4751491a11b2de29341b9',
    ),
    'VantageGroupControls.tga': (
        'fcb72e78fc532905fc340692296d16017473db54e2172e934f3b0f1c94fcbf0b',
        'f7920ed6aa54afea65127eeb867628bb695469746319b2ed2e4eb6c6d10d90e5',
        'd1832349a007b0f603b1b5e25b3fae14b5beffa622eb1a2d273a1cb7f78b6ffe',
        'd29872dbbde974d1dbfffb6ba127f1a566ff0b7c8876feb0dbe23291fba39ea3',
    ),
}


def digest(data):
    return sha256(data).hexdigest()


def pixel(data, width, x, y):
    offset = 18 + 4 * (y * width + x)
    return data[offset:offset + 4]


def protected_pixels(data, width, height, cells):
    allowed = {(x, y) for cx, cy, cw, ch in cells
               for y in range(cy, cy + ch) for x in range(cx, cx + cw)}
    return data[:18] + b''.join(pixel(data, width, x, y)
                                for y in range(height) for x in range(width)
                                if (x, y) not in allowed)


def inner_faces(data, width, cells):
    return b''.join(pixel(data, width, cx + x, cy + y)
                    for cx, cy, cw, ch in cells
                    for y in range(3, ch - 3) for x in range(8, cw - 8))


@pytest.mark.parametrize('name,width,height,cells,buttons', ATLASES)
def test_all_alpha_protected_pixels_clear_pixels_and_faces_match_100_baseline(
        name, width, height, cells, buttons):
    data = (SKIN / name).read_bytes()
    assert len(data) == 18 + width * height * 4
    assert data[:3] == bytes((0, 0, 2))
    assert data[12:18] == (width.to_bytes(2, 'little')
                           + height.to_bytes(2, 'little') + bytes((32, 40)))
    alpha_hash, outside_hash, clear_hash, face_hash = BASELINE[name]
    assert digest(data[21::4]) == alpha_hash
    assert digest(protected_pixels(data, width, height, cells)) == outside_hash
    clear = b''.join(data[i:i + 4] for i in range(18, len(data), 4)
                     if data[i + 3] == 0)
    assert digest(clear) == clear_hash
    assert digest(inner_faces(data, width, buttons)) == face_hash


@pytest.mark.parametrize('name,width,height,cells,buttons', ATLASES)
def test_every_button_keeps_clear_corners_and_atlas_gutters(
        name, width, height, cells, buttons):
    data = (SKIN / name).read_bytes()
    for x, y, w, h in buttons:
        assert x > 0 and y > 0 and x + w < width and y + h < height
        for px, py in ((x, y), (x + w - 1, y),
                       (x, y + h - 1), (x + w - 1, y + h - 1)):
            # Color.Transparent in the original System.Drawing atlas stores
            # white RGB with zero alpha. The baseline hash pins those bytes.
            assert pixel(data, width, px, py)[3] == 0
        for py in range(y - 1, y + h + 1):
            assert pixel(data, width, x - 1, py)[3] == 0
            assert pixel(data, width, x + w, py)[3] == 0
        for px in range(x - 1, x + w + 1):
            assert pixel(data, width, px, y - 1)[3] == 0
            assert pixel(data, width, px, y + h)[3] == 0


def test_slot_rim_lifts_only_existing_gold_pixels():
    data = (SKIN / 'VantageControlEdges.tga').read_bytes()
    visible = 0
    for cx, cy, cw, ch in SLOTS:
        for y in range(cy, cy + ch):
            for x in range(cx, cx + cw):
                b, g, r, alpha = pixel(data, 512, x, y)
                if alpha:
                    assert (r, g, b) == (142, 119, 80)
                    visible += 1
    assert visible > 0


@pytest.mark.parametrize('name,width,height,cells,buttons', ATLASES)
def test_rims_are_local_and_states_remain_distinct(name, width, height, cells, buttons):
    data = (SKIN / name).read_bytes()
    for start in range(0, len(buttons), 5):
        family = buttons[start:start + 5]
        center_tones = []
        rim_tones = []
        for cx, cy, cw, ch in family:
            center = pixel(data, width, cx + cw // 2, cy + ch // 2)
            rim = pixel(data, width, cx + cw // 2, cy)
            assert center[0] == center[1] == center[2]
            assert center[3] == 255
            assert all(rim[channel] > center[channel] for channel in range(3))
            center_tones.append(center[0])
            rim_tones.append(rim[2])
        assert len(set(center_tones)) == 5
        assert rim_tones[1] > rim_tones[0] > rim_tones[4]
        assert rim_tones[3] > rim_tones[2] > rim_tones[4]
    if name != 'VantageControlEdges.tga':
        for cx, cy, cw, ch in buttons:
            assert all(len(set(pixel(data, width, cx + x, cy + y)[:3])) == 1
                       for y in range(ch) for x in range(cw))


def test_actions_pet_and_slot_slice_xml_keep_exact_existing_rectangles():
    for filename, prefix, cells in (
        ('EQUI_ActionsWindow.xml', 'A_VantageActions', ACTIONS),
        ('EQUI_PetInfoWindow.xml', 'A_VantagePet', PET),
    ):
        root = ET.parse(SKIN / filename).getroot()
        for state, expected in zip(STATES, cells):
            frame = root.find(f"Ui2DAnimation[@item='{prefix}{state}']/Frames")
            assert frame is not None
            assert frame.findtext('Texture') == 'VantageControlEdges.tga'
            actual = tuple(int(frame.findtext(path)) for path in
                           ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))
            assert actual == expected
    root = ET.parse(SKIN / 'EQUI_Animations.xml').getroot()
    roles = ('TopLeft', 'Top', 'TopRight', 'RightTop', 'Right', 'RightBottom',
             'BottomRight', 'Bottom', 'BottomLeft', 'LeftTop', 'Left', 'LeftBottom')
    for role, expected in zip(roles, SLOTS):
        frame = root.find(f"Ui2DAnimation[@item='A_VantageSlotGold{role}']/Frames")
        assert frame is not None
        assert frame.findtext('Texture') == 'VantageControlEdges.tga'
        assert tuple(int(frame.findtext(path)) for path in
                     ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY')) == expected


def ps_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def test_native_generators_reproduce_shipping_art_and_patch_is_idempotent(tmp_path):
    powershell = (Path(os.environ.get('SystemRoot', r'C:\Windows'))
                  / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    if os.name != 'nt' or not powershell.is_file():
        pytest.skip('Native System.Drawing verification requires Windows PowerShell 5.')
    output = tmp_path / 'render'
    output.mkdir()
    edge = output / 'VantageControlEdges.tga'
    shutil.copyfile(SKIN / edge.name, edge)
    sentinel = tmp_path / 'sentinel'
    sentinel.mkdir()
    sentinel_edge = sentinel / edge.name
    original = bytearray(edge.read_bytes())
    original[18 + 4 * (127 * 512 + 500):22 + 4 * (127 * 512 + 500)] = b'\x12\x34\x56\x78'
    # Transparent RGB inside an allowed cell and custom alpha must survive.
    original[18 + 4 * (4 * 512 + 352):22 + 4 * (4 * 512 + 352)] = b'\x24\x35\x46\x00'
    original[18 + 4 * (4 * 512 + 416) + 3] = 99
    sentinel_edge.write_bytes(original)
    invalid = tmp_path / 'invalid'
    invalid.mkdir()
    invalid_edge = invalid / edge.name
    malformed = bytearray(original)
    malformed[14] = 127
    invalid_edge.write_bytes(malformed)
    wrong_name = tmp_path / 'not-control-art.tga'
    wrong_name.write_bytes(original)
    short = tmp_path / 'short'
    short.mkdir()
    short_edge = short / edge.name
    short_edge.write_bytes(original[:-4])
    lines = ["$ErrorActionPreference = 'Stop'"]
    for script in ('ui_compact_controls.cs', 'ui_group_controls.cs', 'ui_control_edges.cs'):
        lines.append('Add-Type -TypeDefinition (Get-Content '
                     + ps_quote(ROOT / 'scripts' / script)
                     + ' -Raw) -ReferencedAssemblies System.Drawing')
    lines.extend((
        '[VantageCompactControls]::Render('
        + ps_quote(output / 'VantageCompactControls.tga') + ', $null)',
        '[VantageGroupControls]::Render('
        + ps_quote(output / 'VantageGroupControls.tga') + ', $null)',
    ))
    for path in (edge, sentinel_edge):
        patch = ('[VantageControlEdgesRenderer]::PatchCrispControls('
                 + ps_quote(path) + ')')
        lines.extend((
            patch,
            '$firstBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes('
            + ps_quote(path) + '))',
            patch,
            '$secondBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes('
            + ps_quote(path) + '))',
            "if ($firstBytes -ne $secondBytes) { throw 'Patch changed on repeat.' }",
        ))
    for path in (invalid_edge, wrong_name, short_edge):
        lines.extend((
            '$rejected = $false',
            'try { [VantageControlEdgesRenderer]::PatchCrispControls('
            + ps_quote(path) + ') } catch { $rejected = $true }',
            "if (-not $rejected) { throw 'Invalid atlas was accepted.' }",
        ))
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-Command', '\n'.join(lines)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    for name, _, _, _, _ in ATLASES:
        assert (output / name).read_bytes() == (SKIN / name).read_bytes()
    patched_sentinel = sentinel_edge.read_bytes()
    assert patched_sentinel[21::4] == original[21::4]
    assert protected_pixels(patched_sentinel, 512, 128, SLOTS + ACTIONS + PET) == (
        protected_pixels(original, 512, 128, SLOTS + ACTIONS + PET))
    assert pixel(patched_sentinel, 512, 352, 4) == b'\x24\x35\x46\x00'
    assert invalid_edge.read_bytes() == malformed
    assert wrong_name.read_bytes() == original
    assert short_edge.read_bytes() == original[:-4]
