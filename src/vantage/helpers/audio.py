"""Volume-aware alert audio and the built-in Vantage sound gallery."""

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication

try:
    from PySide6.QtTextToSpeech import QTextToSpeech
except ImportError:  # pragma: no cover - optional on minimal Qt builds
    QTextToSpeech = None

from vantage.helpers import config, resource_path
from vantage.helpers.portable import resolve_portable_path


SOUND_GALLERY = (
    ("Windows-style Chime", "builtin:warden-bell", "Clean notification"),
    ("Ready", "builtin:spawn-horn", "Soft ascending chime"),
    ("Soft Notify", "builtin:crystal-ping", "Quiet buff warning"),
    ("Alert", "builtin:rune-pulse", "Resist or interruption"),
    ("Subtle", "builtin:soft-tick", "Low-priority notice"),
    ("Priority", "builtin:danger-double", "Two-note urgent alert"),
    ("Amber Chime", "builtin:amber-chime", "Warm two-note bell"),
    ("Arcane Bloom", "builtin:arcane-bloom", "Rising magical triad"),
    ("Camp Bell", "builtin:camp-bell", "Rounded camp reminder"),
    ("Copper Click", "builtin:copper-click", "Short crisp marker"),
    ("Dusk Echo", "builtin:dusk-echo", "Low gentle echo"),
    ("Emerald Step", "builtin:emerald-step", "Quick ascending steps"),
    ("Frost Glint", "builtin:frost-glint", "Bright high sparkle"),
    ("Gentle Knock", "builtin:gentle-knock", "Soft double knock"),
    ("Moon Drop", "builtin:moon-drop", "Smooth descending pair"),
    ("Portal Ping", "builtin:portal-ping", "Clear dimensional ping"),
    ("Silver Rise", "builtin:silver-rise", "Light ascending signal"),
    ("Soft Sonar", "builtin:sonar-soft", "Quiet spaced pulse"),
    ("Temple Note", "builtin:temple-note", "Calm harmonic bell"),
    ("Ward Fall", "builtin:ward-fall", "Descending warning"),
)
DEFAULT_SOUND = SOUND_GALLERY[0][1]
_BUILTIN_FILES = {
    "builtin:warden-bell": "warden_bell.wav",
    "builtin:spawn-horn": "spawn_horn.wav",
    "builtin:crystal-ping": "crystal_ping.wav",
    "builtin:rune-pulse": "rune_pulse.wav",
    "builtin:soft-tick": "soft_tick.wav",
    "builtin:danger-double": "danger_double.wav",
    "builtin:amber-chime": "amber_chime.wav",
    "builtin:arcane-bloom": "arcane_bloom.wav",
    "builtin:camp-bell": "camp_bell.wav",
    "builtin:copper-click": "copper_click.wav",
    "builtin:dusk-echo": "dusk_echo.wav",
    "builtin:emerald-step": "emerald_step.wav",
    "builtin:frost-glint": "frost_glint.wav",
    "builtin:gentle-knock": "gentle_knock.wav",
    "builtin:moon-drop": "moon_drop.wav",
    "builtin:portal-ping": "portal_ping.wav",
    "builtin:silver-rise": "silver_rise.wav",
    "builtin:sonar-soft": "sonar_soft.wav",
    "builtin:temple-note": "temple_note.wav",
    "builtin:ward-fall": "ward_fall.wav",
}

NOTIFICATION_SOUND_DEFAULTS = {
    "timer_default": "builtin:spawn-horn",
    "smart_timer": "builtin:spawn-horn",
    "raid_encounter": "builtin:warden-bell",
    "safety_alert": "builtin:danger-double",
    "death_loop": "builtin:danger-double",
    "market_sale": "builtin:crystal-ping",
    "spell_fading": "builtin:soft-tick",
    "spell_resisted": "builtin:rune-pulse",
    "spell_worn_off": "builtin:ward-fall",
}
_ACTIVE_EFFECTS = set()
_MUTED = False
_SPEECH = None
_DEFAULT_VOICE_NAME = ""
_SPEECH_PREWARM_PENDING = False
_SPEECH_PENDING = []
_SPEECH_ACTIVE = None
_SPEECH_BOUND_ENGINE = None
_SPEECH_STATE_SIGNAL = False
_SPEECH_GAP_PENDING = False
_SPEECH_EPOCH = 0
_SPEECH_REQUEST_ID = 0

