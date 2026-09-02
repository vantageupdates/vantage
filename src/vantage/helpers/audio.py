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
)
DEFAULT_SOUND = SOUND_GALLERY[0][1]
_BUILTIN_FILES = {
    "builtin:warden-bell": "warden_bell.wav",
    "builtin:spawn-horn": "spawn_horn.wav",
    "builtin:crystal-ping": "crystal_ping.wav",
    "builtin:rune-pulse": "rune_pulse.wav",
    "builtin:soft-tick": "soft_tick.wav",
    "builtin:danger-double": "danger_double.wav",
}
_ACTIVE_EFFECTS = set()
_MUTED = False
_SPEECH = None
_DEFAULT_VOICE_NAME = ""


def sound_choices():
    """Return immutable display labels and URIs for gallery controls."""
    return SOUND_GALLERY


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
    return _MUTED


def set_audio_muted(muted):
    """Globally mute new alerts and immediately stop active Vantage audio."""
    global _MUTED
    _MUTED = bool(muted)
    if _MUTED:
        stop_all_audio()


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
        try:
            _DEFAULT_VOICE_NAME = _SPEECH.voice().name()
        except (AttributeError, RuntimeError):
            _DEFAULT_VOICE_NAME = ""
    return _SPEECH


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


def _apply_speech_profile(speech, settings):
    wanted = str(settings.get("voice_name", "") or _DEFAULT_VOICE_NAME)
    try:
        voices = list(speech.availableVoices())
        selected = next((
            voice for voice in voices
            if str(voice.name()).casefold() == wanted.casefold()), None)
        if selected is not None:
            speech.setVoice(selected)
        speech.setRate(max(-1.0, min(
            1.0, int(settings.get("voice_speed", 0)) / 10.0)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def stop_all_audio():
    global _SPEECH
    for effect in tuple(_ACTIVE_EFFECTS):
        try:
            effect.stop()
            effect.deleteLater()
        except RuntimeError:
            pass
        _ACTIVE_EFFECTS.discard(effect)
    if _SPEECH is not None:
        try:
            _SPEECH.stop()
        except RuntimeError:
            _SPEECH = None


def play_alert(
        path="", volume=80, repeat=1, source="Vantage alert",
        character="", server=""):
    """Play an identified gallery/custom WAV with per-alert volume control."""
    volume = max(0, min(100, int(volume)))
    profile = profile_audio_settings(character, server)
    volume = round(volume * int(profile.get("volume", 100)) / 100)
    if volume <= 0 or _MUTED:
        return False
    app = QApplication.instance()
    sound = resolve_sound(path)
    if not app or not sound.is_file():
        return False

    effect = QSoundEffect(app)
    effect.setSource(QUrl.fromLocalFile(str(sound.resolve())))
    effect.setVolume(volume / 100.0)
    effect.setLoopCount(max(1, min(int(repeat), 3)))
    _ACTIVE_EFFECTS.add(effect)

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
        notifier(str(source or "Vantage alert"), path, volume)
    # Also release failed/unsupported playback without keeping a dead object.
    QTimer.singleShot(12_000, release_if_finished)
    return True


def speak_text(
        text, volume=80, interrupt=False, source="Vantage speech",
        character="", server=""):
    """Speak resolved trigger text through the built-in Windows voice."""
    message = str(text or "").strip()
    volume = max(0, min(100, int(volume)))
    profile = profile_audio_settings(character, server)
    volume = round(volume * int(profile.get("volume", 100)) / 100)
    speech = _speech_engine()
    if not message or volume <= 0 or _MUTED or speech is None:
        return False
    if interrupt:
        speech.stop()
    _apply_speech_profile(speech, profile)
    speech.setVolume(volume / 100.0)
    speech.say(message)
    app = QApplication.instance()
    notifier = getattr(app, "audio_started", None)
    if callable(notifier):
        notifier(str(source or "Vantage speech"), f"tts:{message[:60]}", volume)
    return True
