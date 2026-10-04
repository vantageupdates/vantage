from PySide6.QtCore import QObject, Signal
import shiboken6
import threading
import pytest

from vantage.parsers.log_searcher import (
    _LogSearchCancelled, _emit_unless_cancelled, _safe_signal_emit)


class _Signals(QObject):
    done = Signal(object)


def test_late_log_worker_signal_is_ignored_after_qt_owner_is_destroyed():
    signals = _Signals()
    done = signals.done
    shiboken6.delete(signals)

    assert _safe_signal_emit(done, {"late": True}) is False


def test_cancelled_log_worker_stops_before_touching_qt_signal_owner():
    signals = _Signals()
    received = []
    signals.done.connect(received.append)
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(_LogSearchCancelled):
        _emit_unless_cancelled(stop_event, signals.done, {"late": True})

    assert received == []


def test_unrelated_log_worker_runtime_error_is_not_hidden():
    class BrokenSignal:
        @staticmethod
        def emit(*_args):
            raise RuntimeError("backend invariant failed")

    with pytest.raises(RuntimeError, match="backend invariant failed"):
        _safe_signal_emit(BrokenSignal(), {"result": "important"})