# Automatic alerts share one local Windows voice.  Keep the pause perceptible
# without making combat feedback feel late, and cap only the waiting work: the
# phrase already being spoken is never sacrificed to make room.
_SPEECH_GAP_MS = 180
_SPEECH_MAX_PENDING = 8
_SPEECH_POLL_MS = 100


def _percent(value, default=100):
    """Return a defensive 0-100 percentage for live audio settings."""
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return int(default)


def master_volume():
    """Return the live global volume without changing the mute state."""
    return _percent(
        config.data.get("general", {}).get("master_volume", 100), 100)


def set_master_volume(volume):
    """Apply a global volume percentage to subsequent WAV and TTS alerts."""
    value = _percent(volume, 100)
    config.data.setdefault("general", {})["master_volume"] = value
    return value


def sound_choices():
    """Return immutable display labels and URIs for gallery controls."""
    return SOUND_GALLERY


def notification_sound(event_key):
    """Return the saved sound for one global notification route."""
    key = "smart_timer" if str(event_key) == "timer_default" else str(event_key)
    fallback = NOTIFICATION_SOUND_DEFAULTS.get(key, DEFAULT_SOUND)
    route = config.data.get("sounds", {}).get("routes", {}).get(key, {})
    if isinstance(route, dict) and "sound" in route:
        return str(route.get("sound", fallback) or "")
    return str(config.data.get("sounds", {}).get(event_key, fallback) or "")


def sound_display_name(value):
    value = str(value or "")
    if not value:
        return "No sound"
    if value.startswith("tts:"):
        return "Text-to-speech"
    for label, uri, _description in SOUND_GALLERY:
        if value == uri:
            return label
    if value.startswith("portable:"):
        return f"Custom · {Path(value).name}"
    return "Windows-style Chime"


def resolve_sound(value=""):
    """Resolve a gallery URI, copied WAV, or legacy file path."""
    value = str(value or DEFAULT_SOUND).strip()
    builtin = _BUILTIN_FILES.get(value)
    if builtin:
        return Path(resource_path(f"data/sounds/{builtin}"))
    candidate = resolve_portable_path(value)
    if candidate.is_file() and candidate.suffix.casefold() == ".wav":
        return candidate
    return Path(resource_path(
        f"data/sounds/{_BUILTIN_FILES[DEFAULT_SOUND]}"))


def set_sound_combo_value(combo, value=""):
    """Populate a QComboBox with the gallery and retain a custom WAV choice."""
    value = str(value or "").strip()
    combo.clear()
    combo.addItem("No sound", "")
    for label, uri, description in SOUND_GALLERY:
        combo.addItem(f"{label} · {description}", uri)
    index = combo.findData(value)
    if index < 0 and value:
        combo.addItem(sound_display_name(value), value)
        index = combo.count() - 1
    combo.setCurrentIndex(max(0, index))


def add_custom_sound_to_combo(combo, value):
    """Select a copied custom sound without discarding the built-in gallery."""
    if not value:
        return
    index = combo.findData(value)
    if index < 0:
        combo.addItem(sound_display_name(value), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)


def audio_muted():
    """Return the authoritative mute state and reconcile config reloads.

    A freshly reloaded configuration can become muted without passing through
    the Quick Bar callback.  Promote that persisted state into the live kill
    switch and silence anything already playing.  A live mute deliberately
    remains fail-closed until :func:`set_audio_muted(False)` is called.
    """
    global _MUTED
    configured = bool(
        config.data.get("general", {}).get("audio_muted", False))
    if configured and not _MUTED:
        _MUTED = True
        if _ACTIVE_EFFECTS or _SPEECH is not None:
            stop_all_audio()
    return bool(_MUTED or configured)


def set_audio_muted(muted):
    """Globally mute new alerts and immediately stop active Vantage audio."""
    global _MUTED
    was_muted = bool(_MUTED or config.data.get(
        "general", {}).get("audio_muted", False))
    _MUTED = bool(muted)
    # Update the in-memory preference in the same operation.  Previously the
    # application wrote config on the following line, leaving two mute states
    # that could temporarily disagree during signals or a UI reload.
    config.data.setdefault("general", {})["audio_muted"] = _MUTED
    if _MUTED:
        stop_all_audio()
    elif was_muted:
        # Recreate the discarded backend before the first post-mute alert.
        prewarm_speech_engine()


