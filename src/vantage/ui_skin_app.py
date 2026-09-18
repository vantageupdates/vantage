"""Small standalone VantageUI window; the updater core stays GUI-independent."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from vantage.helpers import ui_skin_updater as updater

DEFAULT_EQ = r"C:\Program Files (x86)\Sony\EverQuest"
CHECK_SECONDS = 300
BG, PANEL, TEXT, MUTED, GOLD = "#14191d", "#1f252b", "#e4e8eb", "#adb8bf", "#bba66f"


def app_version():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    if getattr(sys, "frozen", False):
        candidates = (root / "ui-release.json", root / "release.json")
    else:
        candidates = (root / "ui/release.json",)
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    return json.loads(path.read_text(encoding="utf-8"))["version"]


def state_root():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()/"AppData/Local")))
    return base / "Vantage" / "UIUpdater"


def version_key(value):
    try:
        values = tuple(int(x) for x in value.split("."))
        return values if len(values) == 3 else (0, 0, 0)
    except (TypeError, ValueError):
        return (0, 0, 0)


def update_available(installed, available):
    return bool(available) and (not installed or version_key(available) > version_key(installed))


def local_selection(eq_dir):
    """Read one folder selection, so its version and command cannot disagree."""
    folder = updater.installed_folder(eq_dir)
    if not folder:
        return "", ""
    prefix = updater.SKIN_FOLDER + "-v"
    version = folder[len(prefix):] if folder.startswith(prefix) else ""
    if not version or updater.folder_name(version) != folder:
        raise updater.SkinUpdateError("The selected VantageUI folder is invalid.")
    return version, folder


def load_settings(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid settings")
        return {"eq_dir": data.get("eq_dir") if isinstance(data.get("eq_dir"), str) else DEFAULT_EQ,
                "automatic": data.get("automatic") is True}
    except (OSError, ValueError):
        return {"eq_dir": DEFAULT_EQ, "automatic": False}


class SkinWindow:
    def __init__(self, root, settings_dir=None, eq_dir=None, test_mode=False,
                 allow_game_running=False):
        self.root = root
        self.settings_dir = Path(settings_dir) if settings_dir else state_root()
        self.settings_path = self.settings_dir / "settings.json"
        self.backups = self.settings_dir / "backups"
        settings = load_settings(self.settings_path)
        self.eq = tk.StringVar(root, eq_dir or settings["eq_dir"])
        self.automatic = tk.BooleanVar(root, settings["automatic"])
        self.installed = ""
        self.folder = ""
        self.known_eq = ""
        self.operation_eq = ""
        self.release = None
        self.pending = False
        self.allow_game_running = bool(allow_game_running)
        self.busy = False
        self.confirming = False
        self.events = queue.Queue()
        self.next_check = time.monotonic() + CHECK_SECONDS
        self.retry_at = 0.0
        self.test_mode = test_mode
        self.status = tk.StringVar(root, "Select your EverQuest folder to get started.")
        self.versions = tk.StringVar(root, "Installed: not registered     Available: not checked")
        self.destination = tk.StringVar(root)
        self.command = tk.StringVar(root)
        self._build()
        self.eq.trace_add("write", self._path_changed)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if not test_mode:
            self.root.after(100, self._pump)
            self.root.after(250, self.refresh_local)

    def _build(self):
        root = self.root
        root.title("VantageUI · EverQuest")
        root.configure(bg=BG)
        root.geometry("800x650")
        root.minsize(720, 650)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", foreground=TEXT, font=("Segoe UI Semibold", 23))
        style.configure("Gold.TLabel", foreground=GOLD, font=("Segoe UI", 10))
        style.configure("TButton", background=PANEL, foreground=TEXT, bordercolor="#424d55",
                        focuscolor=GOLD, padding=(14, 9), font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#354149"), ("pressed", "#182026")],
                  foreground=[("disabled", "#78838b")], bordercolor=[("focus", GOLD)])
        style.configure("Primary.TButton", background="#3c493f", bordercolor="#6c826e")
        style.map("Primary.TButton", background=[("active", "#4a5c4e"), ("disabled", PANEL)])
        style.configure("Update.Horizontal.TProgressbar", troughcolor="#0e1418",
                        background=GOLD, bordercolor="#424d55")
        style.configure("TEntry", fieldbackground="#0e1418", foreground=TEXT,
                        insertcolor=TEXT, bordercolor="#424d55", padding=8)
        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", MUTED)])
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(11, weight=1)
        ttk.Label(outer, text="VANTAGE COMPANION", style="Gold.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="Your UI, always up to date.", style="Title.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 6))
        ttk.Label(outer, text="VantageUI for EverQuest Titanium / Project 1999", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 20))
        ttk.Label(outer, text="EverQuest folder · contains eqgame.exe").grid(row=3, column=0, sticky="w", pady=(0, 6))
        path_row = ttk.Frame(outer)
        path_row.grid(row=4, column=0, sticky="ew")
        path_row.columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(path_row, textvariable=self.eq)
        self.path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.path_entry.bind("<Return>", lambda event: self.refresh_local())
        self.browse_button = ttk.Button(path_row, text="Browse…", command=self.browse)
        self.browse_button.grid(row=0, column=1)
        ttk.Label(outer, textvariable=self.destination, wraplength=650,
                  style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(7, 12))
        ttk.Label(outer, textvariable=self.versions, style="Gold.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 12))
        actions = ttk.Frame(outer)
        actions.grid(row=7, column=0, sticky="w")
        self.check_button = ttk.Button(actions, text="Check for updates", command=self.check)
        self.check_button.pack(side="left", padx=(0, 8))
        self.install_button = ttk.Button(actions, text="Update UI", style="Primary.TButton", command=self.install)
        self.install_button.pack(side="left", padx=(0, 8))
        self.restore_button = ttk.Button(actions, text="Restore previous", command=self.restore)
        self.restore_button.pack(side="left")
        auto = ttk.Frame(outer)
        auto.grid(row=8, column=0, sticky="ew", pady=(18, 12))
        self.auto_button = ttk.Checkbutton(auto, text="Update automatically while this window is open",
                                           variable=self.automatic, command=self.toggle_auto)
        self.auto_button.pack(anchor="w")
        auto_hint = (
            "Checks every 5 minutes. Installation can run while EQ is open; cleanup waits until it closes."
            if self.allow_game_running else
            "Checks every 5 minutes. Close EverQuest before installing or restoring a previous version.")
        self.auto_hint = ttk.Label(auto, text=auto_hint, wraplength=650, style="Muted.TLabel")
        self.auto_hint.pack(anchor="w", pady=(4, 0))
        self.progress_value = tk.IntVar(root, 0)
        self.progress_text = tk.StringVar(root, "Ready · 0%")
        self.progressbar = ttk.Progressbar(
            outer, variable=self.progress_value, maximum=100,
            style="Update.Horizontal.TProgressbar")
        self.progressbar.grid(row=9, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(outer, textvariable=self.progress_text,
                  style="Muted.TLabel").grid(row=10, column=0, sticky="w")
        self.logbox = tk.Text(outer, height=6, bg="#10161a", fg=MUTED, font=("Segoe UI", 10),
                              relief="flat", borderwidth=0, padx=12, pady=4, wrap="word",
                              state="disabled", takefocus=True)
        self.logbox.grid(row=11, column=0, sticky="nsew")
        self.logbox.bind("<Control-a>", self._select_all_log)
        self.logbox.bind("<Control-c>", self._copy_log_selection)
        for sequence, direction, units in (
                ("<Up>", -1, "units"), ("<Down>", 1, "units"),
                ("<Prior>", -1, "pages"), ("<Next>", 1, "pages")):
            self.logbox.bind(
                sequence,
                lambda event, amount=direction, mode=units: self._scroll_log(amount, mode))
        self.logbox.bind("<Home>", lambda event: self._move_log(0.0))
        self.logbox.bind("<End>", lambda event: self._move_log(1.0))
        ttk.Label(outer, textvariable=self.status, wraplength=650).grid(row=12, column=0, sticky="w", pady=(12, 8))
        command_row = ttk.Frame(outer)
        command_row.grid(row=13, column=0, sticky="ew")
        command_row.columnconfigure(0, weight=1)
        ttk.Label(command_row, textvariable=self.command, wraplength=490,
                  style="Gold.TLabel").grid(row=0, column=0, sticky="w")
        self.copy_button = ttk.Button(command_row, text="Copy command", command=self.copy_command)
        self.copy_button.grid(row=0, column=1, padx=(10, 0))
        ttk.Label(outer, text=f"Updater {app_version()} · Does not change other skins or INI files.",
                  style="Muted.TLabel").grid(row=14, column=0, sticky="w", pady=(6, 0))
        self._version_text()
        self._controls()

    def _controls(self):
        controls = (self.browse_button, self.check_button, self.install_button,
                    self.restore_button, self.path_entry, self.auto_button,
                    self.copy_button)
        if (self.busy or self.confirming) and self.root.focus_get() in controls:
            self.logbox.focus_set()
        for widget in (self.browse_button, self.check_button, self.restore_button, self.path_entry, self.auto_button):
            widget.configure(state="disabled" if self.busy or self.confirming else "normal")
        self.install_button.configure(state="normal" if self.release and not self.busy and not self.confirming else "disabled")
        self.copy_button.configure(state="normal" if self.folder and self.known_eq == self.eq.get().strip()
                                   and not self.busy and not self.confirming else "disabled")

    def _path_changed(self, *args):
        self.installed = self.folder = self.known_eq = ""
        self.release = None
        self.pending = False
        self._version_text()
        self._controls()

    def copy_command(self):
        if self.busy or self.confirming or not self.folder or self.known_eq != self.eq.get().strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(f"/loadskin {self.folder} 1")
        self.status.set("Command copied. Paste it in EverQuest to load this folder.")

    def _save(self):
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"eq_dir": self.eq.get().strip(), "automatic": self.automatic.get()}), encoding="utf-8")
            os.replace(temporary, self.settings_path)
            return True
        except OSError as error:
            self.automatic.set(False)
            self.pending = False
            self._log(f"Could not save settings.{updater.error_diagnostic(error)}")
            self.status.set("Automatic mode paused: settings could not be saved.")
            return False

    def _confirm(self, title, text):
        # Tk dialogs run a nested event loop. Pause automatic scheduling until
        # the user's decision is complete, including cancellation.
        self.confirming = True
        self._controls()
        try:
            return messagebox.askokcancel(title, text, parent=self.root)
        finally:
            self.confirming = False
            self._controls()

    def _log(self, line):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _select_all_log(self, _event=None):
        self.logbox.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _copy_log_selection(self, _event=None):
        try:
            selection = self.logbox.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selection)
        return "break"

    def _scroll_log(self, amount, units):
        self.logbox.yview_scroll(amount, units)
        return "break"

    def _move_log(self, fraction):
        self.logbox.yview_moveto(fraction)
        return "break"

    def _version_text(self):
        available = self.release.version if self.release else "not checked"
        self.versions.set(f"Installed: {self.installed or 'not registered'}     Available: {available}")
        selected = self.folder or "no versioned folder selected"
        next_folder = updater.folder_name(self.release.version) if self.release else "not checked"
        self.destination.set(f"Selected: {selected}\nNext installation: uifiles\\{next_folder}")
        self.command.set(f"/loadskin {self.folder} 1" if self.folder else "Install or check a version to get its command.")

    def _work(self, action, callback):
        if self.busy:
            return
        self.busy = True
        self.operation_eq = self.eq.get().strip()
        self.progress_value.set(0)
        self.progress_text.set("Preparing · 0%")
        self._controls()
        def run():
            try:
                self.events.put(("done", action, callback()))
            except Exception as error:
                self.events.put(("error", action, error))
        threading.Thread(target=run, name="VantageUI-worker", daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, action, result = self.events.get_nowait()
                if kind == "log":
                    self._log(result)
                    continue
                if kind == "progress":
                    stage, percent, received, total = result
                    value = max(self.progress_value.get(), min(100, int(percent)))
                    self.progress_value.set(value)
                    suffix = f" · {received}/{total} bytes" if total else ""
                    self.progress_text.set(f"{stage} · {value}%{suffix}")
                    continue
                start_automatic_install = False
                self.busy = False
                if self.operation_eq and self.operation_eq != self.eq.get().strip():
                    self.operation_eq = ""
                    self._path_changed()
                    self.status.set("The folder changed. Check the current selection; the operation used the previous folder.")
                    continue
                self.operation_eq = ""
                if kind == "error":
                    self.installed = self.folder = self.known_eq = ""
                    self.release = None
                    self.pending = False
                    self.retry_at = time.monotonic() + CHECK_SECONDS
                    self.status.set("The operation did not complete. Review the log.")
                    self.progress_text.set(
                        f"Failed · {self.progress_value.get()}%")
                    self._log("The operation failed."
                              f"{updater.error_diagnostic(result)}")
                    sharing = (
                        getattr(result, "winerror", None) in (32, 33) or
                        getattr(result, "errno", None) in (16, 26))
                    if sharing:
                        self.status.set(
                            "The installation stopped safely. "
                            "Do not reload the UI; resolve the lock and try again.")
                        self._log(
                            "Windows has a file in use. Close the application using that file "
                            "and try again; do not reload the UI yet.")
                    elif isinstance(result, PermissionError):
                        self._log("Windows does not allow writing here. Close the updater, right-click it, and select Run as administrator.")
                elif action == "check":
                    self.release, selection = result
                    self.installed, self.folder = selection
                    self.known_eq = self.eq.get().strip()
                    self.pending = False
                    start_automatic_install = (
                        self.automatic.get() and
                        update_available(self.installed, self.release.version))
                    self.status.set("An update is available." if update_available(self.installed, self.release.version) else "Your version is up to date. Your local changes will be preserved.")
                else:
                    if action == "local":
                        self.installed, self.folder = result
                    else:
                        self.installed, self.folder = result.version, result.folder
                    self.known_eq = self.eq.get().strip()
                    if action == "local":
                        self.status.set("Selection checked. The legacy VantageUI folder remains untouched; it is not treated as a versioned installation.")
                    else:
                        self.status.set(f"Operation complete. In game: /loadskin {self.folder} 1")
                        for warning in result.warnings:
                            self._log(warning)
                        if result.warnings:
                            self.status.set(f"Selected installation: {self.folder}. Some folders are protected or cleanup is pending; review the log.")
                    if action in ("install", "restore"):
                        self.pending = False
                    self.progress_value.set(100)
                    self.progress_text.set("Complete · 100%")
                self._version_text()
                self._controls()
                if action == "check" and start_automatic_install:
                    self.install(automatic=True)
        except queue.Empty:
            pass
        now = time.monotonic()
        if not self.busy and not self.confirming and self.automatic.get() and now >= self.next_check:
            self.check()
        self.root.after(150, self._pump)

    def refresh_local(self):
        if self.busy:
            return
        eq = self.eq.get().strip()
        self.release = None
        self.pending = False
        self._save()
        def run():
            updater.recover_pending(
                eq, self.backups, log=self.worker_log,
                allow_game_running=self.allow_game_running,
                progress=self.worker_progress)
            return local_selection(eq)
        self._work("local", run)

    def browse(self):
        chosen = filedialog.askdirectory(parent=self.root, title="Select the folder containing eqgame.exe", initialdir=self.eq.get())
        if chosen:
            self.eq.set(chosen)
            self.refresh_local()

    def check(self):
        if self.busy:
            return
        eq = self.eq.get().strip()
        self.pending = False
        self.next_check = time.monotonic() + CHECK_SECONDS
        self.status.set("Checking the official Vantage release…")
        self._save()
        def run():
            release = updater.check_release(progress=self.worker_progress)
            return release, local_selection(eq)
        self._work("check", run)

    def worker_log(self, message):
        self.events.put(("log", "", message))

    def worker_progress(self, stage, percent, received=0, total=0):
        self.events.put(("progress", "", (
            str(stage), int(percent), int(received), int(total))))

    def install(self, automatic=False):
        if not self.release or self.busy:
            return
        if not automatic:
            next_folder = updater.folder_name(self.release.version)
            live_copy = (
                "If EverQuest is open, installation will continue without closing it. "
                "Do not reload the UI during the operation; after it succeeds, use "
                f"/loadskin {next_folder} 1. Cleanup of older versions will wait until the game closes."
                if self.allow_game_running else "EverQuest must be closed.")
            if not self._confirm("Update VantageUI", f"uifiles\\{next_folder} will be installed.\nThe selected version and two previous fallback versions will be kept.\nModified, unmanaged, and legacy VantageUI folders will not be deleted.\n\n" + live_copy):
                self.automatic.set(False)
                self.pending = False
                self._save()
                self.status.set("Update canceled. Automatic mode paused.")
                return
        if self.busy:
            return
        selected, eq = self.release, self.eq.get().strip()
        self.pending = False
        self.status.set("Updating — do not reload the UI yet.")
        self._work("install", lambda: updater.install_release(
            selected, eq, self.backups, log=self.worker_log,
            allow_game_running=self.allow_game_running,
            progress=self.worker_progress))

    def restore(self):
        if self.busy or not self._confirm("Restore VantageUI", "The retained previous version folder will be selected.\nNo files will be overwritten and your INI files will not be changed.\nAfterward, load its command in EverQuest.\n\nEverQuest must be closed."):
            return
        if self.busy:
            return
        self.automatic.set(False)
        self.pending = False
        self._save()
        eq = self.eq.get().strip()
        self.status.set("Restoring the previous installation…")
        self._work("restore", lambda: updater.rollback_last(
            eq, self.backups, log=self.worker_log,
            progress=self.worker_progress))

    def toggle_auto(self):
        self._save()
        self.pending = False
        if self.automatic.get():
            self.check()
        else:
            self.status.set("Automatic updates disabled.")

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation in progress", "Wait for the operation to finish before closing.", parent=self.root)
            return
        try:
            self._save()
        finally:
            self.root.destroy()


def self_test():
    """Offline portable check: no network, process changes or live skin writes."""
    assert updater.SKIN_FOLDER == "VantageUI"
    assert updater.folder_name(app_version()) == "VantageUI-v" + app_version()
    assert update_available("1.2.3", "1.2.4")
    assert not update_available("1.2.4", "1.2.3")
    with tempfile.TemporaryDirectory(prefix="vantage-ui-self-test-") as temporary:
        root = tk.Tk()
        root.withdraw()
        app = SkinWindow(root, settings_dir=temporary, test_mode=True)
        root.update_idletasks()
        assert str(app.install_button["state"]) == "disabled"
        assert not app.automatic.get()
        assert str(app.copy_button["state"]) == "disabled"
        app.installed = app_version()
        app.folder = updater.folder_name(app.installed)
        app.known_eq = app.eq.get().strip()
        app._version_text()
        app._controls()
        assert app.command.get() == f"/loadskin {app.folder} 1"
        assert str(app.copy_button["state"]) == "normal"
        app.busy = True
        app._controls()
        assert str(app.restore_button["state"]) == "disabled"
        assert str(app.copy_button["state"]) == "disabled"
        root.destroy()
    return {"status": "PASS", "version": app_version(), "network": False, "live_skin_writes": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="VantageUI updater")
    parser.add_argument("--eq-dir", help="EverQuest folder containing eqgame.exe")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--allow-game-running", action="store_true",
                        help="Allow verified live install without closing EverQuest")
    parser.add_argument("--report", type=Path, help="Optional self-test JSON output")
    args = parser.parse_args(argv)
    if args.self_test:
        result = self_test()
        if args.report:
            args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return 0
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    SkinWindow(root, eq_dir=args.eq_dir,
               allow_game_running=args.allow_game_running)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
