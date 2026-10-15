"""Vitals sampling must not block Qt or wake an unused capture pipeline."""

from copy import deepcopy
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from vantage.helpers.vitals import (
    VitalReading, VitalStopTracker, default_vital_bar, default_vital_stop)
from vantage.helpers.vitals_polling import VitalPollWorker
import vantage.helpers.vitals_polling as sampling
from vantage.parsers.vitals import VitalCard, Vitals
import vantage.parsers.vitals as vitals_module


def _bar():
    bar = default_vital_bar("hp", "My HP", "my_hp")
    bar.update(ocr_calibrated=True, rect=[0, 0, 1, 1])
    bar["stops"] = [default_vital_stop(50, "below")]
    return bar


def _wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
        # Some platform plugins hold the GIL while their nested event wait
        # runs. Give the Python OCR worker an explicit scheduling opportunity.
        time.sleep(.001)
    assert predicate(), "background sample did not finish before the deadline"


class FakeCapture:
    def __init__(self, gate=None, fail=False):
        self.gate = gate
        self.fail = fail
        self.started = threading.Event()
        self.calls = 0
        self.threads = []

    def image_frame(self, **kwargs):
        assert kwargs == {"require_enabled": False, "require_foreground": True}
        self.calls += 1
        self.threads.append(threading.get_ident())
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(3), "test did not release its fake capture"
        if self.fail:
            self.fail = False
            raise OSError("synthetic failed capture")
        image = QImage(80, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("#102027"))
        return {"available": True}, image, (0, 0, 80, 20)


class PollingPanel(QWidget):
    """Exercise the real polling methods without loading the whole app."""

    poll_now = Vitals.poll_now
    _drain_poll_result = Vitals._drain_poll_result
    _invalidate_poll_readings = Vitals._invalidate_poll_readings
    _set_reading = Vitals._set_reading
    _apply_poll_sample = Vitals._apply_poll_sample
    _shutdown_polling = Vitals._shutdown_polling
    _bar_index = Vitals._bar_index

    def __init__(self, capture, bars):
        super().__init__()
        self._capture = capture
        self._bars = deepcopy(bars)
        self._cards = {}
        self._readings = {}
        self._tracker = VitalStopTracker()
        self._calibration_context = None
        self._poll_generation = 0
        self._poll_shutdown = False
        self._poll_worker = VitalPollWorker()
        self._poll_timer = QTimer(self)
        self._poll_result_timer = QTimer(self)
        self._poll_result_timer.setInterval(10)
        self._poll_result_timer.timeout.connect(self._drain_poll_result)
        self.statuses = []
        self.deliveries = []
        self._set_status = self.statuses.append
        self._deliver_stop = lambda *args: self.deliveries.append(
            (threading.get_ident(), args))
        self.destroyed.connect(self._poll_worker.close)


@pytest.fixture
def panels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    windows = []
    monkeypatch.setattr(sampling, "read_vital_bar", lambda *_: VitalReading(
        40, 1.0, True, "Synthetic percentage"))

    def make(capture=None, bars=None):
        panel = PollingPanel(capture or FakeCapture(), [_bar()] if bars is None else bars)
        windows.append(panel)
        return panel

    yield make
    for panel in windows:
        panel._shutdown_polling()
        if panel._capture.gate is not None:
            panel._capture.gate.set()
        panel.close()
        panel.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("state", ["empty", "disabled", "uncalibrated", "missing_rect"])
def test_inactive_vitals_never_capture_or_run_ocr(panels, monkeypatch, state):
    bars = [_bar()]
    if state == "empty":
        bars = []
    elif state == "disabled":
        bars[0]["enabled"] = False
    elif state == "uncalibrated":
        bars[0]["ocr_calibrated"] = False
    else:
        bars[0]["rect"] = []
    panel = panels(bars=bars)
    monkeypatch.setattr(sampling, "read_vital_bar", lambda *_: pytest.fail("unused OCR"))
    for _ in range(20):
        panel.poll_now()
    QTest.qWait(30)
    assert panel._capture.calls == 0
    assert not panel._poll_worker.busy
    assert not panel._poll_result_timer.isActive()
    assert panel.statuses[-1].startswith("NO READING")