def _playback_block_reason(app, channel="", allow_hidden=False):
    """Return why a new sound must not start, or an empty string.

    This is the single gate used by WAV and text-to-speech playback.  Runtime
    parsers identify their owning panel with ``channel``; explicit Test and
    Replay controls opt into ``allow_hidden`` because they are direct user
    actions.
    """
    if audio_muted():
        return "muted"
    channel = str(channel or "").strip().casefold()
    if channel and not allow_hidden:
        checker = getattr(app, "audio_playback_allowed", None)
        if callable(checker) and not checker(channel):
            return "window hidden"
    return ""


def playback_block_reason(channel="", allow_hidden=False):
    """Expose the authoritative current block reason to UI dispatchers."""
    return _playback_block_reason(
        QApplication.instance(), channel, allow_hidden)


def _report_blocked(app, source, reason, channel=""):
    notifier = getattr(app, "audio_blocked", None)
    if callable(notifier):
        notifier(
            str(source or "Vantage alert"), str(reason or "blocked"),
            str(channel or ""))


def _audio_profile_key(character="", server=""):
    return f"{str(character or '').strip().casefold()}@{str(server or '').strip().casefold()}"


def profile_audio_settings(character="", server=""):
    """Return the GINA-style voice, speed, and volume for one log profile."""
    character = str(character or "").strip()
    server = str(server or "").strip()
    defaults = {
        "character": character, "server": server, "voice_name": "",
        "voice_speed": 0, "volume": 100}
    if not character:
        return defaults
    profiles = config.data.get("spells", {}).get("audio_profiles", {})
    exact = profiles.get(_audio_profile_key(character, server))
    if isinstance(exact, dict):
        defaults.update(exact)
        return defaults
    # Older/single-server profiles still apply when the character name is
    # unambiguous. Never borrow settings from another character.
    matches = [
        value for value in profiles.values()
        if isinstance(value, dict) and
        str(value.get("character", "")).casefold() == character.casefold()]
    if len(matches) == 1:
        defaults.update(matches[0])
    return defaults


def save_profile_audio_settings(
        character, server="", voice_name="", voice_speed=0, volume=100):
    """Persist one log character's independent GINA-style audio profile."""
    character = str(character or "").strip()
    server = str(server or "").strip()
    if not character:
        return False
    try:
        voice_speed = max(-10, min(10, int(voice_speed)))
    except (TypeError, ValueError):
        voice_speed = 0
    try:
        volume = max(0, min(100, int(volume)))
    except (TypeError, ValueError):
        volume = 100
    profiles = config.data.setdefault("spells", {}).setdefault(
        "audio_profiles", {})
    profiles[_audio_profile_key(character, server)] = {
        "character": character[:80],
        "server": server[:80],
        "voice_name": str(voice_name or "")[:160],
        "voice_speed": voice_speed,
        "volume": volume,
    }
    config.save()
    return True


def _speech_engine():
    global _SPEECH, _DEFAULT_VOICE_NAME
    app = QApplication.instance()
    if not app or QTextToSpeech is None:
        return None
    if _SPEECH is None:
        _SPEECH = QTextToSpeech(app)
    if not _DEFAULT_VOICE_NAME:
        try:
            _DEFAULT_VOICE_NAME = _SPEECH.voice().name()
        except (AttributeError, RuntimeError):
            _DEFAULT_VOICE_NAME = ""
    return _SPEECH


def _finish_speech_prewarm():
    """Initialize the local Qt/SAPI backend without speaking or taking focus."""
    global _SPEECH_PREWARM_PENDING
    _SPEECH_PREWARM_PENDING = False
    if audio_muted():
        return False
    speech = _speech_engine()
    if speech is None:
        return False
    # Voice discovery and selection are part of the measurable cold path on
    # Windows. Do them now on Qt's owning thread so the first real alert only
    # has to submit its text to the already initialized backend.
    _apply_speech_profile(speech, profile_audio_settings())
    return True


