"""Windows clipboard support tailored to the EverQuest Titanium client."""

from __future__ import annotations

import sys
import time

from PySide6.QtWidgets import QApplication


CF_TEXT = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def clipboard_payloads(text):
    """Return the ANSI and Unicode payloads placed on the Windows clipboard."""
    value = str(text or "")
    return (
        value.encode("cp1252", errors="replace") + b"\0",
        value.encode("utf-16-le") + b"\0\0",
    )


def _set_windows_clipboard(text):
    """Publish both formats read by modern apps and the old Titanium client."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p

    ansi, unicode_text = clipboard_payloads(text)
    for _attempt in range(8):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.015)
    else:
        return False

    handles = []
    try:
        if not user32.EmptyClipboard():
            return False
        for clipboard_format, payload in (
                (CF_UNICODETEXT, unicode_text), (CF_TEXT, ansi)):
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
            if not handle:
                return False
            handles.append(handle)
            address = kernel32.GlobalLock(handle)
            if not address:
                return False
            try:
                ctypes.memmove(address, payload, len(payload))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(clipboard_format, handle):
                return False
            # Windows owns the allocation after SetClipboardData succeeds.
            handles.remove(handle)
        return True
    finally:
        user32.CloseClipboard()
        for handle in handles:
            kernel32.GlobalFree(handle)


def set_eq_clipboard(text):
    """Copy text in formats compatible with both Windows and EQ Titanium."""
    value = str(text or "")
    application = QApplication.instance()
    if application is not None:
        application.clipboard().setText(value)
    if sys.platform != "win32":
        return application is not None
    try:
        return _set_windows_clipboard(value)
    except (AttributeError, OSError):
        return application is not None
