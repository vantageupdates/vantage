from pathlib import Path
from types import SimpleNamespace

from vantage.helpers import audio, config
from vantage.helpers.application import VantageApp


class _Signal:
    def connect(self, callback):
        self.callback = callback


class _Effect:
    instances = []

    def __init__(self, _parent):
        self.playingChanged = _Signal()
        self.volume = None
        self.muted = False
        self.play_count = 0
        self.stop_count = 0
        self.deleted = False
        self.__class__.instances.append(self)

    def setSource(self, _source):
        pass

    def setVolume(self, volume):
        self.volume = volume

    def setLoopCount(self, _count):
        pass

    def play(self):
        self.play_count += 1

    def setMuted(self, muted):
        self.muted = bool(muted)

    def stop(self):
        self.stop_count += 1

    def deleteLater(self):
        self.deleted = True

    def isPlaying(self):
        return True


class _Voice:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Speech:
    def __init__(self):
        self.voices = [_Voice('Voice A'), _Voice('Voice B')]
        self.selected = None
        self.rate = None
        self.volume = None
        self.message = None
        self.stop_count = 0
        self.deleted = False

    def availableVoices(self):
        return self.voices

    def setVoice(self, voice):
        self.selected = voice.name()

    def setRate(self, rate):
        self.rate = rate

    def setVolume(self, volume):
        self.volume = volume

    def say(self, message):
        self.message = message

    def stop(self):
        self.stop_count += 1

    def deleteLater(self):
        self.deleted = True


class _App:
    def __init__(self):
        self.events = []
        self.blocked = []
        self.channel_visible = True

    def audio_started(self, source, path, volume):
        self.events.append((source, path, volume))

    def audio_playback_allowed(self, _channel):
        return self.channel_visible

    def audio_blocked(self, source, reason, channel):
        self.blocked.append((source, reason, channel))


def test_started_audio_is_recorded_without_spawning_a_second_notification():
    refreshed = []
    host = SimpleNamespace(_refresh_quickbar=lambda: refreshed.append(True))

    VantageApp.audio_started(
        host, "Sale alert", "builtin:crystal-ping", 72, "market")

    assert host._last_audio_event == (
        "Sale alert", "builtin:crystal-ping", 72, "market")
    assert "Sale alert" in host._last_audio
    assert refreshed == [True]


def test_character_audio_profile_is_server_specific_and_persists(monkeypatch):
    monkeypatch.setattr(config, 'save', lambda: None)
    config.data = {'spells': {'audio_profiles': {}}}

    assert audio.save_profile_audio_settings(
        'Gandalf', 'Green', 'Voice B', 7, 50)
    exact = audio.profile_audio_settings('Gandalf', 'Green')
    other = audio.profile_audio_settings('Gandalf', 'Blue')

    assert exact == {
        'character': 'Gandalf', 'server': 'Green',
        'voice_name': 'Voice B', 'voice_speed': 7, 'volume': 50}
    assert other['voice_name'] == 'Voice B'
    assert other['volume'] == 50
    audio.save_profile_audio_settings('Gandalf', 'Blue', 'Voice A', -2, 90)
    assert audio.profile_audio_settings('Gandalf', 'Blue')['volume'] == 90
    assert audio.profile_audio_settings('Gandalf', 'Red')['volume'] == 100


def test_profile_volume_voice_and_speed_are_applied_to_trigger_audio(
        monkeypatch, tmp_path):
    app = _App()
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'RIFF')
    config.data = {'spells': {'audio_profiles': {
        'gandalf@green': {
            'character': 'Gandalf', 'server': 'Green',
            'voice_name': 'Voice B', 'voice_speed': 7, 'volume': 50}}}}
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'resolve_sound', lambda _path: Path(wav))
    monkeypatch.setattr(audio, 'QSoundEffect', _Effect)
    monkeypatch.setattr(audio, 'QTimer', type(
        'Timer', (), {'singleShot': staticmethod(lambda *_args: None)}))
    speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.play_alert(
        'builtin:test', 80, source='Trigger sound',
        character='Gandalf', server='Green')
    effect = next(iter(audio._ACTIVE_EFFECTS))
    assert effect.volume == 0.4
    assert audio.speak_text(
        'Charm broke', 80, source='Trigger speech',
        character='Gandalf', server='Green')
    assert speech.selected == 'Voice B'
    assert speech.rate == 0.7
    assert speech.volume == 0.4
    assert speech.message == 'Charm broke'
    assert app.events[-1] == (
        'Trigger speech', 'tts:Charm broke', 40)
    audio._ACTIVE_EFFECTS.clear()