def prewarm_speech_engine(delay_ms=0):
    """Schedule one silent speech-backend warm-up on the Qt event loop.

    QTextToSpeech and its Windows SAPI backend are Qt objects and must stay on
    the application thread. A zero-delay Qt callback is asynchronous with
    respect to application construction but never creates a worker thread,
    speaks, or changes window focus.
    """
    global _SPEECH_PREWARM_PENDING
    if _SPEECH is not None:
        return True
    app = QApplication.instance()
    if (app is None or QTextToSpeech is None or audio_muted() or
            _SPEECH_PREWARM_PENDING):
        return bool(_SPEECH_PREWARM_PENDING)
    _SPEECH_PREWARM_PENDING = True
    QTimer.singleShot(
        max(0, int(delay_ms or 0)), _finish_speech_prewarm)
    return True


def speech_voice_names():
    """Return installed Windows speech voices without exposing Qt objects."""
    speech = _speech_engine()
    if speech is None:
        return []
    try:
        return sorted({
            str(voice.name()).strip() for voice in speech.availableVoices()
            if str(voice.name()).strip()}, key=str.casefold)
    except (AttributeError, RuntimeError):
        return []


def select_vantage_command_voice(voice_names, startup_voice=""):
    """Choose the best installed voice for the Vantage Adjutant preset.

    The preset is an original Vantage presentation using only a voice already
    installed on Windows.  It neither downloads nor imitates a third-party
    character voice. Voice objects may be supplied so Qt's reported gender can
    supplement deterministic name matching.
    """
    voices = []
    seen = set()
    for value in voice_names or ():
        name_getter = getattr(value, "name", None)
        try:
            raw_name = name_getter() if callable(name_getter) else value
            name = str(raw_name or "").strip()
        except (AttributeError, RuntimeError, TypeError):
            name = str(value or "").strip()
        folded = name.casefold()
        if name and folded not in seen:
            gender = ""
            gender_getter = getattr(value, "gender", None)
            if callable(gender_getter):
                try:
                    gender = _speech_state_name(gender_getter())
                except (AttributeError, RuntimeError, TypeError):
                    gender = ""
            voices.append((name, gender))
            seen.add(folded)

    names = [name for name, _gender in voices]

    def first_matching(*needles):
        return next((
            name for name in names
            if any(needle in name.casefold() for needle in needles)), "")

    # Zira is the most broadly installed calm female Windows voice. Additional
    # known local voices keep the same readable, non-shrill direction.
    preferred = first_matching("microsoft zira")
    if preferred:
        return preferred
    preferred = first_matching(
        "microsoft ava", "microsoft jenny", "microsoft aria",
        "microsoft hazel", "microsoft susan", "microsoft eva",
        "microsoft linda", "microsoft natasha", "microsoft sonia",
        "zira", "ava", "jenny", "aria", "hazel", "susan",
        "female", "feminine")
    if preferred:
        return preferred
    preferred = next((
        name for name, gender in voices if gender == "female"), "")
    if preferred:
        return preferred

    # Preserve the earlier safe local fallback when no female voice is
    # installed, so speech remains available rather than failing closed.
    preferred = first_matching(
        "microsoft mark", "microsoft david",
        "microsoft guy", "microsoft george", "microsoft ryan",
        "microsoft james", "microsoft richard", "microsoft sean",
        "male", "masculine")
    if preferred:
        return preferred
    startup = str(startup_voice or "").strip()
    if startup:
        current = next((
            name for name in names if name.casefold() == startup.casefold()), "")
        if current:
            return current
    return names[0] if names else ""


def vantage_command_voice_name():
    """Return the installed voice currently backing Vantage Adjutant."""
    speech = _speech_engine()
    inventory = []
    if speech is not None:
        try:
            inventory = list(speech.availableVoices())
        except (AttributeError, RuntimeError):
            inventory = []
    return select_vantage_command_voice(
        inventory or speech_voice_names(), _DEFAULT_VOICE_NAME)


def vantage_command_voice_label():
    """Return honest user-facing text for the local default voice preset."""
    resolved = vantage_command_voice_name()
    return (f"Vantage Adjutant · {resolved}" if resolved else
            "Vantage Adjutant · local Windows voice")


def unavailable_voice_label(voice_name):
    """Describe a preserved, currently unavailable explicit voice."""
    return (f"{str(voice_name or '').strip()} · unavailable; "
            "Vantage Adjutant fallback active")


