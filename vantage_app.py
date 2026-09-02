"""Vantage: a lightweight Project 1999 companion."""
import os
import sys


def _enable_crisp_windows_rendering():
    """Opt into native per-monitor pixels before Qt creates any surface."""
    if sys.platform != "win32":
        return
    # PyInstaller/Qt normally provide a DPI-aware manifest, but explicitly
    # requesting PMv2 prevents Windows from bitmap-stretching the whole UI on
    # mixed-DPI systems and when Vantage is moved between monitors.
    try:
        import ctypes
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):
            return  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

if __name__ == "__main__":
    if "--apply-update" in sys.argv:
        from vantage.helpers.update_apply import apply_staged_update
        raise SystemExit(apply_staged_update(sys.argv[1:]))
    cleanup_dir = os.environ.get("VANTAGE_UPDATE_CLEANUP", "")
    if cleanup_dir:
        from vantage.helpers.update_apply import schedule_update_cleanup
        schedule_update_cleanup(cleanup_dir)
    if "--portable-self-test" in sys.argv:
        from pathlib import Path
        import tempfile
        import traceback
        try:
            # Import the complete application graph so a release smoke test
            # catches missing src-layout packages and transitive Qt modules,
            # not merely the lightweight portable helper.
            from vantage.helpers.application import CURRENT_VERSION
            from vantage.helpers.portable import data_dir
            marker = data_dir() / "portable-self-test.txt"
            marker.write_text(
                f"{CURRENT_VERSION}\n{data_dir()}", encoding="utf-8")
        except Exception:
            error_file = Path(tempfile.gettempdir()) / (
                "vantage-self-test-error.txt")
            error_file.write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1)
        raise SystemExit(0)
    # Acquire the process lock before importing Qt or building any window.
    # A second launch therefore exits without a splash, taskbar flash, parser,
    # tray icon, or duplicate log reader.
    from vantage.helpers.single_instance import SingleInstanceGuard
    INSTANCE_GUARD = SingleInstanceGuard()
    if not INSTANCE_GUARD.acquired:
        raise SystemExit(0)
    _enable_crisp_windows_rendering()
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QCoreApplication.setOrganizationName("Vantage")
    QCoreApplication.setApplicationName("Vantage")
    try:
        import ctypes
        APPID = 'vantage.eqcompanion'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APPID)
    except Exception:
        pass
    from vantage.helpers.application import VantageApp
    APP = VantageApp(sys.argv)
    APP.setQuitOnLastWindowClosed(False)

    sys.exit(APP.exec())
