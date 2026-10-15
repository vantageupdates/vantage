"""Single-flight, read-only Vitals sampling without a GUI-thread capture.

The worker owns only Python state and QImages. It never retains a widget,
delivers audio, or calls a UI callback. A GUI-owned timer drains its one-result
mailbox. A stuck native capture cannot create more jobs or hold up app exit.
"""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time

from vantage.helpers.vitals import MAX_VITAL_BARS, VitalReading, read_vital_bar


MAX_SAMPLE_AGE_SECONDS = 5.0


def eligible_vital_bar(bar):
    return bool(bar.get("enabled") and bar.get("ocr_calibrated")
                and bar.get("rect"))


def inactive_vital_reading(bar):
    message = ("Monitoring is off" if not bar.get("enabled") else
               "Calibrate a visible vital number")
    return VitalReading(None, 0.0, False, message)


@dataclass(frozen=True)
class VitalSample:
    status: dict
    image: object
    window_rect: tuple
    readings: dict
    captured_at: float


def collect_vital_sample(capture, bars, cancelled=None):
    """Read all eligible monitors from one QImage, never from separate frames."""
    bars = bars[:MAX_VITAL_BARS]
    eligible = [bar for bar in bars if eligible_vital_bar(bar)]
    readings = {bar["id"]: inactive_vital_reading(bar)
                for bar in bars if not eligible_vital_bar(bar)}
    if not eligible or (cancelled is not None and cancelled.is_set()):
        return VitalSample({}, None, (), readings, 0.0)
    status, image, window_rect = capture.image_frame(
        require_enabled=False, require_foreground=True)
    captured_at = time.monotonic()
    if not status.get("available"):
        message = str(status.get("message") or "No visual reading")
        readings.update({bar["id"]: VitalReading(None, 0.0, False, message)
                         for bar in eligible})
        return VitalSample(status, None, (), readings, captured_at)
    # OCR is intentionally bounded to the already-sanitized monitor list. Its
    # QRawFont instances and QImages are created/used only on this thread; only
    # immutable digit-template data is shared with explicit calibration.
    for bar in eligible:
        if cancelled is not None and cancelled.is_set():
            return None
        readings[bar["id"]] = read_vital_bar(image, bar)
    return VitalSample(status, image, tuple(window_rect), readings, captured_at)


class VitalPollWorker:
    """At most one running capture and one pending completion; no backlog."""

    def __init__(self):
        self._cancelled = threading.Event()
        self._results = queue.Queue(maxsize=1)
        self._thread = None
        self.started_at = 0.0

    @property
    def busy(self):
        # Keep the slot occupied until the GUI consumes its result, even if
        # the worker has already finished. Repeated timer ticks cannot queue.
        return self._thread is not None

    def start(self, generation, capture, bars):
        if self.busy or self._cancelled.is_set():
            return False
        started = time.monotonic()
        self.started_at = started

        def run():
            try:
                sample = collect_vital_sample(capture, bars, self._cancelled)
            except Exception:
                # A capture/OCR failure must release the single-flight slot and
                # allow the next normal polling tick to retry safely.
                message = "Visual reading failed; retrying"
                readings = {bar["id"]: (
                    VitalReading(None, 0.0, False, message)
                    if eligible_vital_bar(bar) else inactive_vital_reading(bar))
                    for bar in bars}
                sample = VitalSample(
                    {"available": False, "message": message}, None, (),
                    readings, 0.0)
            if not self._cancelled.is_set():
                self._results.put_nowait(
                    (generation, capture, bars, started, sample))

        self._thread = threading.Thread(
            target=run, name="Vantage-Vitals-Sampler", daemon=True)
        self._thread.start()
        return True

    def take_result(self):
        if self._thread is None or self._thread.is_alive():
            return None
        self._thread = None
        try:
            return self._results.get_nowait()
        except queue.Empty:
            return None

    def close(self, *_args):
        # Do not join a potentially blocked Windows PrintWindow call on the UI
        # thread. The daemon has no QObject/widget receiver to outlive, and it
        # drops its result and stops between readings once shutdown is set.
        self._cancelled.set()
