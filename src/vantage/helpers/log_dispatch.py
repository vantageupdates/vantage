"""Bounded, text-free diagnostics for independent live-log consumers."""

from collections import deque
import copy
import json
import os
from pathlib import Path
import tempfile
import time


class LogDispatchHealth:
    """Record failures without copying EQ messages or exception messages."""

    def __init__(self, diagnostic_path):
        self.path = Path(diagnostic_path)
        self.events_received = 0
        self.events_completed = 0
        self.events_with_errors = 0
        self.last_received_at = 0.0
        self.last_completed_at = 0.0
        self._failure_count = 0
        self._active_errors = {}
        self._recent_events = deque(maxlen=100)
        self._last_write = float('-inf')
        self._dirty = False
        self._write_error = ''

    def begin_event(self):
        self.events_received += 1
        self.last_received_at = time.time()
        return self._failure_count

    def complete_event(self, marker):
        self.events_completed += 1
        self.last_completed_at = time.time()
        if self._failure_count != marker:
            self.events_with_errors += 1
        if self._recent_events:
            self._dirty = True
        self.flush()

    @property
    def has_errors(self):
        return bool(self._active_errors)

    def first_error(self):
        record = next(iter(self._active_errors.values()), None)
        return dict(record) if record else None

    def has_error(self, component):
        return component in self._active_errors

    def run(self, component, callback, *args, **kwargs):
        try:
            result = callback(*args, **kwargs)
        except Exception as error:
            self.failed(component, error)
            return False, None
        self.recovered(component)
        return True, result

    def failed(self, component, error):
        self._failure_count += 1
        component = str(component)[:80]
        now = time.time()
        record = self._active_errors.get(component)
        new_failure = record is None or record['error_type'] != type(error).__name__
        if new_failure:
            frames = []
            trace = error.__traceback__
            while trace is not None:
                frames.append({
                    'file': os.path.basename(trace.tb_frame.f_code.co_filename),
                    'function': trace.tb_frame.f_code.co_name[:80],
                    'line': trace.tb_lineno,
                })
                trace = trace.tb_next
            record = {
                'component': component,
                'error_type': type(error).__name__[:80],
                'count': 0,
                'first_at': now,
                'last_at': now,
                'frames': frames[-12:],
            }
            # Consumer names come from the application's fixed feature list.
            # Still bound the map so a future caller cannot grow it forever.
            if component not in self._active_errors and len(self._active_errors) >= 64:
                self._active_errors.pop(next(iter(self._active_errors)))
            self._active_errors[component] = record
            self._recent_events.append({
                'event': 'error', 'at': now,
                'component': component, 'error_type': record['error_type'],
                'frames': frames[-12:],
            })
        record['count'] += 1
        record['last_at'] = now
        self._dirty = True
        self.flush(force=new_failure)

    def recovered(self, component):
        previous = self._active_errors.pop(component, None)
        if previous is None:
            return
        self._recent_events.append({
            'event': 'recovered', 'at': time.time(),
            'component': component, 'error_type': previous['error_type'],
            'count': previous['count'],
        })
        self._dirty = True
        self.flush(force=True)

    def snapshot(self):
        return {
            'events_received': self.events_received,
            'events_completed': self.events_completed,
            'events_with_errors': self.events_with_errors,
            'last_received_at': self.last_received_at,
            'last_completed_at': self.last_completed_at,
            'active_errors': copy.deepcopy(list(self._active_errors.values())),
            'recent_events': copy.deepcopy(list(self._recent_events)),
            'diagnostic_path': str(self.path),
            'diagnostic_write_error': self._write_error,
        }

    def flush(self, force=False):
        now = time.monotonic()
        # Even alternating failure/recovery must not write once per log line.
        minimum_interval = 1 if force else 30
        if not self._dirty or now - self._last_write < minimum_interval:
            return
        self._last_write = now
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {'schema': 1, **self.snapshot()}
            payload['diagnostic_write_error'] = ''
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', prefix='.log-dispatch-',
                    suffix='.tmp', dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=True, indent=2)
            os.replace(temporary, self.path)
            self._write_error = ''
            self._dirty = False
        except Exception as error:
            # A read-only/full profile must not stop the live parser. The
            # in-memory evidence remains available in Log Profiles.
            self._write_error = type(error).__name__[:80]
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
