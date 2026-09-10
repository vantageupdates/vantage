"""Build the neutral, high-value surface that EverQuest tints per spell gem.

The client supplies the spell-category hue at runtime.  A dark or colored source
surface multiplies that hue down, so the background atlas must stay neutral and
bright while retaining enough vertical shading to read as a compact 3D control.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


ATLAS_WIDTH = 256
ATLAS_HEIGHT = 256
BACKGROUND_LEFT = 0
BACKGROUND_TOP = 28
BACKGROUND_WIDTH = 120
BACKGROUND_HEIGHT = 28

# High-value neutral ramp: a soft highlight near the top and a controlled lower
# shadow.  Runtime spell hues remain saturated because no baked hue is present.
BACKGROUND_SHADES = (
    198, 220, 230, 238, 244, 248, 250, 248, 246, 242, 238, 234, 230, 226,
    222, 216, 210, 204, 198, 192, 186, 180, 174, 168, 162, 158, 170, 196,
)


def brighten_spell_gem_background(data: bytes) -> bytes:
    """Return the atlas with only V3_CastBackground neutralized and lifted."""
    if len(data) != 18 + ATLAS_WIDTH * ATLAS_HEIGHT * 4:
        raise ValueError("Expected a 256x256 uncompressed 32-bit TGA")
    if data[:3] != bytes((0, 0, 2)):
        raise ValueError("Expected an uncompressed true-color TGA")
    width, height = struct.unpack_from("<HH", data, 12)
    if (width, height, data[16], data[17]) != (ATLAS_WIDTH, ATLAS_HEIGHT, 32, 40):
        raise ValueError("Expected top-left 256x256 BGRA atlas geometry")

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
    refined = brighten_spell_gem_background(original)
    args.path.write_bytes(refined)


if __name__ == "__main__":
    main()
