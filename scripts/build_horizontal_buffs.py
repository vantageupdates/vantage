"""Lay out the existing Titanium buff controls as a fixed horizontal preset.

This changes geometry and native window chrome only. It does not create buff
controls, change native IDs, replace spell art, or touch a character's UI INI.
The vertical preset remains available in the separately published UI102 skin.
Native tooltips, cancellation, and titlebar clipping need a client reload to
validate; XML geometry checks cannot certify the game renderer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "ui" / "skin" / "EQUI_BuffWindow.xml"
BUFF_COUNT = 25
ICON_SIZE = 24
ICON_PITCH = 28
ICON_X = 6
ICON_Y = 4
WINDOW_WIDTH = 716
WINDOW_HEIGHT = 56


def _change_child(block: str, parent: str, child: str, value: str) -> str:
    """Replace exactly one existing field, preserving XML formatting."""
    pattern = (rf"(<{parent}>\s*(?:<[^>]+>[^<]*</[^>]+>\s*)*?"
               rf"<{child}>)[^<]*(</{child}>)")
    block, count = re.subn(pattern, lambda match: match[1] + value + match[2], block)
    if count != 1:
        raise ValueError(f"Expected one {parent}/{child}, found {count}")
    return block


def _change_field(block: str, field: str, value: str) -> str:
    pattern = rf"(<{field}>)[^<]*(</{field}>)"
    block, count = re.subn(pattern, lambda match: match[1] + value + match[2], block)
    if count != 1:
        raise ValueError(f"Expected one {field}, found {count}")
    return block


def _change_item(source: str, kind: str, name: str, fields: dict[str, str]) -> str:
    pattern = rf'(<{kind} item="{re.escape(name)}">.*?</{kind}>)'

    def replace(match: re.Match[str]) -> str:
        block = match[1]
        for field, value in fields.items():
            if "/" in field:
                parent, child = field.split("/", 1)
                block = _change_child(block, parent, child, value)
            else:
                block = _change_field(block, field, value)
        return block

    result, count = re.subn(pattern, replace, source, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"Expected one {kind} {name}, found {count}")
    return result


def _rect(x: int, y: int, width: int, height: int) -> dict[str, str]:
    return dict(zip(("Location/X", "Location/Y", "Size/CX", "Size/CY"),
                    map(str, (x, y, width, height))))


def horizontal_preset(source: str) -> str:
    """Keep the original native controls/Pieces and change only their layout."""
    before = ET.fromstring(source)
    buttons = before.findall("Button")
    if [node.findtext("ScreenID") for node in buttons] != [
            f"Buff{i}" for i in range(BUFF_COUNT)]:
        raise ValueError("Expected exactly the original Buff0 through Buff24 controls")

    result = source
    for index in range(BUFF_COUNT):
        # Coordinates are inside the native client area. WDT_Rounded has a
        # 16px titlebar and up to 4px frame insets, leaving 708x32 client pixels
        # in the 716x56 outer screen. Do not reserve the title a second time.
        # A button's size and decal fields are native contracts, not layout.
        result = _change_item(result, "Button", f"BW_Buff{index}_Button", {
            "Location/X": str(ICON_X + ICON_PITCH * index),
            "Location/Y": str(ICON_Y),
        })

    # Keep every original Piece and every EQType assignment. A zero-sized
    # text/decorative lane leaves native icon hit boxes unobstructed and keeps
    # long spell names from extending a compact horizontal preset.
    for kind in ("Label", "StaticAnimation"):
        for node in before.findall(kind):
            result = _change_item(result, kind, node.attrib["item"], _rect(4, 20, 0, 0))

    result = _change_item(result, "Screen", "BuffWindow", {
        **_rect(415, 395, WINDOW_WIDTH, WINDOW_HEIGHT),
        "Style_Transparent": "false",
        "DrawTemplate": "WDT_Rounded",
        "Style_Titlebar": "true",
        "Style_Border": "true",
    })
    after = ET.fromstring(result)
    original_screen = before.find("Screen[@item='BuffWindow']")
    horizontal_screen = after.find("Screen[@item='BuffWindow']")
    if original_screen is None or horizontal_screen is None:
        raise ValueError("Missing native BuffWindow screen")
    if [node.text for node in original_screen.findall("Pieces")] != [
            node.text for node in horizontal_screen.findall("Pieces")]:
        raise ValueError("Horizontal layout changed the native Piece list")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path,
                        help="Save mechanically transformed XML to this path")
    parser.add_argument("--check", action="store_true",
                        help="Check that the source already matches the preset")
    args = parser.parse_args(argv)
    if args.check and args.output:
        parser.error("--check and --output are mutually exclusive")
    if not args.check and args.output is None:
        parser.error("Specify --output or --check")

    # read_bytes/decode preserves the source's CRLF and comments. Only the
    # named fields above change; ElementTree is used for checks, not export.
    source = args.source.read_bytes().decode("ascii")
    rendered = horizontal_preset(source)
    if args.check:
        if source != rendered:
            print("BuffWindow does not match the horizontal preset")
            return 1
        print("Horizontal buff source geometry matches")
        return 0
    args.output.write_bytes(rendered.encode("ascii"))
    print(f"Horizontal buff preset written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