def test_hidden_active_monitor_still_alerts_with_gui_thread_delivery(panels, monkeypatch):
    panel = panels()
    main_thread = threading.get_ident()
    read_threads = []
    card_threads = []

    def read(_image, _bar):
        read_threads.append(threading.get_ident())
        return VitalReading(40, 1.0, True, "Synthetic percentage")

    monkeypatch.setattr(sampling, "read_vital_bar", read)
    panel._cards["hp"] = type("Card", (), {
        "set_reading": lambda _self, reading: card_threads.append(threading.get_ident())})()
    panel._tracker.update("hp", 70, panel._bars[0]["stops"])
    assert not panel.isVisible()
    panel.poll_now()
    _wait_until(lambda: bool(panel.deliveries))
    assert panel._capture.calls == 1
    assert panel._capture.threads == read_threads
    assert all(thread != main_thread for thread in read_threads)
    assert card_threads == [main_thread]
    assert panel.deliveries[0][0] == main_thread
    assert panel._readings["hp"].percent == 40
    assert panel.statuses[-1] == "ACTIVE · 1 live reading"


def test_slow_capture_keeps_qt_responsive_and_never_queues_jobs(panels):
    gate = threading.Event()
    capture = FakeCapture(gate)
    panel = panels(capture)
    ticks = []
    heartbeat = QTimer(panel)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start()
    started = time.monotonic()
    panel.poll_now()
    assert time.monotonic() - started < .1
    _wait_until(capture.started.is_set)
    for _ in range(20):
        panel.poll_now()
        QTest.qWait(5)
    assert len(ticks) >= 5
    assert capture.calls == 1
    assert not panel._readings
    gate.set()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert capture.calls == 1  # Missed polling ticks are not replayed.
    assert panel._readings["hp"].valid
    assert not panel._poll_result_timer.isActive()


def test_slow_ocr_keeps_qt_responsive_without_resampling(panels, monkeypatch):
    entered = threading.Event()
    gate = threading.Event()
    panel = panels()

    def read(_image, _bar):
        entered.set()
        assert gate.wait(3)
        return VitalReading(40, 1, True, "Synthetic percentage")

    monkeypatch.setattr(sampling, "read_vital_bar", read)
    ticks = []
    timer = QTimer(panel)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        panel.poll_now()
        _wait_until(entered.is_set)
        for _ in range(20):
            panel.poll_now()
            QTest.qWait(5)
        assert len(ticks) >= 5
        assert panel._capture.calls == 1
    finally:
        gate.set()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert panel._readings["hp"].valid


def test_mixed_monitors_only_ocr_eligible_and_unchanged_cards_are_not_rebuilt(
        panels, monkeypatch):
    bars = [_bar(), _bar(), _bar()]
    bars[1].update(id="disabled", enabled=False)
    bars[2].update(id="uncalibrated", ocr_calibrated=False)
    panel = panels(bars=bars)
    reads = []
    paints = []

    def read(_image, bar):
        reads.append(bar["id"])
        return VitalReading(40, 1, True, "Synthetic percentage")

    monkeypatch.setattr(sampling, "read_vital_bar", read)
    panel._cards["hp"] = type("Card", (), {
        "set_reading": lambda _self, reading: paints.append(reading)})()
    for _ in range(2):
        panel.poll_now()
        _wait_until(lambda: not panel._poll_worker.busy)
    assert reads == ["hp", "hp"]
    assert len(paints) == 1
    assert panel._readings["disabled"].message == "Monitoring is off"
    assert "Calibrate" in panel._readings["uncalibrated"].message


@pytest.mark.parametrize("change", [
    "edit", "disable", "remove", "calibration", "generation", "capture"])
def test_stale_snapshot_never_changes_cards_or_delivers_alerts(panels, change):
    gate = threading.Event()
    original_capture = FakeCapture(gate)
    panel = panels(original_capture)
    panel._tracker.update("hp", 70, panel._bars[0]["stops"])
    panel.poll_now()
    _wait_until(original_capture.started.is_set)
    if change == "edit":
        panel._bars[0]["rect"] = [0, 0, .5, .5]
    elif change == "disable":
        panel._bars[0]["enabled"] = False
    elif change == "remove":
        panel._bars.clear()
    elif change == "calibration":
        panel._calibration_context = ("hp", None, None)
    elif change == "generation":
        # Starting then cancelling calibration restores the original config;
        # the generation still invalidates a pre-calibration frame.
        panel._poll_generation += 1
    else:
        panel._capture = FakeCapture()
    gate.set()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert not panel._readings
    assert not panel.deliveries
    assert not panel.statuses


def test_expired_sample_is_not_presented_as_live(panels, monkeypatch):
    monkeypatch.setattr(vitals_module, "MAX_SAMPLE_AGE_SECONDS", 0)
    panel = panels()
    panel.poll_now()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert panel._readings["hp"].valid is False
    assert panel._readings["hp"].percent is None
    assert not panel.deliveries
    assert panel.statuses[-1] == "NO READING · delayed capture; retrying"


