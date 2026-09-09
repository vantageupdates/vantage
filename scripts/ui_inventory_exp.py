"""Generate native-size inventory EXP sprites from the unchanged shared gauge art.

The client does not stretch a 100px gauge animation to its 118px control.
Only horizontal sampling changes; original height, alpha, shading and caps stay.
"""
from pathlib import Path
import struct

WIDTH = 118
PARTS = ('Background', 'Fill', 'Lines', 'LinesFill')


def read_tga(path):
    data = path.read_bytes()
    h = data[:18]
    width, height = struct.unpack_from('<HH', h, 12)
    depth = h[16] // 8
    if h[1] or h[2] not in (2, 10) or depth not in (3, 4):
        raise ValueError('Expected RGB/RGBA true-color TGA')
    offset, pixels = 18 + h[0], []
    while len(pixels) < width * height:
        packet = data[offset] if h[2] == 10 else 0
        offset += h[2] == 10
        count = (packet & 127) + 1
        for i in range(count):
            if not i or not packet & 128:
                color = data[offset:offset + depth]
                offset += depth
                if depth == 3:
                    color += b'\xff'
            pixels.append(color)
    if len(pixels) != width * height:
        raise ValueError('Invalid TGA pixel count')
    rows = [pixels[y * width:(y + 1) * width] for y in range(height)]
    if not h[17] & 32:
        rows.reverse()
    if h[17] & 16:
        rows = [row[::-1] for row in rows]
    return rows


def render(source):
    original = read_tga(source)
    pixels = bytearray(128 * 64 * 4)
    for part in range(4):
        for y in range(8):
            for x in range(WIDTH):
                # Integer nearest sampling, with both original end pixels intact.
                sx = (x * 99 + (WIDTH - 1) // 2) // (WIDTH - 1)
                dest = 4 * ((2 + part * 12 + y) * 128 + 2 + x)
                pixels[dest:dest + 4] = original[10 + part * 10 + y][110 + sx]
    header = bytearray(18)
    header[2] = 2
    struct.pack_into('<HH', header, 12, 128, 64)
    header[16:18] = bytes((32, 40))
    return bytes(header + pixels)


if __name__ == '__main__':
    skin = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
    (skin / 'VantageInventoryExp.tga').write_bytes(render(skin / 'window_pieces01.tga'))
