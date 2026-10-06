"""Safe, data-only import of GINA trigger packages."""

from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile

from vantage.parsers.spells import CustomTrigger, compile_trigger_pattern
from vantage.helpers import text_time_to_seconds
from vantage.helpers.trigger_groups import (
    group_ancestors, normalize_trigger_color, normalize_trigger_groups)
from vantage.helpers.portable import resolve_portable_path, store_portable_bytes


MAX_PACKAGE_BYTES = 12 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 256
MAX_MEDIA_BYTES = 8 * 1024 * 1024
MAX_UNPACKED_BYTES = 24 * 1024 * 1024
MAX_TRIGGERS = 1500
MAX_PATTERN_LENGTH = 4096


class GinaImportError(ValueError):
    pass


class GinaImportBatch(list):
    """List-compatible preview batch that stages package audio in memory."""

    def __init__(self, triggers=(), media=None, warnings=None,
                 format_name="GINA trigger pack", groups=None):
        super().__init__(triggers)
        self._media = dict(media or {})
        self.warnings = list(warnings or ())
        self.format_name = format_name
        self.groups = dict(groups or {})

    def warnings_for(self, trigger):
        return [warning for warning in self.warnings
                if warning.get("trigger") in ("", trigger.name)]

    def has_embedded_audio(self, trigger, field=None):
        refs = getattr(trigger, "_gina_media_refs", {})
        if field:
            return refs.get(field) in self._media
        return any(media_id in self._media for media_id in refs.values())

    def preview_audio_delivery(self, trigger, stage="basic"):
        """Resolve staged WAV choices without writing a path or running audio."""
        if trigger.audio_muted:
            return "off"
        field = "sound_path" if stage == "basic" else f"timer_{stage}_sound"
        mode_field = "delivery" if stage == "basic" else f"timer_{stage}_delivery"
        if getattr(trigger, mode_field) == "legacy" and self.has_embedded_audio(trigger, field):
            return "sound"
        return trigger.audio_delivery(stage)

    def materialize_selected(self, triggers):
        """Commit only selected triggers' validated WAV data to profile storage."""
        selected = list(triggers)
        for trigger in selected:
            refs = getattr(trigger, "_gina_media_refs", {})
            for field, media_id in refs.items():
                media = self._media.get(media_id)
                if not media:
                    continue
                filename, content = media
                wav_name = f"{Path(filename).stem or 'gina-audio'}.wav"
                setattr(trigger, field, store_portable_bytes(
                    content, wav_name, subdir="sounds/gina-imports"))
        return selected


def _warning(warnings, name, code, message):
    warnings.append({"trigger": name, "code": code, "message": message})


def _validate_patterns(trigger, warnings):
    for label, text, regex, mode in [
            ("Match", trigger.text, trigger.regex, trigger.match_mode),
            *(("Early ender", entry.get("text", ""), entry.get("regex", False), "full")
              for entry in trigger.end_patterns)]:
        try:
            compile_trigger_pattern(text, raw_regex=regex, match_mode=mode)
        except (re.error, ValueError) as error:
            _warning(warnings, trigger.name, "invalid-pattern",
                     f"{label} pattern cannot run in Vantage: {error}. "
                     "GINA/.NET-only regex syntax is not translated; edit before enabling.")


_GINA_FIELDS = {
    "Name", "TriggerText", "EnableRegex", "UseText", "DisplayText",
    "PlayMediaFile", "MediaFileId", "UseTextToVoice", "TextToVoiceText",
    "InterruptSpeech", "TimerType", "TimerName", "TimerMillisecondDuration",
    "TimerDuration", "TimerStartBehavior", "RestartBasedOnTimerName",
    "TimerVisibleDuration", "UseTimerEnding", "TimerEndingTime",
    "TimerEndingTrigger", "UseTimerEnded", "TimerEndedTrigger",
    "UseCounterResetTimer", "CounterResetDuration", "CopyToClipboard",
    "ClipboardText", "TimerEarlyEnders", "TimerEarlyEndText", "Comments",
    "Category", "SuggestedCategory", "Id", "ID", "Guid", "GUID",
}
_GINA_STAGE_FIELDS = {
    "UseText", "DisplayText", "PlayMediaFile", "MediaFileId",
    "UseTextToVoice", "TextToVoiceText", "InterruptSpeech",
}


def _gina_compatibility(element, trigger, media, warnings):
    for label, stage, fields in (
            ("Match", element, _GINA_FIELDS),
            ("Timer ending", _child(element, "TimerEndingTrigger"), _GINA_STAGE_FIELDS),
            ("Timer ended", _child(element, "TimerEndedTrigger"), _GINA_STAGE_FIELDS)):
        if stage is None:
            continue
        unsupported = sorted({_local(child.tag) for child in stage
                              if _local(child.tag) not in fields
                              and ((child.text or "").strip() or len(child))})
        if unsupported:
            _warning(warnings, trigger.name, "unsupported-settings",
                     f"{label}: settings not imported: {', '.join(unsupported[:20])}.")
        has_sound = _truth(_child_text(stage, "PlayMediaFile"))
        has_voice = _truth(_child_text(stage, "UseTextToVoice"))
        if has_sound and has_voice:
            _warning(warnings, trigger.name, "combined-audio",
                     f"{label}: GINA can play Sound and Voice together. Vantage uses "
                     "one audio route per phase; Sound takes priority. Both choices "
                     "are retained for editing, not simultaneous playback.")
        if has_sound and _media_id(stage) not in media:
            _warning(warnings, trigger.name, "missing-audio",
                     f"{label}: no valid packaged WAV was found; a Vantage gallery "
                     "sound is substituted. External sound paths are never loaded.")
        external = [child for child in stage
                    if any(word in _local(child.tag).casefold()
                           for word in ("path", "filename", "mediafile"))
                    and _local(child.tag) not in {"PlayMediaFile", "MediaFileId"}
                    and (child.text or "").strip()]
        if external:
            _warning(warnings, trigger.name, "external-path",
                     f"{label}: external file references were ignored; no outside "
                     "file or executable is opened.")
    if trigger.regex:
        _warning(warnings, trigger.name, "regex-dialect",
                 "Vantage uses Python regular expressions, not GINA/.NET regex. "
                 "Review matching behavior before enabling this imported rule.")
    milliseconds = _integer(_child_text(element, "TimerMillisecondDuration", "0"))
    if milliseconds % 1000:
        _warning(warnings, trigger.name, "timer-precision",
                 "Millisecond timer duration was rounded down to whole seconds.")
    _validate_patterns(trigger, warnings)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(element, name, default=""):
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return default


