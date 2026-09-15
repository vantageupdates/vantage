"""Pure data and pixel-analysis helpers for the read-only Vitals Monitor."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import os
import re
import time

from PySide6.QtGui import QFont, QGuiApplication, QRawFont


MAX_VITAL_BARS = 32
MAX_VITAL_STOPS = 32
MIN_CONFIDENCE = 0.55
VITALS_DEFAULTS_VERSION = 1
BAR_TYPES = {"my_hp", "my_mana", "target_hp", "group_hp", "custom"}
STOP_DIRECTIONS = {"below", "above", "either", "full"}
DELIVERIES = {"sound", "tts", "off"}


def _number(value, default=0.0):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _integer(value, default, lower, upper):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = int(default)
    return max(lower, min(upper, value))


def _identifier(value, fallback):
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")[:64]
    return value or fallback


def normalize_rect(rect, window_size):
    """Convert a pixel ROI to a safe 0..1 rectangle inside a window."""
    width, height = max(1, int(window_size[0])), max(1, int(window_size[1]))
    x, y, roi_width, roi_height = (_number(value) for value in rect)
    x = max(0.0, min(float(width - 1), x))
    y = max(0.0, min(float(height - 1), y))
    roi_width = max(1.0, min(float(width) - x, roi_width))
    roi_height = max(1.0, min(float(height) - y, roi_height))
    return [
        round(x / width, 7), round(y / height, 7),
        round(roi_width / width, 7), round(roi_height / height, 7),
    ]


def sanitize_normalized_rect(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return []
    x, y, width, height = (_number(item, -1.0) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return []
    x, y = min(1.0, x), min(1.0, y)
    width = min(1.0 - x, width)
    height = min(1.0 - y, height)
    if width <= 0 or height <= 0:
        return []
    return [round(x, 7), round(y, 7), round(width, 7), round(height, 7)]


def denormalize_rect(rect, window_size):
    """Convert a normalized ROI to bounded integer image coordinates."""
    rect = sanitize_normalized_rect(rect)
    width, height = max(1, int(window_size[0])), max(1, int(window_size[1]))
    if not rect:
        return (0, 0, 0, 0)
    x = min(width - 1, max(0, round(rect[0] * width)))
    y = min(height - 1, max(0, round(rect[1] * height)))
    right = min(width, max(x + 1, round((rect[0] + rect[2]) * width)))
    bottom = min(height, max(y + 1, round((rect[1] + rect[3]) * height)))
    return (x, y, right - x, bottom - y)


def default_vital_stop(percent, direction="below", index=0):
    percent = _integer(percent, 25, 0, 100)
    direction = direction if direction in STOP_DIRECTIONS else "below"
    return {
        "id": f"stop-{percent}-{index}",
        "enabled": True,
        "percent": percent,
        "direction": direction,
        "hysteresis": 3,
        "cooldown": 30,
        "delivery": "sound",
        "sound": "builtin:soft-tick",
        "tts_text": "{name} {direction} {percent} percent",
        "voice": "",
        "volume": 80,
        "pitch": 0,
    }


def sanitize_vital_stop(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    percent = _integer(raw.get("percent", 25), 25, 0, 100)
    direction = str(raw.get("direction", "below") or "below").casefold()
    if direction not in STOP_DIRECTIONS:
        direction = "below"
    delivery = str(raw.get("delivery", "sound") or "sound").casefold()
    if delivery == "voice":
        delivery = "tts"
    if delivery not in DELIVERIES:
        delivery = "sound"
    fallback = default_vital_stop(percent, direction, index)
    return {
        "id": _identifier(raw.get("id"), fallback["id"]),
        "enabled": bool(raw.get("enabled", True)),
        "percent": percent,
        "direction": direction,
        "hysteresis": _integer(raw.get("hysteresis", 3), 3, 0, 15),
        "cooldown": _integer(raw.get("cooldown", 30), 30, 0, 3600),
        "delivery": delivery,
        "sound": str(raw.get("sound", fallback["sound"]) or "")[:512],
        "tts_text": str(raw.get("tts_text", fallback["tts_text"]) or "")[:300],
        "voice": str(raw.get("voice", "") or "")[:160],
        "volume": _integer(raw.get("volume", 80), 80, 0, 100),
        "pitch": _integer(raw.get("pitch", 0), 0, -10, 10),
    }


def default_vital_bars():
    return [
        default_vital_bar("my-hp", "My HP", "my_hp"),
        default_vital_bar("my-mana", "My Mana", "my_mana"),
        default_vital_bar(
            "target-hp", "Target / Mob HP", "target_hp"),
        default_vital_bar("group-hp", "Group HP", "group_hp"),
    ]


def default_vital_bar(bar_id="custom", name="Custom bar", bar_type="custom"):
    return {
        "id": _identifier(bar_id, "custom"),
        "name": str(name or "Custom bar")[:80],
        "type": bar_type if bar_type in BAR_TYPES else "custom",
        "enabled": True,
        "ocr_calibrated": False,
        "rect": [],
        "stops": [],
    }


def sanitize_vital_bar(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    bar_type = str(raw.get("type", "custom") or "custom").casefold()
    if bar_type not in BAR_TYPES:
        bar_type = "custom"
    name = " ".join(str(raw.get("name", "") or "").split())[:80]
    if not name:
        name = {"my_hp": "My HP", "my_mana": "My Mana",
                "target_hp": "Target / Mob HP",
                "group_hp": "Group HP"}.get(bar_type, f"Custom bar {index + 1}")
    # 1.44.92 numeric profiles used ``read_mode=number``. Newer profiles keep
    # a dedicated marker so their compact OCR rectangle survives subsequent
    # saves without retaining the removed mode selector. A legacy fill ROI is
    # intentionally cleared: running OCR over the long bar would be unsafe.
    migrated_numeric = str(raw.get("read_mode", "") or "").casefold() == "number"
    numeric_marker = raw.get("ocr_calibrated") is True or migrated_numeric
    rect = sanitize_normalized_rect(raw.get("rect", [])) if numeric_marker else []
    raw_stops = raw.get("stops", [])
    if not isinstance(raw_stops, list):
        raw_stops = []
    stops, stop_ids = [], set()
    for stop_index, raw_stop in enumerate(raw_stops[:MAX_VITAL_STOPS]):
        stop = sanitize_vital_stop(raw_stop, stop_index)
        base = stop["id"]
        suffix = 2
        while stop["id"] in stop_ids:
            stop["id"] = f"{base[:58]}-{suffix}"
            suffix += 1
        stop_ids.add(stop["id"])
        stops.append(stop)
    return {
        "id": _identifier(raw.get("id"), f"vital-{index + 1}"),
        "name": name,
        "type": bar_type,
        "enabled": bool(raw.get("enabled", True)),
        "ocr_calibrated": bool(rect),
        "rect": rect,
        "stops": stops,
    }


def sanitize_vital_bars(value):
    if not isinstance(value, list):
        return default_vital_bars()
    bars, ids = [], set()
    for index, raw in enumerate(value[:MAX_VITAL_BARS]):
        bar = sanitize_vital_bar(raw, index)
        base = bar["id"]
        suffix = 2
        while bar["id"] in ids:
            bar["id"] = f"{base[:58]}-{suffix}"
            suffix += 1
        ids.add(bar["id"])
        bars.append(bar)
    return bars if bars else default_vital_bars()


@dataclass(frozen=True)
class VitalReading:
    percent: float | None
    confidence: float
    valid: bool
    message: str
    source: str = ""
    # Absolute image-pixel bounds of the recognized token.  Runtime callers
    # can ignore this; calibration uses it to turn a loosely placed rectangle
    # into a small, stable saved ROI.
    token_rect: tuple[int, int, int, int] = ()


def _rgb(image, x, y):
    color = image.pixelColor(int(x), int(y))
    return color.red(), color.green(), color.blue()


def _distance(first, second):
    return math.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(first, second)))


_OCR_WIDTH = 24
_OCR_HEIGHT = 32
_OCR_GLYPHS = "0123456789%"
_BITMAP_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "%": ("11001", "11010", "00100", "00100", "01000", "10110", "00110"),
}


def _tight_mask(mask):
    if not mask or not mask[0]:
        return []
    rows = [row for row, values in enumerate(mask) if any(values)]
    columns = [
        column for column in range(len(mask[0]))
        if any(row[column] for row in mask)]
    if not rows or not columns:
        return []
    top, bottom = rows[0], rows[-1] + 1
    left, right = columns[0], columns[-1] + 1
    return [row[left:right] for row in mask[top:bottom]]


def _normalized_bits(mask):
    mask = _tight_mask(mask)
    if not mask:
        return (0.0, ())
    source_height, source_width = len(mask), len(mask[0])
    aspect = source_width / max(1.0, source_height)
    rows = []
    for target_y in range(_OCR_HEIGHT):
        source_y = min(
            source_height - 1,
            int((target_y + 0.5) * source_height / _OCR_HEIGHT))
        bits = 0
        for target_x in range(_OCR_WIDTH):
            source_x = min(
                source_width - 1,
                int((target_x + 0.5) * source_width / _OCR_WIDTH))
            if mask[source_y][source_x]:
                bits |= 1 << target_x
        rows.append(bits)
    return (aspect, tuple(rows))


def _render_glyph_mask(glyph, path, pixel_size):
    font = QRawFont(
        path, float(pixel_size), QFont.HintingPreference.PreferFullHinting)
    indexes = font.glyphIndexesForString(glyph) if font.isValid() else []
    if not indexes or not indexes[0]:
        return (0.0, ())
    image = font.alphaMapForGlyph(
        indexes[0], QRawFont.AntialiasingType.PixelAntialiasing)
    if image.isNull():
        return (0.0, ())
    mask = [
        [image.pixelColor(x, y).alpha() >= 72 for x in range(image.width())]
        for y in range(image.height())]
    return _normalized_bits(mask)


@lru_cache(maxsize=1)
def _ocr_templates():
    """Small in-process digit templates; no OCR executable or model needed."""
    templates = {glyph: [] for glyph in _OCR_GLYPHS}
    for glyph, rows in _BITMAP_GLYPHS.items():
        templates[glyph].append(_normalized_bits([
            [value == "1" for value in row] for row in rows]))
    if QGuiApplication.instance() is None:
        return templates
    windows = os.environ.get("WINDIR", r"C:\Windows")
    font_dir = os.path.join(windows, "Fonts")
    # These standard Windows faces cover native EQ/VantageUI labels. QRawFont
    # reads their glyph outlines directly, so this remains usable in packaged
    # and offscreen builds where Qt's global font database can be unavailable.
    paths = (
        "arial.ttf", "arialbd.ttf", "tahoma.ttf", "tahomabd.ttf",
        "segoeui.ttf", "segoeuib.ttf", "cour.ttf", "courbd.ttf")
    for filename in paths:
        path = os.path.join(font_dir, filename)
        if not os.path.isfile(path):
            continue
        for pixel_size in (10, 14, 20, 28):
            for glyph in _OCR_GLYPHS:
                template = _render_glyph_mask(glyph, path, pixel_size)
                if template[1] and template not in templates[glyph]:
                    templates[glyph].append(template)
    return templates


def _otsu_threshold(values):
    histogram = [0] * 256
    for value in values:
        histogram[max(0, min(255, int(value)))] += 1
    total = len(values)
    weighted_total = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_variance = -1.0
    threshold = 127
    for level, count in enumerate(histogram):
        background_weight += count
        if not background_weight:
            continue
        foreground_weight = total - background_weight
        if not foreground_weight:
            break
        background_sum += level * count
        background_mean = background_sum / background_weight
        foreground_mean = (
            weighted_total - background_sum) / foreground_weight
        variance = (background_weight * foreground_weight *
                    (background_mean - foreground_mean) ** 2)
        if variance > best_variance:
            best_variance = variance
            threshold = level
    return threshold


def _mask_bounds(mask):
    if not mask or not mask[0]:
        return ()
    rows = [row for row, values in enumerate(mask) if any(values)]
    columns = [
        column for column in range(len(mask[0]))
        if any(row[column] for row in mask)]
    if not rows or not columns:
        return ()
    return (columns[0], rows[0], columns[-1] - columns[0] + 1,
            rows[-1] - rows[0] + 1)


def _without_frame_lines(mask):
    """Remove long one-pixel frame rules without erasing digit strokes."""
    if not mask or not mask[0]:
        return []
    cleaned = [list(row) for row in mask]
    height, width = len(cleaned), len(cleaned[0])
    for row in range(height):
        if sum(cleaned[row]) >= max(8, round(width * .72)):
            cleaned[row] = [False] * width
    for column in range(width):
        if sum(cleaned[row][column] for row in range(height)) >= max(
                8, round(height * .78)):
            for row in range(height):
                cleaned[row][column] = False
    return cleaned


def _column_spans(mask):
    """Return occupied column runs tall enough to be a percentage glyph."""
    if not mask or not mask[0]:
        return []
    height = len(mask)
    occupied = [any(row[column] for row in mask)
                for column in range(len(mask[0]))]
    spans = []
    start = None
    for column, active in enumerate(occupied + [False]):
        if active and start is None:
            start = column
        elif not active and start is not None:
            submask = [row[start:column] for row in mask]
            bounds = _mask_bounds(submask)
            if bounds and bounds[3] >= max(4, round(height * .16)):
                spans.append((start, column))
            start = None
    return spans


def _candidate_masks(image, x, y, width, height):
    pixels = []
    quantized = {}
    for row in range(y, y + height):
        pixel_row = []
        for column in range(x, x + width):
            rgb = _rgb(image, column, row)
            luminance = round(rgb[0] * .299 + rgb[1] * .587 + rgb[2] * .114)
            pixel_row.append((rgb, luminance))
            key = tuple(component // 16 for component in rgb)
            quantized[key] = quantized.get(key, 0) + 1
        pixels.append(pixel_row)
    if not pixels:
        return []
    background_key = max(quantized, key=quantized.get)
    background = tuple(component * 16 + 8 for component in background_key)
    flat_luminance = [value for row in pixels for _rgb_value, value in row]
    otsu = _otsu_threshold(flat_luminance)
    raw_candidates = []
    for distance in (24, 38, 56):
        raw_candidates.append([
            [_distance(rgb, background) >= distance for rgb, _value in row]
            for row in pixels])
    raw_candidates.extend((
        [[value > otsu for _rgb_value, value in row] for row in pixels],
        [[value <= otsu for _rgb_value, value in row] for row in pixels],
    ))
    candidates = []
    seen = set()
    area = width * height
    for mask in raw_candidates:
        foreground = sum(sum(values) for values in mask)
        if foreground < max(3, round(area * .012)) or foreground > area * .62:
            continue
        cleaned = _without_frame_lines(mask)
        spans = _column_spans(cleaned)
        # Examine up to four neighboring glyph runs.  This finds a percentage
        # token within a padded rectangle while keeping polling work bounded.
        gaps = [spans[index + 1][0] - spans[index][1]
                for index in range(max(0, len(spans) - 1))]
        compact = (
            1 <= len(spans) <= 4 and
            all(gap <= max(5, round(height * .35)) for gap in gaps))
        sequences = ([(0, len(spans) - 1)] if compact else [
            (first, last)
            for first in range(len(spans))
            for last in range(first, min(len(spans), first + 4))])
        for first, last in sequences:
                left, right = spans[first][0], spans[last][1]
                sliced = [row[left:right] for row in cleaned]
                local = _mask_bounds(sliced)
                if not local:
                    continue
                local_x, top, local_width, local_height = local
                if local_height < 5 or local_width < 1:
                    continue
                candidate = [
                    row[local_x:local_x + local_width]
                    for row in sliced[top:top + local_height]]
                bounds = (x + left + local_x, y + top,
                          local_width, local_height)
                signature = (bounds, tuple(
                    sum((1 << column) for column, value in enumerate(row)
                        if value)
                    for row in candidate))
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append((candidate, bounds, last - first + 1))
    return candidates


def _glyph_runs(mask):
    """Split compact percentage text on empty columns."""
    mask = _tight_mask(mask)
    if not mask:
        return []
    occupied = [any(row[column] for row in mask)
                for column in range(len(mask[0]))]
    runs = []
    start = None
    for column, active in enumerate(occupied + [False]):
        if active and start is None:
            start = column
        elif not active and start is not None:
            glyph = _tight_mask([row[start:column] for row in mask])
            if glyph:
                runs.append(glyph)
            start = None
    # A border/noise speck should not become a digit. Keep a narrow "1" when
    # it spans most of the text height, and keep small percent dots only as
    # part of a percent-shaped final run.
    text_height = len(mask)
    return [run for run in runs
            if len(run) >= max(4, round(text_height * .48))]


def _glyph_similarity(observed, template):
    observed_aspect, observed_rows = observed
    template_aspect, template_rows = template
    if not observed_rows or not template_rows:
        return 0.0
    intersection = sum(
        (first & second).bit_count()
        for first, second in zip(observed_rows, template_rows))
    union = sum(
        (first | second).bit_count()
        for first, second in zip(observed_rows, template_rows))
    overlap = intersection / max(1, union)
    aspect_ratio = max(.01, observed_aspect) / max(.01, template_aspect)
    aspect_score = math.exp(-abs(math.log(aspect_ratio)) * 1.35)
    return overlap * .78 + aspect_score * .22


def _recognize_mask(mask):
    runs = _glyph_runs(mask)
    if not runs or len(runs) > 4:
        return (None, 0.0)
    templates = _ocr_templates()
    output = []
    scores = []
    margins = []
    for index, run in enumerate(runs):
        observed = _normalized_bits(run)
        choices = []
        allowed = _OCR_GLYPHS if index == len(runs) - 1 else _OCR_GLYPHS[:-1]
        for glyph in allowed:
            score = max(
                (_glyph_similarity(observed, template)
                 for template in templates[glyph]), default=0.0)
            choices.append((score, glyph))
        choices.sort(reverse=True)
        best_score, glyph = choices[0]
        margin = best_score - choices[1][0]
        output.append(glyph)
        scores.append(best_score)
        margins.append(margin)
    text = "".join(output)
    if text.endswith("%"):
        text = text[:-1]
        scores = scores[:-1]
        margins = margins[:-1]
    if not text or not text.isdigit() or len(text) > 3:
        return (None, 0.0)
    # Leading zeroes are not emitted by the EQ labels and usually indicate a
    # bad segmentation. The single value 0 remains a valid reading.
    if len(text) > 1 and text.startswith("0"):
        return (None, 0.0)
    value = int(text)
    if not 0 <= value <= 100 or not scores:
        return (None, 0.0)
    shape = sum(scores) / len(scores)
    separation = sum(max(0.0, value) for value in margins) / len(margins)
    confidence = min(1.0, shape * .84 + min(.16, separation * 1.8))
    if shape < .53 or min(scores) < .46 or confidence < MIN_CONFIDENCE:
        return (None, confidence)
    return (value, confidence)


def read_visible_percent(image, normalized_rect):
    """Find and read one visible 0..100 percentage label inside an ROI.

    This deliberately returns ``percent=None`` for unreadable pixels. A valid
    glyph for the number zero is distinguishable from an absent/invalid label.
    Padding and simple UI frame lines are tolerated.  Two plausible numbers
    are rejected as ambiguous rather than guessing which one is a vital.
    """
    rect = sanitize_normalized_rect(normalized_rect)
    if image is None or image.isNull() or not rect:
        return VitalReading(None, 0.0, False, "Visible number not calibrated", "number")
    x, y, width, height = denormalize_rect(
        rect, (image.width(), image.height()))
    if width < 3 or height < 5:
        return VitalReading(None, 0.0, False, "Number area is too small", "number")
    recognized = []
    best_confidence = 0.0
    for mask, bounds, glyph_count in _candidate_masks(
            image, x, y, width, height):
        value, confidence = _recognize_mask(mask)
        best_confidence = max(best_confidence, confidence)
        if value is not None:
            # Prefer a complete multi-glyph token over a contained single
            # digit.  Confidence remains the primary OCR quality measure.
            rank = confidence + min(3, max(0, glyph_count - 1)) * .025
            recognized.append((rank, confidence, value, bounds, glyph_count))
    if not recognized:
        return VitalReading(
            None, round(best_confidence, 3), False,
            "Visible percentage number is unreadable; alerts paused", "number")

    # Deduplicate threshold variants that found the same value and region.
    unique = {}
    for candidate in recognized:
        _rank, _confidence, value, bounds, _glyph_count = candidate
        key = (value, bounds)
        if key not in unique or candidate[0] > unique[key][0]:
            unique[key] = candidate
    recognized = list(unique.values())

    # A valid wider token supersedes readings of its individual digits.
    filtered = []
    for candidate in recognized:
        rank, confidence, _value, bounds, glyph_count = candidate
        left, top, width_value, height_value = bounds
        right, bottom = left + width_value, top + height_value
        contained = False
        for other in recognized:
            if other is candidate or other[4] <= glyph_count:
                continue
            o_left, o_top, o_width, o_height = other[3]
            if (o_left <= left and o_top <= top and
                    o_left + o_width >= right and
                    o_top + o_height >= bottom and
                    other[1] >= confidence - .10):
                contained = True
                break
        if not contained:
            filtered.append(candidate)
    recognized = sorted(filtered or recognized, reverse=True)
    best_rank, best_confidence, best_value, best_bounds, _count = recognized[0]
    alternatives = [
        candidate for candidate in recognized[1:]
        if candidate[2] != best_value and candidate[0] >= best_rank - .065]
    if alternatives:
        return VitalReading(
            None, round(best_confidence, 3), False,
            "Multiple percentage numbers detected; use a smaller area",
            "number")
    return VitalReading(
        float(best_value), round(best_confidence, 3), True,
        "Visible number reading", "number", tuple(best_bounds))


def read_vital_bar(image, bar):
    """Read one sanitized vital exclusively from its visible-number ROI."""
    bar = sanitize_vital_bar(bar, 0)
    return read_visible_percent(image, bar["rect"])


def preset_percentages(name):
    name = str(name or "").casefold().strip()
    if name in {"every 10%", "every10", "10"}:
        return list(range(10, 101, 10))
    if name in {"25/50/75/100", "quarters", "quarter"}:
        return [25, 50, 75, 100]
    return []


class VitalStopTracker:
    """Non-persistent crossing state with hysteresis and per-stop cooldown."""

    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._states = {}

    def reset_bar(self, bar_id):
        prefix = f"{bar_id}:"
        self._states = {
            key: value for key, value in self._states.items()
            if not key.startswith(prefix)}

    def update(self, bar_id, percent, stops, confidence=1.0, now=None):
        if percent is None or _number(confidence) < MIN_CONFIDENCE:
            return []
        now = self._clock() if now is None else float(now)
        current = max(0.0, min(100.0, float(percent)))
        events = []
        for index, raw_stop in enumerate((stops or [])[:MAX_VITAL_STOPS]):
            stop = sanitize_vital_stop(raw_stop, index)
            if not stop["enabled"] or stop["delivery"] == "off":
                continue
            key = f"{bar_id}:{stop['id']}"
            state = self._states.get(key)
            threshold = float(stop["percent"])
            hysteresis = float(stop["hysteresis"])
            if state is None:
                self._states[key] = {
                    "below": current >= threshold + hysteresis,
                    "above": current <= threshold - hysteresis,
                    "full": current <= 100.0 - hysteresis,
                    "last": -float("inf"),
                }
                continue
            directions = []
            mode = stop["direction"]
            if mode in {"below", "either"}:
                if state["below"] and current <= threshold:
                    directions.append("below")
                    state["below"] = False
                elif current >= threshold + hysteresis:
                    state["below"] = True
            if mode in {"above", "either"}:
                if state["above"] and current >= threshold:
                    directions.append("above")
                    state["above"] = False
                elif current <= threshold - hysteresis:
                    state["above"] = True
            if mode == "full":
                if state["full"] and current >= 100.0:
                    directions.append("full")
                    state["full"] = False
                elif current <= 100.0 - hysteresis:
                    state["full"] = True
            for crossed in directions:
                if now - state["last"] < stop["cooldown"]:
                    continue
                state["last"] = now
                events.append((stop, crossed))
        return events