def test_stuck_native_capture_pauses_live_status_without_starting_another(
        panels, monkeypatch):
    gate = threading.Event()
    panel = panels(FakeCapture(gate))
    monkeypatch.setattr(vitals_module, "MAX_SAMPLE_AGE_SECONDS", 0)
    try:
        panel.poll_now()
        _wait_until(panel._capture.started.is_set)
        panel.poll_now()
        assert panel.statuses[-1] == "NO READING · waiting for delayed capture"
        assert panel._poll_result_timer.interval() == 250
        assert panel._capture.calls == 1
    finally:
        gate.set()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert panel._readings["hp"].valid is False
    assert panel._readings["hp"].percent is None
    assert panel.statuses[-1] == "NO READING · delayed capture; retrying"


@pytest.mark.parametrize("branch", ["timeout", "expired"])
def test_delayed_capture_invalidates_previously_live_cards_without_alerts(
        panels, monkeypatch, branch):
    gate = threading.Event()
    bars = [_bar(), _bar(), _bar()]
    bars[1].update(id="disabled", enabled=False)
    bars[2].update(id="uncalibrated", ocr_calibrated=False, rect=[])
    panel = panels(FakeCapture(gate), bars)
    for bar in panel._bars:
        panel._cards[bar["id"]] = VitalCard(bar, panel)
    panel._set_reading("hp", VitalReading(70, 1, True, "Previous live frame"))
    panel._tracker.update("hp", 70, panel._bars[0]["stops"])
    prior_threshold_state = deepcopy(panel._tracker._states)
    card = panel._cards["hp"]
    assert card.state_label.text() == "LIVE"
    assert card.value_label.text() == "70%"
    try:
        panel.poll_now()
        _wait_until(panel._capture.started.is_set)
        panel._poll_result_timer.stop()
        monkeypatch.setattr(vitals_module, "MAX_SAMPLE_AGE_SECONDS", 0)
        if branch == "expired":
            gate.set()
            _wait_until(lambda: not panel._poll_worker._thread.is_alive())
        panel._drain_poll_result()
        reading = panel._readings["hp"]
        assert reading.valid is False and reading.percent is None
        assert card.state_label.text() == "NO READING"
        assert card.value_label.text() == "—%"
        assert "delayed capture" in card.detail.text().casefold()
        assert panel._readings["disabled"].message == "Monitoring is off"
        assert panel._cards["disabled"].state_label.text() == "PAUSED"
        assert panel._readings["uncalibrated"].message == "Calibrate a visible vital number"
        assert panel._cards["uncalibrated"].state_label.text() == "SETUP"
        assert panel._tracker._states == prior_threshold_state
        assert not panel.deliveries
    finally:
        gate.set()


def test_capture_failure_releases_slot_and_next_poll_recovers(panels):
    panel = panels(FakeCapture(fail=True))
    panel.poll_now()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert panel._readings["hp"].valid is False
    assert "retrying" in panel.statuses[-1]
    panel.poll_now()
    _wait_until(lambda: not panel._poll_worker.busy)
    assert panel._capture.calls == 2
    assert panel._readings["hp"].valid


def test_shutdown_does_not_wait_for_native_capture_or_deliver_late_result(panels):
    gate = threading.Event()
    panel = panels(FakeCapture(gate))
    panel.poll_now()
    _wait_until(panel._capture.started.is_set)
    started = time.monotonic()
    panel._shutdown_polling()
    assert time.monotonic() - started < .1
    assert not panel._poll_timer.isActive()
    assert not panel._poll_result_timer.isActive()
    panel.poll_now()
    assert panel._capture.calls == 1
    gate.set()
    _wait_until(lambda: not panel._poll_worker._thread.is_alive())
    panel._drain_poll_result()
    assert not panel._readings
    assert not panel.deliveries


def test_unconsumed_completion_keeps_single_flight_slot(panels):
    panel = panels()
    worker = panel._poll_worker
    assert worker.start(0, panel._capture, deepcopy(panel._bars))
    _wait_until(lambda: not worker._thread.is_alive())
    assert worker.busy
    assert not worker.start(0, panel._capture, deepcopy(panel._bars))
    assert panel._capture.calls == 1
    assert worker.take_result() is not None
    assert not worker.busy


def test_deleted_widget_does_not_leave_a_worker_callback(monkeypatch):
    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    capture = FakeCapture(gate)
    panel = PollingPanel(capture, [_bar()])
    worker = panel._poll_worker
    reads = []
    monkeypatch.setattr(sampling, "read_vital_bar", lambda *_: reads.append(1))
    panel.poll_now()
    _wait_until(capture.started.is_set)
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert worker._cancelled.is_set()
    gate.set()
    _wait_until(lambda: not worker._thread.is_alive())
    app.processEvents()
    assert worker.take_result() is None
    assert reads == []