def _child(element, name):
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _truth(value):
    return re.sub(r"\s+", "", str(value or "")).casefold() in {
        "true", "1", "yes", "on"}


def _early_enders(trigger):
    """Return every data-only GINA early ender and its pattern mode."""
    patterns = []
    for child in trigger:
        if _local(child.tag) != "TimerEarlyEnders":
            continue
        for early_ender in child:
            if _local(early_ender.tag) != "EarlyEnder":
                continue
            value = (
                _child_text(early_ender, "EarlyEndText") or
                _child_text(early_ender, "TriggerText")).strip()
            if value:
                patterns.append({
                    "text": value[:MAX_PATTERN_LENGTH],
                    "regex": _truth(_child_text(
                        early_ender, "EnableRegex")),
                })
    if patterns:
        return patterns
    legacy = _child_text(trigger, "TimerEarlyEndText")
    return [
        {"text": line.strip()[:MAX_PATTERN_LENGTH], "regex": False}
        for line in legacy.splitlines() if line.strip()]


def _timer_type(value, duration):
    folded = str(value or "").casefold()
    if "repeat" in folded:
        return "repeating"
    if "stopwatch" in folded or "count up" in folded:
        return "stopwatch"
    if folded in ("notimer", "no timer", "false", "0"):
        return "none"
    return "countdown" if duration > 0 or "timer" in folded else "none"


def _integer(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError, OverflowError):
        return default


def _subtrigger(trigger, name):
    element = _child(trigger, name)
    if element is None:
        return {"alert": "", "sound": "", "tts": "", "interrupt": False,
                "media_id": None}
    use_text = _truth(_child_text(element, "UseText"))
    has_media = _truth(_child_text(element, "PlayMediaFile"))
    alert = _child_text(element, "DisplayText") if use_text else ""
    tts = (
        _child_text(element, "TextToVoiceText")
        if _truth(_child_text(element, "UseTextToVoice")) else "")
    return {
        "alert": _safe_name(alert, "") if alert else "",
        "sound": _gallery_sound(element, has_media),
        "tts": _safe_name(tts, "") if tts else "",
        "interrupt": _truth(_child_text(element, "InterruptSpeech")),
        "media_id": _media_id(element) if has_media else None,
    }


def _media_id(element):
    value = _integer(_child_text(element, "MediaFileId"), 0)
    return value if value > 0 else None


def _restart_behavior(trigger):
    value = _child_text(trigger, "TimerStartBehavior").casefold()
    if any(word in value for word in ("ignore", "do not", "keep")):
        return "keep"
    if any(word in value for word in ("new", "additional", "another")):
        return "new"
    return "restart"


def _duration(seconds):
    try:
        seconds = max(0, min(int(float(seconds or 0)), 31_536_000))
    except (TypeError, ValueError, OverflowError):
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _safe_name(value, fallback):
    value = re.sub(r"[\x00-\x1f]+", " ", str(value or "")).strip()
    return (value or fallback)[:120]


def _gallery_sound(trigger, has_audio):
    if not has_audio:
        return ""
    text = " ".join((
        _child_text(trigger, "Name"),
        _child_text(trigger, "TriggerText"),
        _child_text(trigger, "Category"),
    ))
    return _gallery_sound_from_text(text)


def _gallery_sound_from_text(text):
    text = str(text or "").casefold()
    if any(word in text for word in ("charm", "danger", "death", "slain", "enrage")):
        return "builtin:danger-double"
    if any(word in text for word in ("invis", "fade", "wear", "ending")):
        return "builtin:crystal-ping"
    if any(word in text for word in ("fizzle", "miss a note")):
        return "builtin:soft-tick"
    if any(word in text for word in ("resist", "interrupt", "failed")):
        return "builtin:rune-pulse"
    if any(word in text for word in ("spawn", "respawn", "active")):
        return "builtin:spawn-horn"
    return "builtin:warden-bell"


def _gtt_value(value):
    value = re.sub(r"[\x00-\x1f]+", " ", str(value or "")).strip()
    return "" if re.sub(r"\s+", "", value).casefold() == "blank" else value


def _gtt_fields(block):
    fields = {}
    for part in str(block or "").replace("\r", " ").replace("\n", " ").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = re.sub(r"\s+", "", key).casefold()
        if key:
            fields[key] = _gtt_value(value)
    return fields


def _gtt_restart(value):
    folded = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if any(word in folded for word in ("always", "new timer", "additional")):
        return "new"
    if any(word in folded for word in ("ignore", "do not", "keep")):
        return "keep"
    return "restart"


def _read_gtt(path):
    try:
        package = Path(path)
        if not package.is_file():
            raise GinaImportError("The GTT file does not exist.")
        if package.stat().st_size > MAX_XML_BYTES:
            raise GinaImportError("The GTT file exceeds the 8 MB safety limit.")
        content = package.read_bytes()
    except OSError as error:
        raise GinaImportError(f"The GTT file could not be opened: {error}") from error
    encodings = (
        ("utf-16", "utf-8-sig", "cp1252")
        if content.startswith((b"\xff\xfe", b"\xfe\xff")) else
        ("utf-8-sig", "cp1252"))
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GinaImportError("The GTT text encoding could not be read.")


