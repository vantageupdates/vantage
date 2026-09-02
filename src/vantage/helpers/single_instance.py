"""Process-lifetime single-instance guard for the portable Windows app."""

from __future__ import annotations

import ctypes
import os


ERROR_ALREADY_EXISTS = 183
DEFAULT_MUTEX_NAME = r"Local\Vantage.EQCompanion.SingleInstance"


class SingleInstanceGuard:
    """Own a named Windows mutex until this process exits."""

    def __init__(self, name=DEFAULT_MUTEX_NAME):
        self.name = str(name or DEFAULT_MUTEX_NAME)
        self._handle = None
        self.acquired = True
        if os.name != "nt":
            return

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            # Fail open if Windows itself cannot create the mutex.  A startup
            # failure is worse than the unlikely duplicate in this condition.
            return
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            self.acquired = False
            return
        self._handle = handle
        self._kernel32 = kernel32

    def close(self):
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self):
        self.close()

