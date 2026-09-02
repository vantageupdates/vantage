"""Low-cost, read-only capture of the EverQuest window for LAN viewing."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading
import time

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


AUTO_EXECUTABLES = {"eqgame.exe", "everquest.exe"}
WINEQ_EXECUTABLES = {"wineq2.exe", "wineq2"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
BI_RGB = 0
DIB_RGB_COLORS = 0
PW_RENDERFULLCONTENT = 0x00000002
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
GA_ROOT = 2
GA_ROOTOWNER = 3

GAME_IMAGE_PROFILES = {
    "efficient": (1280, 72, "Efficient HD"),
    "hd": (1920, 86, "Sharp HD"),
    "native": (2560, 91, "Native detail"),
}


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BitmapInfoHeader),
        ("bmiColors", wintypes.DWORD * 1),
    ]


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", wintypes.WPARAM),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def _normal_path(path):
    return os.path.normcase(os.path.abspath(path)) if path else ""


class GameWindowCapture:
    """Captures a selected game window without providing any input channel."""

    def __init__(
            self, executable="", max_width=None, quality=None, fps=5,
            profile="hd"):
        self._target = _normal_path(executable)
        self._quality_profile = self._valid_image_profile(profile)
        profile_width, profile_quality, _ = GAME_IMAGE_PROFILES[
            self._quality_profile]
        self._max_width = max(
            480, min(int(max_width or profile_width), 2560))
        self._quality = max(
            35, min(int(quality or profile_quality), 94))
        self._fps = self._valid_fps(fps)
        self._enabled = False
        self._hwnd = 0
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached_frame = b""
        self._last_title = ""
        self._last_message = "Enable the view to find EverQuest."
        self._capture_error = ""
        self._capture_mode = ""
        self._supported = os.name == "nt"
        if self._supported:
            self._prepare_win32()

    @property
    def enabled(self):
        return self._enabled

    @property
    def executable(self):
        return self._target

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self._cached_frame = b""
        self._cached_at = 0.0
        if not self._enabled:
            self._last_message = "EverQuest View is off."

    def set_executable(self, executable):
        self._target = _normal_path(executable)
        self._hwnd = 0
        self._cached_frame = b""
        self._cached_at = 0.0

    def detect_running_executable(self):
        """Return the path of a currently visible EQ client when readable."""
        if not self._supported:
            return ""
        previous_target, previous_hwnd = self._target, self._hwnd
        self._target = ""
        self._hwnd = 0
        try:
            hwnd, _ = self._find_window()
            path = self._process_path(hwnd) if hwnd else ""
            if path and os.path.basename(path) in AUTO_EXECUTABLES:
                self.set_executable(path)
                return path
            # A WinEQ wrapper can own the visible surface. Resolve the real
            # client from the bounded process snapshot instead of saving the
            # wrapper as the game executable.
            for pid, name in self._process_names().items():
                if name in AUTO_EXECUTABLES:
                    path = self._process_path_from_pid(pid)
                    if path and os.path.basename(path) in AUTO_EXECUTABLES:
                        self.set_executable(path)
                        return path
        finally:
            if not self._target:
                self._target, self._hwnd = previous_target, previous_hwnd
        return ""

    def discover_executables(self):
        """Check the running client, registry and common install locations.

        This is intentionally bounded: it never crawls a whole disk.
        """
        found = []

        def remember(candidate):
            path = Path(str(candidate or "")).expanduser()
            try:
                path = path.resolve()
            except OSError:
                return
            if (path.is_file() and path.name.casefold() in AUTO_EXECUTABLES
                    and str(path) not in found):
                found.append(str(path))

        remember(self.detect_running_executable())
        remember(self._target)
        roots = {
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PUBLIC", ""),
            "C:\\Games",
            "C:\\EverQuest",
        }
        relatives = (
            "Sony/EverQuest/eqgame.exe",
            "Sony/EverQuest/EverQuest.exe",
            "Daybreak Game Company/Installed Games/EverQuest/eqgame.exe",
            "Steam/steamapps/common/EverQuest F2P/eqgame.exe",
            "EverQuest/eqgame.exe",
            "eqgame.exe",
        )
        for root in roots:
            if root:
                for relative in relatives:
                    remember(Path(root) / relative)

        if os.name == "nt":
            try:
                import winreg
                hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
                uninstall_keys = (
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                )
                for hive in hives:
                    for key_name in uninstall_keys:
                        try:
                            root_key = winreg.OpenKey(hive, key_name)
                        except OSError:
                            continue
                        with root_key:
                            for index in range(winreg.QueryInfoKey(root_key)[0]):
                                try:
                                    child = winreg.OpenKey(
                                        root_key, winreg.EnumKey(root_key, index))
                                    with child:
                                        display = str(winreg.QueryValueEx(
                                            child, "DisplayName")[0])
                                        if "everquest" not in display.casefold():
                                            continue
                                        location = str(winreg.QueryValueEx(
                                            child, "InstallLocation")[0])
                                        remember(Path(location) / "eqgame.exe")
                                except OSError:
                                    continue
            except (ImportError, OSError):
                pass
        return found

    @staticmethod
    def _valid_fps(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 5
        return value if value in {2, 5, 10} else 5

    @staticmethod
    def _valid_image_profile(value):
        value = str(value or "").strip().casefold()
        return value if value in GAME_IMAGE_PROFILES else "hd"

    def set_fps(self, fps):
        self._fps = self._valid_fps(fps)
        self._cached_at = 0.0

    def set_image_profile(self, profile):
        self._quality_profile = self._valid_image_profile(profile)
        self._max_width, self._quality, _ = GAME_IMAGE_PROFILES[
            self._quality_profile]
        self._cached_frame = b""
        self._cached_at = 0.0
        return self._quality_profile

    def status(self):
        if not self._supported:
            return self._status(False, "Capture is available on Windows only.")
        if not self._enabled:
            return self._status(False, "Enable 'EverQuest View' in Vantage.")
        hwnd, title = self._find_window()
        if not hwnd:
            message = (
                "EverQuest is not open or does not match the linked executable."
                if self._target else
                "EverQuest is not open. It will be detected automatically when it starts.")
            return self._status(False, message)
        if self._is_window_minimized(hwnd):
            return self._status(False, "EverQuest is minimized; restore it to view.", title)
        return self._status(True, "Local read-only view.", title)

    def is_game_foreground(self):
        """Return whether the real EQ client or its WinEQ surface has focus."""
        if not self._supported:
            return False
        hwnd, _ = self._find_window()
        return bool(hwnd and self._game_is_foreground(hwnd))

    def frame(self):
        """Return ``(status, jpeg)``. Capture is throttled and serialized."""
        with self._lock:
            status = self.status()
            if not status["available"]:
                return status, b""
            now = time.monotonic()
            if self._cached_frame and now - self._cached_at < (1.0 / self._fps):
                return status, self._cached_frame
            frame = self._capture_jpeg(self._hwnd)
            if not frame:
                message = self._capture_error or (
                    "Windows could not capture the image. Use EverQuest in windowed "
                    "or borderless-window mode.")
                self._last_message = message
                return self._status(False, message, self._last_title), b""
            self._cached_frame = frame
            self._cached_at = now
            return status, frame

    def _status(self, available, message, title=""):
        if title:
            self._last_title = title
        self._last_message = message
        return {
            "enabled": self._enabled,
            "available": bool(available),
            "title": self._last_title if available else title,
            "message": message,
            "local_only": True,
            "interactive": False,
            "target": os.path.basename(self._target) if self._target else "automatic",
            "fps": self._fps,
            "image_quality": self._quality_profile,
            "image_quality_label": GAME_IMAGE_PROFILES[
                self._quality_profile][2],
            "max_width": self._max_width,
            "jpeg_quality": self._quality,
        }

    def _prepare_win32(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        self._user32.EnumWindows.restype = wintypes.BOOL
        self._user32.EnumChildWindows.argtypes = [
            wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
        self._user32.EnumChildWindows.restype = wintypes.BOOL
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.GetWindowRect.restype = wintypes.BOOL
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindowDC.argtypes = [wintypes.HWND]
        self._user32.GetWindowDC.restype = wintypes.HDC
        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.ReleaseDC.restype = ctypes.c_int
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self._user32.GetAncestor.restype = wintypes.HWND
        self._user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        self._user32.IsChild.restype = wintypes.BOOL
        self._user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        self._user32.PrintWindow.restype = wintypes.BOOL

        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
        self._kernel32.Process32FirstW.restype = wintypes.BOOL
        self._kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
        self._kernel32.Process32NextW.restype = wintypes.BOOL

        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self._gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self._gdi32.SelectObject.restype = wintypes.HANDLE
        self._gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.DeleteDC.restype = wintypes.BOOL
        self._gdi32.GetDIBits.argtypes = [
            wintypes.HDC, wintypes.HANDLE, wintypes.UINT, wintypes.UINT,
            ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), wintypes.UINT]
        self._gdi32.GetDIBits.restype = ctypes.c_int
        self._gdi32.BitBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        self._gdi32.BitBlt.restype = wintypes.BOOL

    def _window_title(self, hwnd):
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    def _process_path(self, hwnd):
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return self._process_path_from_pid(pid.value)

    def _process_path_from_pid(self, pid):
        if not pid:
            return ""
        process = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not process:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if self._kernel32.QueryFullProcessImageNameW(
                    process, 0, buffer, ctypes.byref(size)):
                return _normal_path(buffer.value)
            return ""
        finally:
            self._kernel32.CloseHandle(process)

    def _window_pid(self, hwnd):
        pid = wintypes.DWORD()
        if hwnd:
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def _game_is_foreground(self, hwnd):
        """Accept WinEQ-owned/child surfaces without accepting another app.

        WinEQ can put focus on a child or root-owner surface instead of the
        exact top-level handle returned for eqgame.exe. Requiring handle
        equality made the phone report that it was still waiting even though
        the game itself was visibly active.
        """
        foreground = self._user32.GetForegroundWindow()
        if not foreground:
            return False
        if foreground == hwnd:
            return True
        if self._window_pid(foreground) == self._window_pid(hwnd):
            return True
        if (self._user32.IsChild(hwnd, foreground)
                or self._user32.IsChild(foreground, hwnd)):
            return True
        game_roots = {
            int(self._user32.GetAncestor(hwnd, GA_ROOT) or 0),
            int(self._user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0),
        }
        foreground_roots = {
            int(self._user32.GetAncestor(foreground, GA_ROOT) or 0),
            int(self._user32.GetAncestor(foreground, GA_ROOTOWNER) or 0),
        }
        if game_roots.intersection(foreground_roots) - {0}:
            return True
        # Some WinEQ versions put the wrapper surface in a separate process.
        # Both titles must explicitly identify the active EverQuest window.
        game_title = self._window_title(hwnd).casefold()
        foreground_title = self._window_title(foreground).casefold()
        return self._wineq_title_pair_is_game(game_title, foreground_title)

    @staticmethod
    def _wineq_title_pair_is_game(game_title, foreground_title):
        game_title = str(game_title or "").casefold()
        foreground_title = str(foreground_title or "").casefold()
        return (
            "everquest" in game_title and "everquest" in foreground_title
            and ("wineq" in game_title or "wineq" in foreground_title
                 or foreground_title == game_title))

    def _is_window_minimized(self, hwnd):
        handles = {
            int(hwnd or 0),
            int(self._user32.GetAncestor(hwnd, GA_ROOT) or 0),
            int(self._user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0),
        }
        return any(
            handle and self._user32.IsIconic(handle) for handle in handles)

    @staticmethod
    def _window_match_score(
            process_path, process_name, title, target, has_eq_process):
        """Score only a real EQ client or an EQ-labelled WinEQ surface."""
        process_path = _normal_path(process_path)
        process_name = os.path.normcase(str(process_name or ""))
        title_folded = str(title or "").casefold()
        target = _normal_path(target)
        target_name = os.path.basename(target)
        if target:
            if process_path == target:
                return 3_000_000
            if process_name == target_name:
                return 1_000_000
        elif process_name in AUTO_EXECUTABLES:
            return 3_000_000
        if (has_eq_process and process_name in WINEQ_EXECUTABLES
                and "everquest" in title_folded):
            return 750_000
        return 0

    def _process_names(self):
        """Return PID -> executable name without opening elevated processes."""
        snapshot = self._kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return {}
        names = {}
        try:
            entry = _ProcessEntry32()
            entry.dwSize = ctypes.sizeof(_ProcessEntry32)
            if not self._kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return names
            while True:
                if entry.szExeFile:
                    names[int(entry.th32ProcessID)] = os.path.normcase(entry.szExeFile)
                entry.dwSize = ctypes.sizeof(_ProcessEntry32)
                if not self._kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
            return names
        finally:
            self._kernel32.CloseHandle(snapshot)

    def _find_window(self):
        if self._hwnd and self._user32.IsWindow(self._hwnd):
            title = self._window_title(self._hwnd)
            if title and self._user32.IsWindowVisible(self._hwnd):
                self._last_title = title
                return self._hwnd, title
        self._hwnd = 0
        matches = []
        process_names = self._process_names()
        has_eq_process = any(
            name in AUTO_EXECUTABLES for name in process_names.values())
        roots = []
        seen = set()

        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def consider(hwnd):
            hwnd = int(hwnd)
            if not hwnd or hwnd in seen:
                return
            seen.add(hwnd)
            if not self._user32.IsWindowVisible(hwnd):
                return
            title = self._window_title(hwnd)
            if not title:
                return
            rect = wintypes.RECT()
            if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width < 320 or height < 200:
                return
            process_path = self._process_path(hwnd)
            pid = wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process_name = (
                os.path.basename(process_path)
                or process_names.get(int(pid.value), "")
            )
            score = self._window_match_score(
                process_path, process_name, title, self._target,
                has_eq_process)
            if score:
                matches.append((score + width * height, hwnd, title))

        @callback_type
        def visit(hwnd, _):
            roots.append(int(hwnd))
            consider(hwnd)
            return True

        self._user32.EnumWindows(visit, 0)
        # WinEQ may expose the DirectX surface as a descendant of its wrapper
        # rather than as a normal top-level eqgame window.
        @callback_type
        def visit_child(hwnd, _):
            consider(hwnd)
            return True

        for root in roots:
            self._user32.EnumChildWindows(root, visit_child, 0)
        if not matches:
            return 0, ""
        _, self._hwnd, self._last_title = max(matches, key=lambda item: item[0])
        return self._hwnd, self._last_title

    def _capture_jpeg(self, hwnd):
        self._capture_error = ""
        self._capture_mode = ""
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return b""
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0 or width > 8192 or height > 8192:
            return b""

        source_dc = self._user32.GetWindowDC(hwnd)
        if not source_dc:
            return b""
        memory_dc = self._gdi32.CreateCompatibleDC(source_dc)
        bitmap = self._gdi32.CreateCompatibleBitmap(source_dc, width, height)
        if not memory_dc or not bitmap:
            if bitmap:
                self._gdi32.DeleteObject(bitmap)
            if memory_dc:
                self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(hwnd, source_dc)
            return b""

        previous = self._gdi32.SelectObject(memory_dc, bitmap)
        try:
            if self._user32.PrintWindow(
                    hwnd, memory_dc, PW_RENDERFULLCONTENT):
                self._capture_mode = "window"
            else:
                # DirectX under WinEQ commonly rejects PrintWindow. Copying from
                # the game's own DC works reliably, but is allowed only while an
                # EQ/WinEQ surface is foreground so a covered desktop is never
                # exposed to the phone.
                if not self._game_is_foreground(hwnd):
                    self._capture_error = (
                        "WinEQ2 detected · bring EverQuest to the foreground to continue.")
                    return b""
                if self._gdi32.BitBlt(
                        memory_dc, 0, 0, width, height, source_dc,
                        0, 0, SRCCOPY):
                    self._capture_mode = "wineq-window"
                else:
                    screen_dc = self._user32.GetDC(0)
                    if not screen_dc:
                        return b""
                    try:
                        if not self._gdi32.BitBlt(
                                memory_dc, 0, 0, width, height, screen_dc,
                                rect.left, rect.top, SRCCOPY | CAPTUREBLT):
                            return b""
                        self._capture_mode = "wineq-screen"
                    finally:
                        self._user32.ReleaseDC(0, screen_dc)
            info = _BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # top-down pixels
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            pixels = ctypes.create_string_buffer(width * height * 4)
            if self._gdi32.GetDIBits(
                    memory_dc, bitmap, 0, height, pixels,
                    ctypes.byref(info), DIB_RGB_COLORS) != height:
                return b""
            image = QImage(
                bytes(pixels), width, height, width * 4,
                # A 32-bit Windows DIB is B,G,R,X in memory. Format_RGB32
                # represents that native little-endian layout in Qt.
                QImage.Format.Format_RGB32).copy()
            if image.isNull():
                return b""
            if image.width() > self._max_width:
                image = image.scaledToWidth(
                    self._max_width,
                    Qt.TransformationMode.SmoothTransformation)
            encoded = QByteArray()
            output = QBuffer(encoded)
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                return b""
            try:
                if not image.save(output, "JPEG", self._quality):
                    return b""
            finally:
                output.close()
            return bytes(encoded)
        finally:
            if previous:
                self._gdi32.SelectObject(memory_dc, previous)
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(hwnd, source_dc)