def _import_gtt(path):
    """Import the legacy GamTextTriggers key/value exchange format."""
    text = _read_gtt(path)
    starts = list(re.finditer(r"(?im)(?=^\s*Trigger\s*=)", text))
    if not starts:
        raise GinaImportError("The GTT file contains no Trigger= records.")
    imported = []
    warnings = []
    used_names = set()
    pack_name = _safe_name(Path(path).stem, "GTT")
    for index, start in enumerate(starts):
        if len(imported) >= MAX_TRIGGERS:
            raise GinaImportError(
                f"The file exceeds the {MAX_TRIGGERS}-trigger limit.")
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        fields = _gtt_fields(text[start.start():end])
        pattern = fields.get("trigger", "")
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
            _warning(warnings, "", "skipped-entry",
                     f"GTT entry {index + 1} skipped: missing or overlong match text.")
            continue
        timer_enabled = _truth(fields.get("timer"))
        seconds = (
            max(0, _integer(fields.get("hours"))) * 3600 +
            max(0, _integer(fields.get("minutes"))) * 60 +
            max(0, _integer(fields.get("seconds"))))
        seconds = min(seconds, 31_536_000)
        timer_name = fields.get("timertext", "")
        raw_name = timer_name or fields.get("displaytext", "") or pattern
        base_name = _safe_name(raw_name, f"Trigger {len(imported) + 1}")
        name = base_name
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base_name[:108]} · {suffix}"
            suffix += 1
        used_names.add(name.casefold())
        show_text = any(_truth(fields.get(key)) for key in (
            "display", "showtext", "showline"))
        alert_text = fields.get("displaytext", "") if show_text else ""
        has_audio = any(_truth(fields.get(key)) for key in (
            "sound", "playsound"))
        play_tts = _truth(fields.get("playtts"))
        ending_enabled = _truth(fields.get("completiondisplay"))
        end_early = _truth(fields.get("endearly"))
        color = normalize_trigger_color(fields.get("textcolour", ""))
        trigger = CustomTrigger(
            name=name,
            text=pattern,
            time=_duration(seconds if timer_enabled else 0),
            sound_path=(
                _gallery_sound_from_text(" ".join((
                    name, pattern, fields.get("soundlink", ""))))
                if has_audio else ""),
            alert_text=_safe_name(alert_text, "") if alert_text else "",
            enabled=False,
            regex=False,
            source=f"Imported GTT · {pack_name}",
            category="Imported GTT",
            overlay_id="timers" if timer_enabled and seconds else "alerts",
            restart_behavior=_gtt_restart(fields.get("behaviour")),
            end_text=(fields.get("endearlytext", "") if end_early else ""),
            comments=fields.get("comment", ""),
            timer_type="countdown" if timer_enabled and seconds else "none",
            timer_name=timer_name,
            timer_ended_alert=(
                fields.get("completiontext", "") if ending_enabled else ""),
            tts_text=(fields.get("ttstext", "") if play_tts else ""),
            end_patterns=([{
                "text": fields.get("endearlytext", ""), "regex": False}]
                if end_early and fields.get("endearlytext") else []),
            text_color=color,
        )
        known = {
            "trigger", "timer", "hours", "minutes", "seconds", "timertext",
            "displaytext", "display", "showtext", "showline", "sound",
            "playsound", "playtts", "ttstext", "completiondisplay",
            "completiontext", "endearly", "endearlytext", "textcolour",
            "soundlink", "behaviour", "comment",
        }
        unsupported = sorted(key for key, value in fields.items()
                             if key not in known and value)
        if unsupported:
            _warning(warnings, name, "unsupported-settings",
                     f"GTT settings not imported: {', '.join(unsupported[:20])}.")
        if has_audio:
            _warning(warnings, name, "external-path",
                     "GTT external sound reference is not opened; a Vantage "
                     "gallery sound is substituted.")
        if has_audio and play_tts:
            _warning(warnings, name, "combined-audio",
                     "Sound and Voice together are not supported: Vantage uses "
                     "one route per phase. Sound takes priority; speech is retained for editing.")
        _validate_patterns(trigger, warnings)
        imported.append(trigger)
    if not imported:
        raise GinaImportError("The GTT file contains no compatible triggers.")
    return GinaImportBatch(imported, warnings=warnings,
                           format_name="GamTextTriggers GTT")


def _read_package(path):
    try:
        return _read_package_content(path)
    except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as error:
        raise GinaImportError(f"The trigger package could not be opened: {error}") from error


