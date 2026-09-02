"""Safe, data-only import of GINA trigger packages."""

from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from vantage.parsers.spells import CustomTrigger
from vantage.helpers.trigger_groups import normalize_trigger_color
from vantage.helpers.portable import store_portable_bytes


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

    def __init__(self, triggers=(), media=None):
        super().__init__(triggers)
        self._media = dict(media or {})

    def has_embedded_audio(self, trigger):
        refs = getattr(trigger, "_gina_media_refs", {})
        return any(media_id in self._media for media_id in refs.values())

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
    except (TypeError, ValueError):
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
    except (TypeError, ValueError):
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
    package = Path(path)
    if not package.is_file():
        raise GinaImportError("The GTT file does not exist.")
    if package.stat().st_size > MAX_XML_BYTES:
        raise GinaImportError("The GTT file exceeds the 8 MB safety limit.")
    content = package.read_bytes()
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
        imported.append(CustomTrigger(
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
        ))
    if not imported:
        raise GinaImportError("The GTT file contains no compatible triggers.")
    return GinaImportBatch(imported)


def _read_package(path):
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
    upper = content[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise GinaImportError("The XML contains unsupported declarations.")
    return content, media


def _iter_triggers(root):
    """Yield each trigger with its enclosing GINA library group path."""
    seen = set()

    def visit(element, path=()):
        local = _local(element.tag)
        if local == "TriggerGroup":
            raw_name = _child_text(element, "Name")
            segment = re.sub(r"[/\\]+", " - ", _safe_name(raw_name, "Group"))
            path = path + (segment,)
        if local == "Trigger":
            seen.add(id(element))
            yield element, path
            return
        for child in element:
            yield from visit(child, path)

    yield from visit(root)
    for element in root.iter():
        if _local(element.tag) == "Trigger" and id(element) not in seen:
            yield element, ()


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
    try:
        content, media = _read_package(path)
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise GinaImportError("The package XML could not be read.") from error

    imported = []
    used_names = set()
    pack_name = _safe_name(Path(path).stem, "Trigger pack")
    for element, group_path in _iter_triggers(root):
        if len(imported) >= MAX_TRIGGERS:
            raise GinaImportError(
                f"The package exceeds the {MAX_TRIGGERS}-trigger limit.")
        pattern = _child_text(element, "TriggerText")
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
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
        imported.append(trigger)
    if not imported:
        raise GinaImportError("The package contains no compatible triggers.")
    return GinaImportBatch(imported, media)
