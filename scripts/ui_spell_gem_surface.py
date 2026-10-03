"""Build the muted neutral surface that EverQuest tints per spell gem.

The client supplies the spell-category hue at runtime.  A dark or colored source
surface multiplies that hue down, so the background atlas must remain neutral
while retaining enough vertical shading to read as a compact 3D control.  This
revision adds a second restrained luminance cut without altering runtime hues.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


ATLAS_WIDTH = 256
ATLAS_HEIGHT = 256
BACKGROUND_LEFT = 0
BACKGROUND_TOP = 28
LEGACY_CONTROL_WIDTH = 120
CONTROL_WIDTH = 136
BACKGROUND_WIDTH = CONTROL_WIDTH
BACKGROUND_HEIGHT = 28
CONTROL_CELLS = ((0, 28), (28, 28), (56, 28), (84, 14), (98, 14), (112, 14), (126, 14))

# Neutral ramp with the original relief and a second uniform ~7% linear-luminance
# cut.  This is roughly a 13.5%-14% total cut from the original source ramp.
# Runtime spell hues stay unchanged because no baked hue is present; only their
# intensity is reduced modestly (6.47%-7.49% from the preceding ramp after
# 8-bit rounding).
BACKGROUND_SHADES = (
    186, 206, 216, 223, 229, 232, 234, 232, 230, 227, 223, 220, 216, 212,
    208, 202, 197, 192, 186, 180, 174, 168, 163, 158, 152, 148, 160, 184,
)


def validate_atlas(data: bytes) -> None:
    if len(data) != 18 + ATLAS_WIDTH * ATLAS_HEIGHT * 4:
        raise ValueError("Expected a 256x256 uncompressed 32-bit TGA")
    if data[:3] != bytes((0, 0, 2)):
        raise ValueError("Expected an uncompressed true-color TGA")
    width, height = struct.unpack_from("<HH", data, 12)
    if (width, height, data[16], data[17]) != (ATLAS_WIDTH, ATLAS_HEIGHT, 32, 40):
        raise ValueError("Expected top-left 256x256 BGRA atlas geometry")



def widen_spell_gem_controls(data: bytes) -> bytes:
    """Insert 16 existing center pixels, preserving native endcaps without scaling.

    Only the seven native gem/header cells are touched. The width check makes
    regeneration safe to repeat after the legacy right cap has moved outward.
    """
    validate_atlas(data)
    probes = [18 + ((top + height // 2) * ATLAS_WIDTH + 128) * 4 + 3
              for top, height in CONTROL_CELLS if top != 56]
    if all(data[offset] == 255 for offset in probes):
        return data
    if any(data[offset] for offset in probes):
        raise ValueError("Unexpected spell control geometry")
    output = bytearray(data)
    insertion = LEGACY_CONTROL_WIDTH // 2
    extra = CONTROL_WIDTH - LEGACY_CONTROL_WIDTH
    for top, height in CONTROL_CELLS:
        for y in range(top, top + height):
            start = 18 + y * ATLAS_WIDTH * 4
            row = data[start:start + LEGACY_CONTROL_WIDTH * 4]
            output[start:start + CONTROL_WIDTH * 4] = (
                row[:insertion * 4] + row[insertion * 4:(insertion + 1) * 4] * extra
                + row[insertion * 4:])
    return bytes(output)


def brighten_spell_gem_background(data: bytes) -> bytes:
    """Return the atlas with only V3_CastBackground set to its neutral ramp."""
    validate_atlas(data)
    output = bytearray(data)
    for local_y, shade in enumerate(BACKGROUND_SHADES):
        y = BACKGROUND_TOP + local_y
        for x in range(BACKGROUND_LEFT, BACKGROUND_LEFT + BACKGROUND_WIDTH):
            offset = 18 + (y * ATLAS_WIDTH + x) * 4
            if output[offset + 3] == 0:
                continue
            output[offset:offset + 3] = bytes((shade, shade, shade))
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "ui" / "skin" / "v3_controls.tga",
    )
    args = parser.parse_args()
    original = args.path.read_bytes()
    refined = brighten_spell_gem_background(widen_spell_gem_controls(original))
    args.path.write_bytes(refined)


if __name__ == "__main__":
    main()