def _read_package_content(path):
    package = Path(path)
    if not package.is_file():
        raise GinaImportError("The package does not exist.")
    if package.stat().st_size > MAX_PACKAGE_BYTES:
        raise GinaImportError("The package exceeds the 12 MB safety limit.")
    if package.suffix.casefold() in {".xml"}:
        content = package.read_bytes()
        media = {}
    else:
        try:
            with zipfile.ZipFile(package) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ENTRIES:
                    raise GinaImportError("The package contains too many files.")
                candidates = [entry for entry in entries
                              if Path(entry.filename).name.casefold() == "sharedata.xml"]
                if not candidates:
                    candidates = [entry for entry in entries
                                  if entry.filename.casefold().endswith(".xml")]
                if not candidates:
                    raise GinaImportError("ShareData.xml was not found in the package.")
                entry = candidates[0]
                if entry.file_size > MAX_XML_BYTES:
                    raise GinaImportError("The internal XML exceeds the 8 MB safety limit.")
                if entry.compress_size and entry.file_size / entry.compress_size > 200:
                    raise GinaImportError("The package uses an unsafe compression ratio.")
                content = archive.read(entry)
                total_size = sum(item.file_size for item in entries)
                if total_size > MAX_UNPACKED_BYTES:
                    raise GinaImportError(
                        "The package exceeds the 24 MB unpacked safety limit.")
                media = {}
                for item in entries:
                    if item is entry or item.is_dir():
                        continue
                    if Path(item.filename).suffix.casefold() == ".xml":
                        continue
                    if item.file_size > MAX_MEDIA_BYTES:
                        continue
                    if (item.compress_size and
                            item.file_size / item.compress_size > 200):
                        continue
                    try:
                        file_id = int(item.comment.decode("ascii").strip())
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if file_id <= 0 or file_id in media:
                        continue
                    payload = archive.read(item)
                    if not (len(payload) >= 12 and payload[:4] == b"RIFF" and
                            payload[8:12] == b"WAVE"):
                        continue
                    media[file_id] = (Path(item.filename).name, payload)
        except zipfile.BadZipFile as error:
            raise GinaImportError("The file is not a valid trigger package.") from error
    if len(content) > MAX_XML_BYTES:
        raise GinaImportError("The XML exceeds the 8 MB safety limit.")
    # Scan the entire bounded document, including UTF-16/32 declaration bytes.
    upper = content.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise GinaImportError("The XML contains unsupported declarations.")
    return content, media


def _iter_triggers(root):
    """Yield each trigger with its enclosing GINA library group path."""
    stack = [(root, (), 0)]
    visited = 0
    while stack:
        element, path, depth = stack.pop()
        visited += 1
        if depth > 64 or visited > 200_000:
            raise GinaImportError("The XML exceeds the safe nesting or element limit.")
        local = _local(element.tag)
        if local == "TriggerGroup":
            raw_name = _child_text(element, "Name")
            segment = re.sub(r"[/\\]+", " - ", _safe_name(raw_name, "Group"))
            path = path + (segment,)
            if len(path) > 16:
                raise GinaImportError("Trigger groups exceed the 16-level nesting limit.")
        if local == "Trigger":
            yield element, path
            continue
        stack.extend((child, path, depth + 1) for child in reversed(element))


def _import_category(element, group_path):
    category = (
        _child_text(element, "Category") or
        _child_text(element, "SuggestedCategory"))
    parts = [part for part in group_path if part]
    if category and (not parts or parts[-1].casefold() != category.casefold()):
        parts.append(re.sub(r"[/\\]+", " - ", _safe_name(category, "Default")))
    return "/".join(parts) or _safe_name(category, "Default")