def test_master_mute_is_a_fail_closed_gate_for_wav_and_speech(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': True},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))

    class _ForbiddenEffect:
        def __init__(self, _parent):
            raise AssertionError('Muted audio created a sound effect')

    monkeypatch.setattr(audio, 'QSoundEffect', _ForbiddenEffect)
    speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert not audio.play_alert(
        'builtin:rune-pulse', 100, source='Spell resist', channel='spells')
    assert not audio.speak_text(
        'Charm broke', 100, source='Charm speech', channel='spells')
    assert speech.message is None
    assert app.events == []
    assert app.blocked == [
        ('Spell resist', 'muted', 'spells'),
        ('Charm speech', 'muted', 'spells')]


def test_hidden_owner_blocks_runtime_audio_but_direct_test_can_play(
        monkeypatch, tmp_path):
    app = _App()
    app.channel_visible = False
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'RIFF')
    config.data = {
        'general': {'audio_muted': False},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'resolve_sound', lambda _path: Path(wav))
    monkeypatch.setattr(audio, 'QSoundEffect', _Effect)
    monkeypatch.setattr(audio, 'QTimer', type(
        'Timer', (), {'singleShot': staticmethod(lambda *_args: None)}))

    assert not audio.play_alert(
        'builtin:test', 80, source='Buff fading', channel='spells')
    assert app.blocked[-1] == (
        'Buff fading', 'window hidden', 'spells')
    assert audio.play_alert(
        'builtin:test', 80, source='Test · buff sound',
        channel='spells', allow_hidden=True)
    assert app.events[-1] == ('Test · buff sound', 'builtin:test', 80)
    audio._ACTIVE_EFFECTS.clear()


def test_config_reload_mute_stops_active_wav_and_flushes_speech(monkeypatch):
    config.data = {
        'general': {'audio_muted': False},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    effect = _Effect(None)
    speech = _Speech()
    monkeypatch.setattr(audio, '_ACTIVE_EFFECTS', {effect})
    monkeypatch.setattr(audio, '_SPEECH', speech)

    # Simulate settings/config being reloaded without the Quick Bar callback.
    config.data['general']['audio_muted'] = True

    assert audio.audio_muted() is True
    assert effect.muted is True
    assert effect.volume == 0.0
    assert effect.stop_count == 1
    assert effect.deleted is True
    assert audio._ACTIVE_EFFECTS == set()
    assert speech.volume == 0.0
    assert speech.stop_count == 1
    assert speech.deleted is True
    assert audio._SPEECH is None


def test_master_mute_stops_now_blocks_tests_and_replay_then_unmutes(
        monkeypatch, tmp_path):
    app = _App()
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'RIFF')
    config.data = {
        'general': {'audio_muted': False},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, '_ACTIVE_EFFECTS', set())
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'resolve_sound', lambda _path: Path(wav))
    monkeypatch.setattr(audio, 'QSoundEffect', _Effect)
    monkeypatch.setattr(audio, 'QTimer', type(
        'Timer', (), {'singleShot': staticmethod(lambda *_args: None)}))
    _Effect.instances.clear()
    speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.play_alert(
        'builtin:test', 80, source='Active sound', channel='spells')
    assert audio.speak_text(
        'Active speech', 80, source='Active speech', channel='spells')
    active_effect = _Effect.instances[-1]
    audio.set_audio_muted(True)

    assert active_effect.muted is True
    assert active_effect.volume == 0.0
    assert active_effect.stop_count == 1
    assert speech.volume == 0.0
    assert speech.stop_count == 1
    assert config.data['general']['audio_muted'] is True

    created_while_muted = len(_Effect.instances)
    assert not audio.play_alert(
        'builtin:test', 80, source='Test while muted',
        channel='spells', allow_hidden=True)
    assert not audio.speak_text(
        'Replay while muted', 80, source='Replay while muted',
        channel='spells', allow_hidden=True)
    assert len(_Effect.instances) == created_while_muted
    assert app.blocked[-2:] == [
        ('Test while muted', 'muted', 'spells'),
        ('Replay while muted', 'muted', 'spells')]

    audio.set_audio_muted(False)
    fresh_speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', fresh_speech)
    assert config.data['general']['audio_muted'] is False
    assert audio.play_alert(
        'builtin:test', 65, source='Unmuted sound',
        channel='spells', allow_hidden=True)
    assert audio.speak_text(
        'Unmuted speech', 65, source='Unmuted speech',
        channel='spells', allow_hidden=True)
    assert _Effect.instances[-1].play_count == 1
    assert fresh_speech.message == 'Unmuted speech'
    audio._ACTIVE_EFFECTS.clear()


def test_final_backend_gate_catches_mute_during_effect_setup(
        monkeypatch, tmp_path):
    app = _App()
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'RIFF')
    config.data = {
        'general': {'audio_muted': False},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, '_ACTIVE_EFFECTS', set())
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'resolve_sound', lambda _path: Path(wav))

    class _MuteDuringSetup(_Effect):
        def setLoopCount(self, _count):
            audio.set_audio_muted(True)

    monkeypatch.setattr(audio, 'QSoundEffect', _MuteDuringSetup)

    assert not audio.play_alert(
        'builtin:test', 80, source='Racing sound',
        channel='spells', allow_hidden=True)
    effect = _MuteDuringSetup.instances[-1]
    assert effect.play_count == 0
    assert effect.muted is True
    assert effect.deleted is True
    assert app.blocked[-1] == ('Racing sound', 'muted', 'spells')
    audio.set_audio_muted(False)
