import wave

from vantage.helpers.audio import (
    DEFAULT_SOUND, audio_muted, resolve_sound, set_audio_muted, sound_choices)


def test_built_in_sound_gallery_is_unique_and_complete():
    choices = sound_choices()
    uris = [uri for _label, uri, _description in choices]

    assert len(choices) == 6
    assert len(set(uris)) == len(uris)
    assert DEFAULT_SOUND in uris
    assert all(resolve_sound(uri).is_file() for uri in uris)
    assert all(resolve_sound(uri).suffix.casefold() == ".wav" for uri in uris)


def test_built_in_sounds_are_short_standard_pcm_notifications():
    for _label, uri, _description in sound_choices():
        with wave.open(str(resolve_sound(uri)), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
            assert stream.getnchannels() == 1
            assert stream.getsampwidth() == 2
            assert stream.getframerate() == 44100
            assert .12 <= duration <= 1.2


def test_global_audio_mute_is_explicit_and_reversible():
    set_audio_muted(True)
    assert audio_muted()
    set_audio_muted(False)
    assert not audio_muted()