def vantage_command_voice_description(unavailable_voice=""):
    """Shared accessible help for blank/default voice choices."""
    description = (
        "Vantage Adjutant uses a calm installed female Windows voice with a "
        "measured command tone, and falls back locally if that voice is "
        "unavailable. It is an original local preset, not an imitation or "
        "download. A saved character profile or an explicitly selected "
        "installed voice takes priority.")
    missing = str(unavailable_voice or "").strip()
    if missing:
        description += (
            f" The saved voice {missing} is unavailable; it remains saved, "
            "and Vantage Adjutant is active until that voice is available.")
    return description


def _apply_speech_profile(speech, settings, voice_name="", pitch=0):
    """Apply every mutable voice setting for one isolated utterance.

    The Qt speech engine is shared, so leaving one setting untouched leaks it
    into the next alert.  Resolve voice from the trigger first, then the
    character profile, and finally the local Vantage Adjutant preset; rate and
    pitch are deliberately reset on every call as well.
    """
    try:
        voices = list(speech.availableVoices())
        voice_names = [str(voice.name()).strip() for voice in voices]
        requested = str(
            voice_name or settings.get("voice_name", "") or "").strip()
        wanted = requested
        requested_is_installed = bool(requested) and any(
            name.casefold() == requested.casefold() for name in voice_names)
        if not requested_is_installed:
            wanted = select_vantage_command_voice(
                voices, _DEFAULT_VOICE_NAME)
        selected = next((
            voice for voice in voices
            if str(voice.name()).casefold() == wanted.casefold()), None)
        if selected is not None:
            speech.setVoice(selected)
        speed_value = int(settings.get("voice_speed", 0))
        pitch_value = int(pitch or 0)
        # A slight slowdown and lower pitch make the local female fallback
        # comfortable during repeated alerts. Explicit voices/settings remain
        # exact and are never forced through this preset tone.
        rate = (-0.05 if not requested and speed_value == 0 else
                speed_value / 10.0)
        tone = (-0.08 if not requested and pitch_value == 0 else
                pitch_value / 10.0)
        speech.setRate(max(-1.0, min(1.0, rate)))
        speech.setPitch(max(-1.0, min(1.0, tone)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _stop_speech_immediately(speech):
    """Flush queued speech at the earliest boundary supported by Qt/SAPI."""
    boundary = getattr(
        getattr(QTextToSpeech, "BoundaryHint", None), "Immediate", None)
    try:
        if boundary is not None:
            speech.stop(boundary)
        else:
            speech.stop()
    except TypeError:
        # Small test adapters and older Qt bindings only expose stop().
        speech.stop()


def _speech_state_name(state):
    """Return a stable lowercase Qt speech-state name for real/test engines."""
    name = getattr(state, "name", "")
    if name:
        return str(name).casefold()
    return str(state or "").rsplit(".", 1)[-1].casefold()


def _current_speech_state(speech):
    getter = getattr(speech, "state", None)
    if not callable(getter):
        return ""
    try:
        return _speech_state_name(getter())
    except (AttributeError, RuntimeError, TypeError):
        return ""


def _reset_speech_scheduler():
    """Forget all queued speech and invalidate every delayed callback."""
    global _SPEECH_ACTIVE, _SPEECH_GAP_PENDING, _SPEECH_EPOCH
    _SPEECH_PENDING.clear()
    _SPEECH_ACTIVE = None
    _SPEECH_GAP_PENDING = False
    _SPEECH_EPOCH += 1


def _bind_speech_scheduler(speech):
    """Attach the one engine-state listener used by the serial scheduler."""
    global _SPEECH_BOUND_ENGINE, _SPEECH_STATE_SIGNAL
    if _SPEECH_BOUND_ENGINE is speech:
        return
    _reset_speech_scheduler()
    _SPEECH_BOUND_ENGINE = speech
    _SPEECH_STATE_SIGNAL = False
    signal = getattr(speech, "stateChanged", None)
    connector = getattr(signal, "connect", None)
    if callable(connector):
        try:
            connector(lambda state, engine=speech:
                      _speech_state_changed(engine, state))
            _SPEECH_STATE_SIGNAL = True
        except (AttributeError, RuntimeError, TypeError):
            _SPEECH_STATE_SIGNAL = False


def _speech_request_key(request):
    """Coalesce exact automatic duplicates without reordering distinct alerts."""
    return tuple(str(request.get(part, "") or "").strip().casefold()
                 for part in ("channel", "source", "message"))


def _speech_fallback_duration(message):
    """Conservative drain time when a backend exposes no state API at all."""
    words = max(1, len(str(message or "").split()))
    characters = len(str(message or ""))
    return max(1_500, min(15_000, 650 + words * 430 + characters * 22))


def _speech_notify_started(request):
    app = QApplication.instance()
    notifier = getattr(app, "audio_started", None)
    if not callable(notifier):
        return
    source = str(request.get("source") or "Vantage speech")
    message = str(request.get("message") or "")
    volume = int(request.get("volume", 0))
    channel = str(request.get("channel") or "")
    try:
        notifier(source, f"tts:{message[:60]}", volume, channel)
    except TypeError:  # Backward-compatible host/test adapter.
        notifier(source, f"tts:{message[:60]}", volume)


def _finish_active_speech(speech, request_id):
    """Release a completed phrase, then enforce a short silent separation."""
    global _SPEECH_ACTIVE, _SPEECH_GAP_PENDING
    if speech is not _SPEECH or not _SPEECH_ACTIVE:
        return
    if int(_SPEECH_ACTIVE.get("id", -1)) != int(request_id):
        return
    _SPEECH_ACTIVE = None
    _SPEECH_GAP_PENDING = True
    epoch = _SPEECH_EPOCH

    def after_gap():
        global _SPEECH_GAP_PENDING
        if speech is not _SPEECH or epoch != _SPEECH_EPOCH:
            return
        _SPEECH_GAP_PENDING = False
        _start_next_speech(speech)

    QTimer.singleShot(_SPEECH_GAP_MS, after_gap)


def _poll_speech_state(speech, epoch, request_id=0):
    """Drain engines whose state signal is absent, disconnected, or delayed."""
    if speech is not _SPEECH or epoch != _SPEECH_EPOCH:
        return
    state = _current_speech_state(speech)
    if _SPEECH_ACTIVE:
        active_id = int(_SPEECH_ACTIVE.get("id", -1))
        if state in ("ready", "error"):
            _finish_active_speech(speech, active_id)
            return
        if state:
            QTimer.singleShot(
                _SPEECH_POLL_MS,
                lambda: _poll_speech_state(speech, epoch, active_id))
            return
        # The smallest/oldest adapters provide neither stateChanged nor
        # state().  Do not stop them: wait a conservative full-phrase window
        # before offering the next item to their native queue.
        delay = _speech_fallback_duration(
            _SPEECH_ACTIVE.get("message", ""))
        QTimer.singleShot(
            delay, lambda: _finish_active_speech(speech, active_id))
        return
    if _SPEECH_PENDING and not _SPEECH_GAP_PENDING:
        if not state or state in ("ready", "error"):
            _start_next_speech(speech)
        else:
            QTimer.singleShot(
                _SPEECH_POLL_MS,
                lambda: _poll_speech_state(speech, epoch, request_id))


def _speech_state_changed(speech, state):
    """Advance only after Qt reports that the active phrase fully finished."""
    if speech is not _SPEECH:
        return
    state_name = _speech_state_name(state)
    if state_name in ("ready", "error") and _SPEECH_ACTIVE:
        _finish_active_speech(speech, _SPEECH_ACTIVE.get("id", -1))
    elif (state_name in ("ready", "error") and _SPEECH_PENDING and
          not _SPEECH_GAP_PENDING):
        _start_next_speech(speech)


def _start_next_speech(speech):
    """Start exactly one queued utterance with its own captured voice profile."""
    global _SPEECH_ACTIVE
    if (speech is not _SPEECH or _SPEECH_ACTIVE or _SPEECH_GAP_PENDING or
            not _SPEECH_PENDING):
        return False
    state = _current_speech_state(speech)
    if state and state not in ("ready", "error"):
        QTimer.singleShot(
            _SPEECH_POLL_MS,
            lambda: _poll_speech_state(speech, _SPEECH_EPOCH))
        return False

    while _SPEECH_PENDING:
        request = _SPEECH_PENDING.pop(0)
        app = QApplication.instance()
        reason = _playback_block_reason(
            app, request.get("channel", ""),
            bool(request.get("allow_hidden", False)))
        live_volume = round(
            int(request.get("base_volume", 0)) * master_volume() / 100)
        request["volume"] = live_volume
        if reason or live_volume <= 0:
            _report_blocked(
                app, request.get("source", "Vantage speech"),
                reason or "master volume 0%", request.get("channel", ""))
            continue
        _apply_speech_profile(
            speech, request.get("profile", {}),
            voice_name=request.get("voice_name", ""),
            pitch=request.get("pitch", 0))
        try:
            speech.setVolume(int(request.get("volume", 0)) / 100.0)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue

        # A mute/config signal may run while voice properties are applied.
        reason = _playback_block_reason(
            app, request.get("channel", ""),
            bool(request.get("allow_hidden", False)))
        if reason or speech is not _SPEECH:
            _report_blocked(
                app, request.get("source", "Vantage speech"),
                reason or "muted", request.get("channel", ""))
            continue
        _SPEECH_ACTIVE = request
        try:
            speech.say(request["message"])
        except (AttributeError, RuntimeError, TypeError):
            _SPEECH_ACTIVE = None
            continue
        _speech_notify_started(request)
        if not _SPEECH_STATE_SIGNAL:
            QTimer.singleShot(
                _SPEECH_POLL_MS,
                lambda: _poll_speech_state(
                    speech, _SPEECH_EPOCH, request.get("id", 0)))
        return True
    return False


def _queue_speech_request(speech, request, replace_pending=False):
    """Queue without ever stopping the active phrase or growing unbounded."""
    _bind_speech_scheduler(speech)
    if replace_pending:
        key = _speech_request_key(request)
        if (_SPEECH_ACTIVE and _SPEECH_ACTIVE.get("automatic") and
                _speech_request_key(_SPEECH_ACTIVE) == key):
            # A duplicate of the sentence already being spoken adds no new
            # information. Let the active copy finish and do not echo it.
            return True
        for index, pending in enumerate(_SPEECH_PENDING):
            if (pending.get("automatic") and
                    _speech_request_key(pending) == key):
                # Same alert, fresher values, same FIFO position.  This is the
                # only coalescing rule, so distinct critical alerts keep order.
                _SPEECH_PENDING[index] = request
                return True
    if len(_SPEECH_PENDING) >= _SPEECH_MAX_PENDING:
        # Refuse only the newest waiting request. Never truncate the active
        # phrase or reorder the distinct alerts already promised to the user.
        _report_blocked(
            QApplication.instance(), request.get("source", "Vantage speech"),
            "speech queue full", request.get("channel", ""))
        return False
    _SPEECH_PENDING.append(request)
    _start_next_speech(speech)
    return True


def stop_all_audio():
    """Immediately silence and dispose every Vantage playback backend."""
    global _SPEECH, _SPEECH_BOUND_ENGINE, _SPEECH_STATE_SIGNAL
    for effect in tuple(_ACTIVE_EFFECTS):
        # Muting volume before stop prevents a multimedia backend's already
        # buffered tail from remaining audible for another scheduler turn.
        try:
            effect.setMuted(True)
        except (AttributeError, RuntimeError):
            pass
        try:
            effect.setVolume(0.0)
        except (AttributeError, RuntimeError):
            pass
        try:
            effect.stop()
        except (AttributeError, RuntimeError):
            pass
        try:
            effect.deleteLater()
        except (AttributeError, RuntimeError):
            pass
        _ACTIVE_EFFECTS.discard(effect)
    # Discarding the speech engine as well as stopping it flushes any queued
    # utterances.  Unmuting lazily creates a fresh engine and voice queue.
    speech, _SPEECH = _SPEECH, None
    _reset_speech_scheduler()
    _SPEECH_BOUND_ENGINE = None
    _SPEECH_STATE_SIGNAL = False
    if speech is not None:
        try:
            speech.setVolume(0.0)
        except (AttributeError, RuntimeError):
            pass
        try:
            _stop_speech_immediately(speech)
        except (AttributeError, RuntimeError):
            pass
        try:
            speech.deleteLater()
        except (AttributeError, RuntimeError):
            pass


def _silence_effect(effect):
    """Dispose a not-yet-started effect when the final mute gate closes."""
    try:
        effect.setMuted(True)
    except (AttributeError, RuntimeError):
        pass
    try:
        effect.setVolume(0.0)
    except (AttributeError, RuntimeError):
        pass
    try:
        effect.stop()
    except (AttributeError, RuntimeError):
        pass
    try:
        effect.deleteLater()
    except (AttributeError, RuntimeError):
        pass
    _ACTIVE_EFFECTS.discard(effect)


def play_alert(
        path="", volume=80, repeat=1, source="Vantage alert",
        character="", server="", channel="", allow_hidden=False):
    """Play an identified gallery/custom WAV with per-alert volume control."""
    app = QApplication.instance()
    if not str(path or "").strip():
        return False
    blocked = _playback_block_reason(app, channel, allow_hidden)
    if blocked:
        _report_blocked(app, source, blocked, channel)
        return False
    volume = max(0, min(100, int(volume)))
    profile = profile_audio_settings(character, server)
    volume = round(volume * int(profile.get("volume", 100)) / 100)
    volume = round(volume * master_volume() / 100)
    if volume <= 0:
        return False
    sound = resolve_sound(path)
    if not app or not sound.is_file():
        return False

    effect = QSoundEffect(app)
    effect.setSource(QUrl.fromLocalFile(str(sound.resolve())))
    effect.setVolume(volume / 100.0)
    effect.setLoopCount(max(1, min(int(repeat), 3)))
    _ACTIVE_EFFECTS.add(effect)

    # Keep a final gate adjacent to the real backend call.  It closes the
    # narrow re-entrant window where a signal/config reload can mute Vantage
    # while the sound object is being prepared.
    blocked = _playback_block_reason(app, channel, allow_hidden)
    if blocked:
        _silence_effect(effect)
        _report_blocked(app, source, blocked, channel)
        return False

    def release_if_finished():
        try:
            playing = effect.isPlaying()
        except RuntimeError:
            _ACTIVE_EFFECTS.discard(effect)
            return
        if not playing:
            _ACTIVE_EFFECTS.discard(effect)
            effect.deleteLater()

    effect.playingChanged.connect(release_if_finished)
    effect.play()
    notifier = getattr(app, "audio_started", None)
    if callable(notifier):
        try:
            notifier(
                str(source or "Vantage alert"), path, volume,
                str(channel or ""))
        except TypeError:  # Backward-compatible host/test adapter.
            notifier(str(source or "Vantage alert"), path, volume)
    # Also release failed/unsupported playback without keeping a dead object.
    QTimer.singleShot(12_000, release_if_finished)
    return True


def speak_text(
        text, volume=80, interrupt=False, source="Vantage speech",
        character="", server="", channel="", allow_hidden=False,
        voice_name="", pitch=0, replace_pending=False):
    """Submit speech to Vantage's serial, gap-aware Windows voice scheduler.

    Automatic notifications use ``replace_pending=True`` to coalesce exact
    duplicates while leaving the phrase already being spoken untouched.
    Explicit trigger authors retain the separate ``interrupt`` switch: false
    waits in order and true is the only path that immediately stops speech.
    """
    global _SPEECH_REQUEST_ID
    message = str(text or "").strip()
    app = QApplication.instance()
    blocked = _playback_block_reason(app, channel, allow_hidden)
    if blocked:
        _report_blocked(app, source, blocked, channel)
        return False
    volume = max(0, min(100, int(volume)))
    profile = profile_audio_settings(character, server)
    base_volume = round(volume * int(profile.get("volume", 100)) / 100)
    volume = round(base_volume * master_volume() / 100)
    speech = _speech_engine()
    if not message or volume <= 0 or speech is None:
        return False
    _bind_speech_scheduler(speech)
    if interrupt:
        _reset_speech_scheduler()
        _stop_speech_immediately(speech)
    _SPEECH_REQUEST_ID += 1
    request = {
        "id": _SPEECH_REQUEST_ID,
        "message": message,
        "volume": volume,
        "base_volume": base_volume,
        "profile": dict(profile),
        "voice_name": str(voice_name or "").strip(),
        "pitch": pitch,
        "source": str(source or "Vantage speech"),
        "channel": str(channel or ""),
        "allow_hidden": bool(allow_hidden),
        "automatic": bool(replace_pending),
    }
    return _queue_speech_request(
        speech, request, replace_pending=bool(replace_pending))
