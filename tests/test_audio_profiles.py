from pathlib import Path

from vantage.helpers import audio, config


class _Signal:
    def connect(self, callback):
        self.callback = callback


class _Effect:
    def __init__(self, _parent):
        self.playingChanged = _Signal()
        self.volume = None

    def setSource(self, _source):
        pass

    def setVolume(self, volume):
        self.volume = volume

    def setLoopCount(self, _count):
        pass

    def play(self):
        pass

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
        pass


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
