"""Lay out the existing Titanium buff controls as fixed V/H presets.

This changes geometry and native window chrome only. It does not create buff
controls, change native IDs, replace spell art, or touch a character's UI INI.
Both presets retain visible native spell-name labels and all native bindings.
The compact horizontal pane fits the 15 P99 slots in three columns and five
rows; the remaining native definitions stay below the pane, as vertically.
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
GRID_COLUMNS = 3
CELL_WIDTH = 176
ROW_HEIGHT = 28
ICON_X = 152
ICON_Y = 4
WINDOW_WIDTH = 544
WINDOW_HEIGHT = 168
GEOMETRY_ANCHORS = (
    "AutoStretch", "TopAnchorToTop", "LeftAnchorToLeft", "BottomAnchorToTop",
    "RightAnchorToLeft", "TopAnchorOffset", "BottomAnchorOffset",
    "LeftAnchorOffset", "RightAnchorOffset",
)


def _change_child(block: str, parent: str, child: str, value: str) -> str:
    """Replace exactly one existing field, preserving XML formatting."""
    pattern = rf"(<{parent}>.*?</{parent}>)"

    def replace(match: re.Match[str]) -> str:
        return _change_field(match[1], child, value)

    block, count = re.subn(pattern, replace, block, flags=re.DOTALL)
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


def _button_anchors(source: str, name: str, x: int | None = None,
                    y: int | None = None) -> str:
    """Set only inherited SIDL geometry fields; None restores old V bytes.

    The native buff code can move buttons after reading Location. Explicit
    top/left anchors are a separate native layout input and keep the intended
    icon rectangle associated with its existing spell-name label. This is a
    source-level mitigation, not evidence of native renderer behavior.
    """
    pattern = rf'(<Button item="{re.escape(name)}">.*?</Button>)'

    def replace(match: re.Match[str]) -> str:
        block = match[1]
        newline = "\r\n" if "\r\n" in block else "\n"
        for field in GEOMETRY_ANCHORS:
            field_pattern = rf"(?:\r?\n)?[ \t]*<{field}>[^<]*</{field}>"
            block, count = re.subn(field_pattern, "", block)
            if count > 1:
                raise ValueError(f"Expected at most one {field}, found {count}")
        if x is None and y is None:
            return block
        if x is None or y is None:
            raise ValueError("Both native anchor coordinates are required")
        values = ("true", "true", "true", "true", "true", str(y),
                  str(y + ICON_SIZE), str(x), str(x + ICON_SIZE))
        size_pattern = r"([ \t]*)</Size>"
        size_matches = list(re.finditer(size_pattern, block))
        if len(size_matches) != 1:
            raise ValueError(f"Expected one button Size, found {len(size_matches)}")
        indent = size_matches[0][1]
        anchor_xml = "".join(f"{newline}{indent}<{field}>{value}</{field}>"
                             for field, value in zip(GEOMETRY_ANCHORS, values))
        return re.sub(size_pattern, lambda size: size[0] + anchor_xml, block)

    result, count = re.subn(pattern, replace, source, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"Expected one Button {name}, found {count}")
    return result


def _validate_controls(source: str) -> ET.Element:
    before = ET.fromstring(source)
    buttons = before.findall("Button")
    if [node.findtext("ScreenID") for node in buttons] != [
            f"Buff{i}" for i in range(BUFF_COUNT)]:
        raise ValueError("Expected exactly the original Buff0 through Buff24 controls")
    return before


def horizontal_preset(source: str) -> str:
    """Three horizontal cells per row, with the original readable name width."""
    before = _validate_controls(source)

    result = source
    for index in range(BUFF_COUNT):
        column, row = index % GRID_COLUMNS, index // GRID_COLUMNS
        # Client coordinates exclude the 16px title and native frame. Names
        # stay left of icons, as vertically; preserve Font/NoWrap/alignment.
        x, y = ICON_X + CELL_WIDTH * column, ICON_Y + ROW_HEIGHT * row
        result = _change_item(result, "Button", f"BW_Buff{index}_Button", {
            "Location/X": str(x), "Location/Y": str(y)})
        result = _button_anchors(result, f"BW_Buff{index}_Button", x, y)
        result = _change_item(result, "Label", f"BW_Buff{index}_Label",
                              _rect(6 + CELL_WIDTH * column, 10 + ROW_HEIGHT * row, 142, 12))
        if index < 15:
            result = _change_item(result, "Label", f"BW_Buff{index}_LabelBG",
                                  _rect(7 + CELL_WIDTH * column, 11 + ROW_HEIGHT * row, 142, 12))
        # Keep the native empty-slot numbers/Pieces but don't float them in
        # the horizontal name lane without the vertical holder artwork.
        result = _change_item(result, "Label", f"BW_Number{index}Label", _rect(4, 20, 0, 0))
    for node in before.findall("StaticAnimation"):
        result = _change_item(result, "StaticAnimation", node.attrib["item"], _rect(4, 20, 0, 0))

    result = _change_item(result, "Screen", "BuffWindow", {
        **_rect(415, 395, WINDOW_WIDTH, WINDOW_HEIGHT),
        "Style_Transparent": "false",
        "DrawTemplate": "WDT_Rounded",
        "Style_Titlebar": "true",
        "Style_Border": "true",
        "Text": "Effects (H)",
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


def vertical_preset(source: str) -> str:
    """Restore the unchanged UI102 column; only the orientation title is new."""
    _validate_controls(source)
    result = source
    for index in range(BUFF_COUNT):
        result = _button_anchors(result, f"BW_Buff{index}_Button")
        result = _change_item(result, "Button", f"BW_Buff{index}_Button", {
            "Location/X": "175", "Location/Y": str(1 + 25 * index)})
        result = _change_item(result, "Label", f"BW_Number{index}Label",
                              _rect(175, 7 + 25 * index, 24, 12))
        result = _change_item(result, "Label", f"BW_Buff{index}_Label",
                              _rect(30, 6 + 25 * index, 142, 12))
        if index < 15:
            result = _change_item(result, "Label", f"BW_Buff{index}_LabelBG",
                                  _rect(31, 7 + 25 * index, 142, 12))
    for index in range(3):
        result = _change_item(result, "StaticAnimation", f"BW_BuffBackground{index}",
                              _rect(175, 1 + 125 * index, 24, 124))
    return _change_item(result, "Screen", "BuffWindow", {
        **_rect(415, 395, 200, 375), "Style_Transparent": "true",
        "DrawTemplate": "WDT_RoundedNoTitle", "Style_Titlebar": "false",
        "Style_Border": "false", "Text": "Effects (V)"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--layout", choices=("vertical", "horizontal"), default="horizontal")
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
    rendered = (vertical_preset if args.layout == "vertical" else horizontal_preset)(source)
    if args.check:
        if source != rendered:
            print(f"BuffWindow does not match the {args.layout} preset")
            return 1
        print(f"{args.layout.title()} buff source geometry matches")
        return 0
    args.output.write_bytes(rendered.encode("ascii"))
    print(f"{args.layout.title()} buff preset written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
