"""Safe Project 1999 Social-button installation and UAC handoff."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from vantage.helpers.portable import data_dir


_SOCIAL_KEY_RX = re.compile(
    r"^(Page(?P<page>\d+)Button(?P<button>\d+))"
    r"(?:Name|Color|Line[1-5])\s*=", re.IGNORECASE)
_P99_CHARACTER_RX = re.compile(
    r"_(?:project1999|p1999(?:green|blue|pvp|red))\.ini$", re.IGNORECASE)
_REQUEST_NAME_RX = re.compile(r"^hotbutton-[0-9a-f]{32}\.json$")


@dataclass(frozen=True)
class ElevatedHotbuttonRequest:
    request_path: Path
    result_path: Path
    nonce: str
    started_at: float


def _validated_character_ini(ini_path):
    target = Path(ini_path).expanduser().resolve(strict=True)
    if not target.is_file() or target.suffix.casefold() != ".ini":
        raise ValueError("Choose a Project 1999 character INI file")
    if not _P99_CHARACTER_RX.search(target.name):
        raise ValueError("This does not look like a Project 1999 character INI")
    return target


def install_auction_hotbuttons(ini_path, lines, trade_type="WTS"):
    """Install WTS or WTB lines into unused P99 Social buttons safely."""
    trade_type = "WTB" if str(trade_type).strip().upper() == "WTB" else "WTS"
    target = _validated_character_ini(ini_path)
    commands = [
        line if str(line).lstrip().startswith("/") else f"/auction {line}"
        for line in (lines or ()) if str(line).strip()]
    if not commands:
        raise ValueError("Add at least one item before installing a hotbutton")
    chunks = [commands[index:index + 5]
              for index in range(0, len(commands), 5)]

    original = target.read_bytes()
    text = original.decode("cp1252")
    rows = text.splitlines()
    section_start = next((
        index for index, row in enumerate(rows)
        if row.strip().casefold() == "[socials]"), None)
    if section_start is None:
        if rows and rows[-1].strip():
            rows.append("")
        rows.append("[Socials]")
        section_start = len(rows) - 1
    section_end = next((
        index for index in range(section_start + 1, len(rows))
        if rows[index].strip().startswith("[") and
        rows[index].strip().endswith("]")), len(rows))

    vantage_slots = set()
    for row in rows[section_start + 1:section_end]:
        match = re.match(
            rf"^(Page\d+Button\d+)Name\s*=\s*Vantage{trade_type}\d*\s*$",
            row.strip(), re.IGNORECASE)
        if match:
            vantage_slots.add(match.group(1).casefold())

    kept = []
    occupied = set()
    for row in rows[section_start + 1:section_end]:
        match = _SOCIAL_KEY_RX.match(row.strip())
        prefix = match.group(1).casefold() if match else ""
        if prefix and prefix in vantage_slots:
            continue
        if prefix:
            occupied.add(prefix)
        kept.append(row)

    available = [
        f"Page{page}Button{button}"
        for page in range(2, 11) for button in range(1, 11)
        if f"page{page}button{button}" not in occupied]
    if len(available) < len(chunks):
        raise ValueError("There are not enough empty social buttons on pages 2–10")

    additions = []
    installed = []
    for index, command_group in enumerate(chunks, 1):
        prefix = available[index - 1]
        installed.append(prefix)
        additions.extend((
            f"{prefix}Name=Vantage{trade_type}{index}",
            f"{prefix}Color=0"))
        additions.extend(
            f"{prefix}Line{line_number}={command}"
            for line_number, command in enumerate(command_group, 1))
        additions.append("")

    rebuilt_section = kept
    if rebuilt_section and rebuilt_section[-1].strip():
        rebuilt_section.append("")
    rebuilt_section.extend(additions)
    updated = rows[:section_start + 1] + rebuilt_section + rows[section_end:]
    payload = ("\r\n".join(updated).rstrip() + "\r\n").encode("cp1252")

    backup = target.with_suffix(target.suffix + ".vantage-backup")
    shutil.copy2(target, backup)
    temporary = target.with_suffix(target.suffix + ".vantage-tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return tuple(installed), backup


def elevated_hotbutton_command(request_path, nonce, *, current_executable=None,
                               frozen=None, source_script=None):
    """Build the dedicated one-shot command used by Windows UAC."""
    current = Path(current_executable or sys.executable).resolve()
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)
    arguments = [
        "--install-auction-hotbuttons", str(Path(request_path).resolve()), nonce]
    if is_frozen and current.is_file():
        return str(current), subprocess.list2cmdline(arguments)
    source = (Path(source_script) if source_script is not None else
              Path(__file__).resolve().parents[3] / "vantage_app.py")
    if source.is_file():
        return sys.executable, subprocess.list2cmdline([str(source), *arguments])
    return None


def request_elevated_hotbutton_install(ini_path, lines, trade_type="WTS"):
    """Ask Windows to perform only this verified INI update with UAC."""
    if os.name != "nt":
        return None
    target = _validated_character_ini(ini_path)
    request_dir = data_dir("hotbutton-requests")
    request_dir.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    nonce = uuid.uuid4().hex
    request_path = request_dir / f"hotbutton-{request_id}.json"
    result_path = request_path.with_suffix(".result.json")
    payload = {
        "schema": 1,
        "nonce": nonce,
        "ini_path": str(target),
        "trade_type": "WTB" if str(trade_type).upper() == "WTB" else "WTS",
        "lines": [str(line) for line in lines if str(line).strip()],
    }
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    command = elevated_hotbutton_command(request_path, nonce)
    if command is None:
        request_path.unlink(missing_ok=True)
        return None
    program, arguments = command
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", program, arguments, None, 0)
    except (AttributeError, OSError):
        request_path.unlink(missing_ok=True)
        return None
    if int(result) <= 32:
        request_path.unlink(missing_ok=True)
        return None
    return ElevatedHotbuttonRequest(
        request_path, result_path, nonce, time.monotonic())


def process_elevated_hotbutton_request(request_path, nonce):
    """Process one UAC request before the normal Companion starts."""
    original_request = Path(request_path).expanduser()
    if original_request.is_symlink():
        return 2
    request = original_request.resolve(strict=True)
    if (request.parent.name.casefold() != "hotbutton-requests" or
            not _REQUEST_NAME_RX.fullmatch(request.name)):
        return 2
    result_path = request.with_suffix(".result.json")
    result = {"ok": False, "nonce": str(nonce), "error": "Invalid request"}
    exit_code = 1
    try:
        if request.stat().st_size > 256 * 1024:
            raise ValueError("Hotbutton request is too large")
        payload = json.loads(request.read_text(encoding="utf-8"))
        if payload.get("schema") != 1 or payload.get("nonce") != nonce:
            raise ValueError("Hotbutton request verification failed")
        lines = payload.get("lines")
        if not isinstance(lines, list) or not all(
                isinstance(line, str) for line in lines):
            raise ValueError("Hotbutton request lines are invalid")
        slots, backup = install_auction_hotbuttons(
            payload.get("ini_path", ""), lines,
            payload.get("trade_type", "WTS"))
        result = {
            "ok": True,
            "nonce": nonce,
            "trade_type": payload.get("trade_type", "WTS"),
            "slots": list(slots),
            "backup": str(backup),
        }
        exit_code = 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        result["error"] = str(error)
    try:
        result_path.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        return 3
    finally:
        request.unlink(missing_ok=True)
    return exit_code


def read_elevated_hotbutton_result(pending):
    """Return a completed result, or None while the helper is still running."""
    if not pending.result_path.is_file():
        return None
    try:
        result = json.loads(pending.result_path.read_text(encoding="utf-8"))
        if result.get("nonce") != pending.nonce:
            raise ValueError("Hotbutton result verification failed")
        return result
    finally:
        pending.result_path.unlink(missing_ok=True)
        pending.request_path.unlink(missing_ok=True)
