"""Pure data and pixel-analysis helpers for the read-only Vitals Monitor."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time


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


def sanitize_color(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return []
    return [_integer(component, 0, 0, 255) for component in value]


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
        "rect": [],
        "color": [],
        "direction": "ltr",
        "tolerance": 64,
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
    direction = str(raw.get("direction", "ltr") or "ltr").casefold()
    if direction not in {"ltr", "rtl"}:
        direction = "ltr"
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
        "rect": sanitize_normalized_rect(raw.get("rect", [])),
        "color": sanitize_color(raw.get("color", [])),
        "direction": direction,
        "tolerance": _integer(raw.get("tolerance", 64), 64, 10, 180),
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


def _rgb(image, x, y):
    color = image.pixelColor(int(x), int(y))
    return color.red(), color.green(), color.blue()


def _distance(first, second):
    return math.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(first, second)))


def learn_fill_color(image, normalized_rect, direction="ltr"):
    """Learn the dominant bright/colorful fill sample near the fill origin."""
    if image is None or image.isNull():
        return ([], 0.0)
    x, y, width, height = denormalize_rect(
        normalized_rect, (image.width(), image.height()))
    if width < 3 or height < 2:
        return ([], 0.0)
    sample_width = max(2, round(width * 0.35))
    start = x if direction != "rtl" else x + width - sample_width
    bins = {}
    samples = 0
    for column in range(start, start + sample_width):
        for row in range(y, y + height):
            rgb = _rgb(image, column, row)
            brightness = max(rgb)
            saturation = max(rgb) - min(rgb)
            if brightness < 45 or saturation < 18:
                continue
            key = tuple(min(255, (component // 16) * 16 + 8) for component in rgb)
            bins[key] = bins.get(key, 0) + 1
            samples += 1
    if not bins or samples < max(2, height // 2):
        return ([], 0.0)
    color, count = max(bins.items(), key=lambda item: item[1])
    return (list(color), min(1.0, count / max(1, height * sample_width * 0.35)))


def analyze_vital_bar(
        image, normalized_rect, fill_color, direction="ltr", tolerance=64):
    """Estimate bar fill by per-column color occupancy with confidence.

    The function never extrapolates from an absent target color. Callers must
    treat ``valid=False`` as no reading, not as zero percent.
    """
    rect = sanitize_normalized_rect(normalized_rect)
    color = sanitize_color(fill_color)
    if image is None or image.isNull() or not rect or not color:
        return VitalReading(None, 0.0, False, "Not calibrated")
    x, y, width, height = denormalize_rect(
        rect, (image.width(), image.height()))
    if width < 3 or height < 2:
        return VitalReading(None, 0.0, False, "Calibration area is too small")
    tolerance = _integer(tolerance, 64, 10, 180)
    match_grid = []
    row_totals = [0] * height
    for column in range(x, x + width):
        column_matches = []
        for row_offset, row in enumerate(range(y, y + height)):
            matched = _distance(
                _rgb(image, column, row), color) <= tolerance
            column_matches.append(matched)
            row_totals[row_offset] += int(matched)
        match_grid.append(column_matches)

    # A generously drawn calibration rectangle often contains the native EQ
    # frame above/below a thin fill stripe. Ignore full-width target-colored
    # edge rows (frame pixels), then normalize each column against the strongest
    # remaining vertical band instead of demanding 35% of the whole ROI.
    edge_depth = max(1, min(height // 3, round(height * 0.2)))
    ignored_rows = {
        row for row, count in enumerate(row_totals)
        if count >= math.ceil(width * 0.9) and
        (row < edge_depth or row >= height - edge_depth)}
    counts, runs = [], []
    for column_matches in match_grid:
        count = 0
        longest = 0
        current_run = 0
        for row, matched in enumerate(column_matches):
            if row in ignored_rows:
                matched = False
            if matched:
                count += 1
                current_run += 1
                longest = max(longest, current_run)
            else:
                current_run = 0
        counts.append(count)
        runs.append(longest)
    peak_count = max(counts, default=0)
    peak_run = max(runs, default=0)
    minimum_band = 3 if height >= 10 else 2
    if peak_count < minimum_band or peak_run < minimum_band:
        return VitalReading(None, 0.0, False, "Fill color is not visible")
    count_floor = max(minimum_band, math.ceil(peak_count * 0.55))
    run_floor = max(minimum_band, math.ceil(peak_run * 0.55))
    scores = [
        min(1.0, 0.45 * count / peak_count + 0.55 * run / peak_run)
        for count, run in zip(counts, runs)]
    active = [
        count >= count_floor and run >= run_floor
        for count, run in zip(counts, runs)]
    if not any(active):
        return VitalReading(None, 0.0, False, "Fill color is not visible")
    ordered = active if direction != "rtl" else list(reversed(active))
    # Small gaps from text/highlights are tolerated, while a detached cluster
    # cannot make an empty bar look full.
    gap_budget = max(1, min(4, round(width * 0.025)))
    filled, gaps = 0, 0
    for is_active in ordered:
        if is_active:
            filled += 1
            gaps = 0
        else:
            gaps += 1
            if gaps <= gap_budget:
                filled += 1
            else:
                filled -= gap_budget
                break
    filled = max(0, min(width, filled))
    percent = 100.0 * filled / width
    predicted = ([index < filled for index in range(width)]
                 if direction != "rtl" else
                 [index >= width - filled for index in range(width)])
    agreement = sum(
        expected == observed for expected, observed in zip(predicted, active)) / width
    clarity = sum(
        score if observed else 1.0 - score
        for score, observed in zip(scores, active)) / width
    band_support = min(1.0, peak_run / max(
        float(minimum_band), min(6.0, height * 0.35)))
    confidence = max(0.0, min(
        1.0, agreement * 0.68 + clarity * 0.20 + band_support * 0.12))
    valid = confidence >= MIN_CONFIDENCE
    return VitalReading(
        round(percent, 1) if valid else None, round(confidence, 3), valid,
        "Reading" if valid else "Low-confidence visual reading")


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
