from PySide6.QtCore import QSize

from vantage.helpers.parser import (
    WMSZ_BOTTOM, WMSZ_BOTTOMLEFT, WMSZ_BOTTOMRIGHT, WMSZ_LEFT,
    WMSZ_RIGHT, WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT,
    independent_sizing_rect)


DESIGN = QSize(520, 360)


def constrained(edge, rect, start_scale=1.0):
    return independent_sizing_rect(edge, rect, DESIGN, .25)


def size(rect):
    return rect[2] - rect[0], rect[3] - rect[1]


def test_dragging_bottom_changes_height_only():
    result = constrained(WMSZ_BOTTOM, (100, 100, 620, 280))
    assert result == (100, 100, 620, 280)
    assert size(result) == (520, 180)


def test_dragging_right_changes_width_only():
    result = constrained(WMSZ_RIGHT, (100, 100, 360, 460))
    assert result == (100, 100, 360, 460)
    assert size(result) == (260, 360)


def test_corners_keep_their_opposite_corner_anchored():
    cases = {
        WMSZ_TOPLEFT: ((360, 280, 620, 460), (360, 280, 620, 460)),
        WMSZ_TOPRIGHT: ((100, 280, 360, 460), (100, 280, 360, 460)),
        WMSZ_BOTTOMLEFT: ((360, 100, 620, 280), (360, 100, 620, 280)),
        WMSZ_BOTTOMRIGHT: ((100, 100, 360, 280), (100, 100, 360, 280)),
    }
    for edge, (proposed, expected) in cases.items():
        assert constrained(edge, proposed) == expected


def test_corner_accepts_independent_width_and_height():
    result = constrained(WMSZ_BOTTOMRIGHT, (100, 100, 600, 280))
    assert size(result) == (500, 180)


def test_minimum_size_clamps_only_the_axis_that_is_too_small():
    assert constrained(WMSZ_BOTTOM, (100, 100, 620, 110)) == (
        100, 100, 620, 190)
    assert constrained(WMSZ_RIGHT, (100, 100, 110, 460)) == (
        100, 100, 230, 460)


def test_minimum_size_respects_left_and_top_anchors():
    assert constrained(WMSZ_LEFT, (610, 100, 620, 460)) == (
        490, 100, 620, 460)
    assert constrained(WMSZ_TOP, (100, 450, 620, 460)) == (
        100, 370, 620, 460)
