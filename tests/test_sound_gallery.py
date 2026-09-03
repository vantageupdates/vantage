import wave

from vantage.helpers import config
from vantage.helpers.audio import (
    DEFAULT_SOUND, audio_muted, notification_sound, play_alert, resolve_sound,
    set_audio_muted, sound_choices)


def test_built_in_sound_gallery_is_unique_and_complete():
    choices = sound_choices()
    uris = [uri for _label, uri, _description in choices]

    assert len(choices) == 20
    assert len(set(uris)) == len(uris)
    assert DEFAULT_SOUND in uris
    assert all(resolve_sound(uri).is_file() for uri in uris)
    assert all(resolve_sound(uri).suffix.casefold() == ".wav" for uri in uris)
    assert len({resolve_sound(uri).read_bytes() for uri in uris}) == 20


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


def test_global_notification_routes_use_saved_gallery_choice():
    original = config.data.get('sounds')
    try:
        config.data['sounds'] = {
            'market_sale': 'builtin:portal-ping',
            'safety_alert': '',
        }
        assert notification_sound('market_sale') == 'builtin:portal-ping'
        assert notification_sound('safety_alert') == ''
        assert notification_sound('timer_default') == 'builtin:spawn-horn'
    finally:
        if original is None:
            config.data.pop('sounds', None)
        else:
            config.data['sounds'] = original


def test_no_sound_route_is_silent_instead_of_falling_back():
    assert play_alert('', source='Silent route') is False