def import_gina_package(path):
    """Return disabled trigger copies from GINA/GamTextTriggers exports."""
    if Path(path).suffix.casefold() == ".gtt":
        return _import_gtt(path)
    if Path(path).suffix.casefold() == ".json":
        return _import_vantage_package(path)
    try:
        content, media = _read_package(path)
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise GinaImportError("The package XML could not be read.") from error

    imported = []
    warnings = []
    used_names = set()
    pack_name = _safe_name(Path(path).stem, "Trigger pack")
    for element, group_path in _iter_triggers(root):
        if len(imported) >= MAX_TRIGGERS:
            raise GinaImportError(
                f"The package exceeds the {MAX_TRIGGERS}-trigger limit.")
        pattern = _child_text(element, "TriggerText")
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
            _warning(warnings, "", "skipped-entry",
                     f"{_child_text(element, 'Name') or 'Unnamed trigger'} skipped: "
                     "missing or overlong match text.")
            continue
        raw_name = _child_text(element, "Name") or _child_text(element, "TimerName")
        category = _import_category(element, group_path)
        base_name = _safe_name(
            raw_name, f"Trigger {len(imported) + 1}")
        name = base_name
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base_name[:108]} · {suffix}"
            suffix += 1
        used_names.add(name.casefold())

        milliseconds = _integer(
            _child_text(element, "TimerMillisecondDuration", "0"))
        timer_seconds = (
            max(0, milliseconds // 1000) if milliseconds else
            max(0, _integer(_child_text(element, "TimerDuration", "0"))))
        timer_mode = _timer_type(
            _child_text(element, "TimerType"), timer_seconds)
        timer_name = _child_text(element, "TimerName")
        display = ""
        if _truth(_child_text(element, "UseText")):
            display = _child_text(element, "DisplayText")
        has_audio = _truth(_child_text(element, "PlayMediaFile"))
        early_enders = _early_enders(element)
        ending = _subtrigger(element, "TimerEndingTrigger")
        ended = _subtrigger(element, "TimerEndedTrigger")
        counter_reset = (
            _integer(_child_text(element, "CounterResetDuration"))
            if _truth(_child_text(element, "UseCounterResetTimer")) else 0)
        use_ending = _truth(_child_text(element, "UseTimerEnding"))
        use_ended = _truth(_child_text(element, "UseTimerEnded"))
        trigger = CustomTrigger(
            name=name,
            text=pattern,
            time=_duration(timer_seconds),
            zone="",
            sound_path=_gallery_sound(element, has_audio),
            alert_text=_safe_name(display, "") if display else "",
            enabled=False,
            regex=_truth(_child_text(element, "EnableRegex")),
            source=f"Imported pack · {pack_name}",
            category=category,
            overlay_id=("timers" if timer_mode != "none"
                        else "alerts"),
            restart_behavior=_restart_behavior(element),
            end_text=(early_enders[0]["text"] if early_enders else ""),
            comments=_child_text(element, "Comments"),
            timer_type=timer_mode,
            timer_name=_safe_name(timer_name, "") if timer_name else "",
            restart_based_on_timer_name=_truth(
                _child_text(element, "RestartBasedOnTimerName")),
            timer_visible_seconds=_integer(
                _child_text(element, "TimerVisibleDuration")),
            timer_ending_seconds=(
                _integer(_child_text(element, "TimerEndingTime"))
                if use_ending else 0),
            timer_ending_alert=ending["alert"] if use_ending else "",
            timer_ending_sound=ending["sound"] if use_ending else "",
            timer_ended_alert=(
                ended["alert"] if use_ended else ""),
            timer_ended_sound=(
                ended["sound"] if use_ended else ""),
            counter_reset_seconds=counter_reset,
            clipboard_text=(
                _child_text(element, "ClipboardText")
                if _truth(_child_text(element, "CopyToClipboard")) else ""),
            end_patterns=early_enders,
            tts_text=(
                _child_text(element, "TextToVoiceText")
                if _truth(_child_text(element, "UseTextToVoice")) else ""),
            interrupt_speech=_truth(
                _child_text(element, "InterruptSpeech")),
            timer_ending_tts=ending["tts"] if use_ending else "",
            timer_ending_interrupt=ending["interrupt"] if use_ending else False,
            timer_ended_tts=ended["tts"] if use_ended else "",
            timer_ended_interrupt=ended["interrupt"] if use_ended else False,
        )
        refs = {}
        main_media_id = _media_id(element) if has_audio else None
        if main_media_id:
            refs["sound_path"] = main_media_id
        if use_ending and ending["media_id"]:
            refs["timer_ending_sound"] = ending["media_id"]
        if use_ended and ended["media_id"]:
            refs["timer_ended_sound"] = ended["media_id"]
        if refs:
            trigger._gina_media_refs = refs
        _gina_compatibility(element, trigger, media, warnings)
        imported.append(trigger)
    if not imported:
        raise GinaImportError("The package contains no compatible triggers.")
    for group in root.iter():
        if _local(group.tag) != "TriggerGroup":
            continue
        options = sorted({_local(child.tag) for child in group
                          if _local(child.tag) not in {
                              "Name", "Triggers", "TriggerGroups", "TriggerGroup", "Id", "ID"}
                          and ((child.text or "").strip() or len(child))})
        if options:
            _warning(warnings, "", "group-options",
                     f"Group {_child_text(group, 'Name') or 'Unnamed'}: only hierarchy "
                     f"is imported; settings not imported: {', '.join(options[:20])}.")
    return GinaImportBatch(imported, media, warnings)


def _is_wave(content):
    return (12 <= len(content) <= MAX_MEDIA_BYTES and content[:4] == b"RIFF"
            and content[8:12] == b"WAVE")


def _bounded_group_path(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError("group path is missing or exceeds 1024 characters")
    parts = [part.strip() for part in value.replace("\\", "/").split("/") if part.strip()]
    if len(parts) > 16 or any(len(part) > 120 for part in parts):
        raise ValueError("group path exceeds 16 levels or 120 characters per level")
    return "/".join(parts) or "Default"


def _bounded_native_groups(raw, warnings):
    """Validate before ancestor expansion; keep only the known group schema."""
    if not isinstance(raw, dict) or len(raw) > MAX_ENTRIES:
        _warning(warnings, "", "group-metadata", "Group metadata skipped: unsupported type or more than 256 groups.")
        return {}
    result, metadata_count = {}, 0
    for key, definition in raw.items():
        try:
            path = _bounded_group_path(key)
            if not isinstance(definition, (bool, dict)):
                raise ValueError("unsupported group definition")
            if isinstance(definition, dict):
                definition = {field: definition[field] for field in (
                    "enabled", "profiles", "style", "profile_styles", "order") if field in definition}
                order = definition.get("order", 0)
                if (not isinstance(order, (int, float)) or not math.isfinite(order)
                        or not 0 <= order <= 1_000_000):
                    raise ValueError("invalid group order")
                if "enabled" in definition and type(definition["enabled"]) is not bool:
                    raise ValueError("invalid group enabled state")
                for field in ("profiles", "profile_styles"):
                    entries = definition.get(field, {})
                    if not isinstance(entries, dict) or len(entries) > MAX_ENTRIES:
                        raise ValueError("too many character overrides")
                    if any(not isinstance(name, str) or len(name) > 160 for name in entries):
                        raise ValueError("invalid character override name")
                    metadata_count += len(entries)
                if metadata_count > 4096:
                    raise ValueError("character metadata safety limit exceeded")
                if any(type(enabled) is not bool for enabled in definition.get("profiles", {}).values()):
                    raise ValueError("invalid character enabled state")
            result[path] = definition
        except (ValueError, TypeError, OverflowError) as error:
            _warning(warnings, "", "group-metadata", f"Group metadata skipped: {error}.")
    return result


def serialize_vantage_package(triggers, groups=None):
    """Build a bounded native JSON exchange; never follow outside audio paths.

    Only selected rules and referenced, profile-owned portable WAVs are shared.
    This is not a GINA-native export or a GimaLink service.
    """
    selected = list(triggers)
    if not selected or len(selected) > MAX_TRIGGERS:
        raise GinaImportError("Choose between 1 and 1500 triggers to export.")
    rows, media, warnings, total = [], {}, [], 0
    paths = set()
    for original in selected:
        trigger = CustomTrigger(*original.to_list())
        try:
            trigger.category = _bounded_group_path(trigger.category)
        except ValueError as error:
            raise GinaImportError(f"Cannot share {trigger.name}: {error}.") from error
        paths.update(group_ancestors(trigger.category))
        if len(paths) > MAX_ENTRIES:
            raise GinaImportError("Selected groups exceed the 256-group safety limit.")
        refs = {}
        for field in ("sound_path", "timer_ending_sound", "timer_ended_sound"):
            value = str(getattr(trigger, field) or "")
            if not value or value.startswith("builtin:"):
                continue
            if value.startswith("portable:"):
                try:
                    source = resolve_portable_path(value)
                    content = (source.read_bytes() if source.is_file()
                               and source.stat().st_size <= MAX_MEDIA_BYTES else b"")
                except OSError:
                    content = b""
                if content:
                    if _is_wave(content):
                        media_id = hashlib.sha256(content).hexdigest()
                        if media_id not in media:
                            if len(media) >= MAX_ENTRIES - 1:
                                raise GinaImportError("Selected WAVs exceed the 255-file safety limit.")
                            total += len(content)
                            if total > MAX_UNPACKED_BYTES:
                                raise GinaImportError("Selected WAV data exceeds the 24 MB safety limit.")
                            media[media_id] = {
                                "name": source.name,
                                "base64": base64.b64encode(content).decode("ascii"),
                            }
                        refs[field] = media_id
                        setattr(trigger, field, "")
                        continue
            setattr(trigger, field, "")
            _warning(warnings, trigger.name, "unshared-audio",
                     f"{field}: unavailable or outside-profile audio was not shared.")
        # Keep full-line-only packs readable by earlier Companion versions.
        # Contains text needs schema 2 so old readers cannot silently narrow it.
        values = trigger.to_list()
        if trigger.match_mode == "full":
            values = values[:49]
        rows.append({"values": values, "media": refs})
    safe_groups = normalize_trigger_groups({
        "trigger_groups": _bounded_native_groups(groups or {}, warnings),
        "custom_timers": [row["values"] for row in rows]})
    package_version = 2 if any(len(row["values"]) > 49 for row in rows) else 1
    if package_version == 2:
        _warning(warnings, "", "minimum-version",
                 "Contains text matching requires Vantage Companion 1.44.127 or newer.")
    payload = {
        "format": "vantage-trigger-pack", "version": package_version,
        "triggers": rows, "media": media,
        "groups": {key: value for key, value in safe_groups.items() if key in paths},
    }
    encoded = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    if len(encoded) > MAX_PACKAGE_BYTES:
        raise GinaImportError("The native JSON pack exceeds the 12 MB safety limit.")
    return encoded, warnings


def export_vantage_package(path, triggers, groups=None):
    content, warnings = serialize_vantage_package(triggers, groups)
    try:
        Path(path).write_bytes(content)
    except OSError as error:
        raise GinaImportError("The native trigger pack could not be saved.") from error
    return warnings


def _import_vantage_package(path):
    try:
        package = Path(path)
        if not package.is_file() or package.stat().st_size > MAX_PACKAGE_BYTES:
            raise GinaImportError("Native JSON pack is missing or exceeds the 12 MB safety limit.")
        content = package.read_bytes()
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise GinaImportError("The native JSON pack could not be read.") from error
    return import_vantage_package_bytes(content, source_name=package.stem)


def import_vantage_package_bytes(content, *, source_name="Shared pack"):
    """Stage native data in memory; callers review selection before commit."""
    if not isinstance(content, bytes) or len(content) > MAX_PACKAGE_BYTES:
        raise GinaImportError("Native JSON pack exceeds the 12 MB safety limit.")
    try:
        data = json.loads(content)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise GinaImportError("The native JSON pack could not be read.") from error
    if (not isinstance(data, dict) or data.get("format") != "vantage-trigger-pack"
            or data.get("version") not in (1, 2)):
        raise GinaImportError("This is not a supported Vantage native trigger pack.")
    rows, raw_media = data.get("triggers"), data.get("media", {})
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_TRIGGERS:
        raise GinaImportError("Native packs must contain between 1 and 1500 trigger records.")
    if not isinstance(raw_media, dict) or len(raw_media) > MAX_ENTRIES:
        raise GinaImportError("The native pack contains too many audio records.")
    media, warnings, total = {}, [], 0
    for key, entry in raw_media.items():
        try:
            if not isinstance(entry, dict):
                raise ValueError("invalid audio record")
            encoded = entry.get("base64", "")
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_MEDIA_BYTES + 2) // 3):
                raise ValueError("audio record too large")
            content = base64.b64decode(encoded, validate=True)
            if not _is_wave(content):
                raise ValueError("not a valid WAV header")
            total += len(content)
            if total > MAX_UNPACKED_BYTES:
                raise GinaImportError("Native WAV data exceeds the 24 MB safety limit.")
            media[str(key)] = (Path(str(entry.get("name") or "shared.wav")).name, content)
        except (ValueError, TypeError) as error:
            _warning(warnings, "", "invalid-audio", f"Audio record {str(key)[:80]} skipped: {error}.")
    imported, names, paths = [], set(), set()
    for index, row in enumerate(rows):
        try:
            values = row.get("values") if isinstance(row, dict) else None
            if (not isinstance(values, list) or not 3 <= len(values) <= 50
                    or not all(isinstance(value, str) for value in values[:3])
                    or not values[1] or len(values[1]) > MAX_PATTERN_LENGTH):
                raise ValueError("missing or unsupported trigger values")
            string_fields = {
                0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15,
                18, 19, 20, 21, 23, 25, 27, 29, 31, 32, 34, 35, 38,
                39, 42, 43, 46, 49,
            }
            if any(index < len(values) and
                   (not isinstance(values[index], str) or len(values[index]) > 8192)
                   for index in string_fields):
                raise ValueError("unsupported text field")
            if any(index < len(values) and type(values[index]) is not bool
                   for index in {6, 7, 26, 28, 30, 33, 48}):
                raise ValueError("native enabled/regex/interrupt/mute values must be Boolean")
            if len(values) > 24 and (
                    not isinstance(values[24], list) or len(values[24]) > MAX_ENTRIES
                    or any(not isinstance(entry, dict) or
                           not isinstance(entry.get("text"), str) or
                           len(entry["text"]) > MAX_PATTERN_LENGTH
                           or type(entry.get("regex", False)) is not bool
                           for entry in values[24])):
                raise ValueError("unsupported early-ending patterns")
            if any(isinstance(value, (dict, list)) for index, value in enumerate(values)
                   if index != 24):
                raise ValueError("unsupported nested trigger value")
            if any(isinstance(value, float) and not math.isfinite(value) for value in values):
                raise ValueError("nonfinite numeric trigger value")
            if len(values) > 49:
                if values[49] not in ("full", "contains"):
                    raise ValueError("unsupported text matching scope")
                if values[49] == "contains" and data["version"] != 2:
                    raise ValueError("Contains text requires native pack schema 2")
            # No nested executable data; text/actions are interpreted solely
            # through the existing CustomTrigger schema and bounded package.
            trigger = CustomTrigger(*values)
            trigger.category = _bounded_group_path(trigger.category)
            candidate_paths = paths | set(group_ancestors(trigger.category))
            if len(candidate_paths) > MAX_ENTRIES:
                raise ValueError("group hierarchy exceeds the 256-group safety limit")
            paths = candidate_paths
            base = _safe_name(trigger.name, f"Trigger {index + 1}")
            name, suffix = base, 2
            while name.casefold() in names:
                name, suffix = f"{base[:108]} · {suffix}", suffix + 1
            trigger.name, trigger.enabled = name, False
            if len(values) > 10 and trigger.overlay_id != values[10]:
                _warning(warnings, name, "overlay-remapped",
                         f"Overlay {values[10]} is not defined locally; recipient default "
                         f"{trigger.overlay_id} is substituted. Review the visual route before enabling.")
            trigger.source = f"Imported Vantage pack · {_safe_name(source_name, 'Native pack')}"
            names.add(name.casefold())
            refs = row.get("media", {})
            refs = refs if isinstance(refs, dict) else {}
            valid_refs = {}
            for field in ("sound_path", "timer_ending_sound", "timer_ended_sound"):
                value = str(getattr(trigger, field) or "")
                media_id = str(refs.get(field) or "")
                if media_id and media_id in media:
                    valid_refs[field] = media_id
                    setattr(trigger, field, "")
                elif media_id or (value and not value.startswith("builtin:")):
                    setattr(trigger, field, "")
                    _warning(warnings, name, "missing-audio",
                             f"{field}: missing packaged WAV or outside file reference ignored; "
                             "review this phase's audio delivery.")
            trigger._gina_media_refs = valid_refs
            _validate_patterns(trigger, warnings)
            imported.append(trigger)
        except (TypeError, ValueError, OverflowError) as error:
            _warning(warnings, "", "skipped-entry", f"Native entry {index + 1} skipped: {error}.")
    if not imported:
        details = "\n".join(entry["message"] for entry in warnings[:5])
        raise GinaImportError("The native pack contains no compatible trigger records." +
                              ("\n" + details if details else ""))
    groups = _bounded_native_groups(data.get("groups", {}), warnings)
    known_paths = set(paths)
    for path in list(groups):
        candidate_paths = known_paths | set(group_ancestors(path))
        if len(candidate_paths) > MAX_ENTRIES:
            groups.pop(path)
            _warning(warnings, "", "group-metadata", "Group metadata skipped: hierarchy exceeds 256 groups.")
        else:
            known_paths = candidate_paths
    groups = normalize_trigger_groups({
        "trigger_groups": groups, "custom_timers": [trigger.to_list() for trigger in imported]})
    return GinaImportBatch(imported, media, warnings, "Vantage native JSON pack", groups)


def serialize_gina_package(triggers, groups=None):
    """Export the supported data-only GINA XML subset with explicit losses.

    Archive WAV comments are the numeric IDs used by MediaFileId. This is not
    a GimaLink upload, nor a claim of complete GINA runtime/service parity.
    """
    native, warnings = serialize_vantage_package(triggers, groups)
    data = json.loads(native)
    warnings = list(warnings)
    _warning(warnings, "", "gina-subset",
             "GINA export is a compatibility subset. Review in GINA before use; "
             "Vantage-specific configuration is not portable. Native JSON preserves it.")
    root = ET.Element("SharedData")
    root_groups = ET.SubElement(root, "TriggerGroups")
    group_nodes, next_media, media_ids = {}, 1, {}
    for key in data["media"]:
        media_ids[key], next_media = next_media, next_media + 1

    def put(parent, key, value):
        ET.SubElement(parent, key).text = (
            "True" if value is True else "False" if value is False else str(value))

    def group_node(path):
        parent = root_groups
        for ancestor in group_ancestors(path):
            if ancestor not in group_nodes:
                node = ET.SubElement(parent, "TriggerGroup")
                put(node, "Name", ancestor.rsplit("/", 1)[-1])
                group_nodes[ancestor] = node
            node = group_nodes[ancestor]
            parent = node.find("TriggerGroups")
            if parent is None:
                parent = ET.SubElement(node, "TriggerGroups")
        node = group_nodes[path]
        records = node.find("Triggers")
        return records if records is not None else ET.SubElement(node, "Triggers")

    def audio_stage(node, trigger, refs, stage):
        prefix = "" if stage == "basic" else "timer_ending_" if stage == "ending" else "timer_ended_"
        text = trigger.alert_text if stage == "basic" else getattr(trigger, prefix + "alert")
        speech = trigger.tts_text if stage == "basic" else getattr(trigger, prefix + "tts")
        interrupt = trigger.interrupt_speech if stage == "basic" else getattr(trigger, prefix + "interrupt")
        sound_field = "sound_path" if stage == "basic" else prefix + "sound"
        mode = trigger.audio_delivery(stage)
        media_id = media_ids.get(refs.get(sound_field))
        put(node, "UseText", bool(text))
        put(node, "DisplayText", text)
        put(node, "PlayMediaFile", mode == "sound" and bool(media_id))
        if media_id:
            put(node, "MediaFileId", media_id)
        put(node, "UseTextToVoice", mode == "tts" and bool(speech))
        put(node, "TextToVoiceText", speech)
        put(node, "InterruptSpeech", interrupt)
        original_sound = str(getattr(trigger, sound_field) or "")
        if mode == "sound" and not media_id:
            _warning(warnings, trigger.name, "gina-audio-loss",
                     f"{stage}: gallery or unavailable audio cannot be embedded in GINA; "
                     "this phase exports without Sound. Native JSON retains gallery choices.")
        if original_sound and mode != "sound" or speech and mode != "tts":
            _warning(warnings, trigger.name, "gina-inactive-audio",
                     f"{stage}: inactive saved audio choices are not active in the GINA export.")

    for row in data["triggers"]:
        trigger = CustomTrigger(*row["values"])
        # Native serialization clears path fields; refs retain selected WAVs.
        for field, media_key in row["media"].items():
            setattr(trigger, field, "packaged:" + media_key)
        node = ET.SubElement(group_node(trigger.category), "Trigger")
        for key, value in (
                ("Name", trigger.name), ("TriggerText", trigger.text),
                ("EnableRegex", trigger.regex), ("Comments", trigger.comments),
                ("TimerType", {"none": "NoTimer", "countdown": "Timer",
                               "stopwatch": "Stopwatch", "repeating": "RepeatingTimer"}[trigger.timer_type]),
                ("TimerName", trigger.timer_name),
                ("TimerMillisecondDuration", int(text_time_to_seconds(trigger.time)) * 1000),
                ("TimerStartBehavior", {"restart": "RestartTimer", "keep": "IgnoreIfRunning",
                                        "new": "StartNewTimer"}[trigger.restart_behavior]),
                ("RestartBasedOnTimerName", trigger.restart_based_on_timer_name),
                ("TimerVisibleDuration", trigger.timer_visible_seconds),
                ("UseCounterResetTimer", bool(trigger.counter_reset_seconds)),
                ("CounterResetDuration", trigger.counter_reset_seconds),
                ("CopyToClipboard", bool(trigger.clipboard_text)),
                ("ClipboardText", trigger.clipboard_text)):
            put(node, key, value)
        audio_stage(node, trigger, row["media"], "basic")
        for stage in ("ending", "ended"):
            enabled = bool(getattr(trigger, "timer_" + stage + "_alert") or
                           getattr(trigger, "timer_" + stage + "_sound") or
                           getattr(trigger, "timer_" + stage + "_tts"))
            put(node, "UseTimer" + stage.capitalize(), enabled)
            if stage == "ending":
                put(node, "TimerEndingTime", trigger.timer_ending_seconds)
            audio_stage(ET.SubElement(node, "Timer" + stage.capitalize() + "Trigger"),
                        trigger, row["media"], stage)
        enders = ET.SubElement(node, "TimerEarlyEnders")
        for entry in trigger.end_patterns:
            ender = ET.SubElement(enders, "EarlyEnder")
            put(ender, "EarlyEndText", entry["text"])
            put(ender, "EnableRegex", bool(entry.get("regex")))
        losses = []
        if trigger.match_mode == "contains" and not trigger.regex:
            losses.append("Vantage literal Contains text matching scope; use a native "
                          "JSON pack or share code to preserve it exactly")
        if trigger.profile or trigger.zone:
            losses.append("character/zone restrictions")
        if not trigger.enabled:
            losses.append("disabled state (GINA controls activation on import)")
        if trigger.match_filter or trigger.match_cooldown_seconds != 0.75:
            losses.append("match filter/repeat guard")
        if trigger.overlay_id or trigger.text_color:
            losses.append("overlay routing and color")
        if any(getattr(trigger, field) for field in (
                "tts_voice", "tts_pitch", "timer_ending_voice", "timer_ending_pitch",
                "timer_ended_voice", "timer_ended_pitch")) or any(
                getattr(trigger, field) != 100 for field in (
                    "tts_volume", "timer_ending_volume", "timer_ended_volume")):
            losses.append("Vantage voice/volume/pitch choices")
        if trigger.audio_muted:
            losses.append("saved muted audio choices")
        if trigger.regex or "{ts}" in trigger.text.casefold():
            losses.append("Python regex/token behavior requires GINA review")
        if losses:
            _warning(warnings, trigger.name, "gina-settings-loss", "Not preserved: " + "; ".join(losses) + ".")
    if data["groups"]:
        _warning(warnings, "", "gina-group-loss",
                 "Only group hierarchy is exported. Group enabled states, profile overrides, "
                 "colors, and ordering settings are not transferred.")
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if len(xml) > MAX_XML_BYTES:
        raise GinaImportError("GINA XML exceeds the 8 MB safety limit.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ShareData.xml", xml)
        for key, entry in data["media"].items():
            info = zipfile.ZipInfo(f"Audio/{media_ids[key]}.wav")
            info.comment = str(media_ids[key]).encode("ascii")
            archive.writestr(info, base64.b64decode(entry["base64"]))
    content = output.getvalue()
    if len(content) > MAX_PACKAGE_BYTES:
        raise GinaImportError("GINA package exceeds the 12 MB safety limit.")
    return content, warnings


def export_gina_package(path, triggers, groups=None):
    content, warnings = serialize_gina_package(triggers, groups)
    try:
        Path(path).write_bytes(content)
    except OSError as error:
        raise GinaImportError("The GINA package could not be saved.") from error
    return warnings
