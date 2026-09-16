from pathlib import Path
from types import SimpleNamespace

from vantage.helpers import audio, config
from vantage.helpers.application import VantageApp


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callback = callback
        self.callbacks.append(callback)

    def emit(self, value=None):
        for callback in tuple(self.callbacks):
            callback(value)


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
    def __init__(self, name, gender=None):
        self._name = name
        self._gender = gender

    def name(self):
        return self._name

    def gender(self):
        return self._gender


class _Speech:
    def __init__(self):
        self.voices = [_Voice('Voice A'), _Voice('Voice B')]
        self.selected = None
        self.rate = None
        self.pitch = None
        self.volume = None
        self.message = None
        self.messages = []
        self.events = []
        self.stop_count = 0
        self.deleted = False
        self.stateChanged = _Signal()
        self._state = 'Ready'

    def availableVoices(self):
        return self.voices

    def voice(self):
        return self.voices[0]

    def setVoice(self, voice):
        self.selected = voice.name()

    def setRate(self, rate):
        self.rate = rate

    def setPitch(self, pitch):
        self.pitch = pitch

    def setVolume(self, volume):
        self.volume = volume

    def say(self, message):
        self.message = message
        self.messages.append(message)
        self.events.append(('say', message))
        self._state = 'Speaking'
        self.stateChanged.emit(self._state)

    def state(self):
        return self._state

    def complete(self):
        self._state = 'Ready'
        self.stateChanged.emit(self._state)

    def stop(self):
        self.stop_count += 1
        self.events.append(('stop', None))
        self._state = 'Ready'
        self.stateChanged.emit(self._state)

    def deleteLater(self):
        self.deleted = True


class _NativeSpeech(_Speech):
    """Deterministic Qt 6.11 enqueue/aboutToSynthesize adapter."""

    def __init__(self):
        super().__init__()
        self.aboutToSynthesize = _Signal()
        self.enqueued = []
        self.synthesized = []
        self.synthesized_profiles = []
        self.setter_events = []
        self._next_id = 1

    def setVoice(self, voice):
        super().setVoice(voice)
        self.setter_events.append(('voice', self.selected))

    def setRate(self, rate):
        super().setRate(rate)
        self.setter_events.append(('rate', rate))

    def setPitch(self, pitch):
        super().setPitch(pitch)
        self.setter_events.append(('pitch', pitch))

    def setVolume(self, volume):
        super().setVolume(volume)
        self.setter_events.append(('volume', volume))

    def enqueue(self, message):
        utterance_id = self._next_id
        self._next_id += 1
        self.enqueued.append((utterance_id, message))
        self.events.append(('enqueue', message))
        return utterance_id

    def synthesize_next(self):
        utterance_id, message = self.enqueued.pop(0)
        self.aboutToSynthesize.emit(utterance_id)
        self.synthesized.append(message)
        self.synthesized_profiles.append(
            (self.selected, self.rate, self.pitch, self.volume))
        self._state = 'Speaking'
        self.stateChanged.emit(self._state)
        return message

    def stop(self, boundary=None):
        self.stop_count += 1
        self.events.append(('stop', boundary))
        self.enqueued.clear()
        self._state = 'Ready'
        self.stateChanged.emit(self._state)


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


class _TimerHarness:
    def __init__(self):
        self.callbacks = []

    def singleShot(self, delay, callback):
        self.callbacks.append((delay, callback))

    def run_next(self, expected_delay=None):
        delay, callback = self.callbacks.pop(0)
        if expected_delay is not None:
            assert delay == expected_delay
        callback()
        return delay


def test_started_audio_is_recorded_without_spawning_a_second_notification():
    refreshed = []
    host = SimpleNamespace(_refresh_quickbar=lambda: refreshed.append(True))

    VantageApp.audio_started(
        host, "Sale alert", "builtin:crystal-ping", 72, "market")

    assert host._last_audio_event == (
        "Sale alert", "builtin:crystal-ping", 72, "market")
    assert "Sale alert" in host._last_audio
    assert refreshed == [True]


def test_direct_replay_is_serialized_without_automatic_duplicate_coalescing(
        monkeypatch):
    import vantage.helpers.application as application
    calls = []
    host = SimpleNamespace(
        _last_audio_event=(
            'Spell fading · Clarity', 'tts:Clarity fading', 73, 'spells'),
        _last_audio='Spell fading',
        _refresh_quickbar=lambda: None)
    monkeypatch.setattr(application, 'audio_muted', lambda: False)
    monkeypatch.setattr(
        application, 'speak_text',
        lambda *args, **kwargs: calls.append((args, kwargs)) or True)

    assert VantageApp.show_last_sound(host)
    assert calls[0][0][:2] == ('Clarity fading', 73)
    assert calls[0][1]['allow_hidden'] is True
    assert 'replace_pending' not in calls[0][1]


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
    assert speech.pitch == 0.0
    assert speech.volume == 0.4
    assert speech.message == 'Charm broke'
    assert app.events[-1] == (
        'Trigger speech', 'tts:Charm broke', 40)
    audio._ACTIVE_EFFECTS.clear()


def test_per_trigger_voice_and_pitch_are_applied_then_reset_next_call(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 80},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, '_DEFAULT_VOICE_NAME', 'Voice A')
    timers = _TimerHarness()
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text(
        'Ending soon', 50, voice_name='Voice B', pitch=7)
    assert speech.selected == 'Voice B'
    assert speech.pitch == 0.7
    assert speech.volume == 0.4  # phase 50% x master 80%

    assert audio.speak_text('Ready again', 100, pitch=0)
    assert speech.messages == ['Ending soon']
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.selected == 'Voice A'
    assert speech.pitch == -0.08
    assert speech.rate == -0.05
    assert speech.volume == 0.8


def test_vantage_adjutant_voice_selection_is_female_first_and_deterministic():
    voices = [
        'Microsoft Zira Desktop', 'Microsoft David Desktop',
        'Microsoft Mark Desktop']
    assert audio.select_vantage_command_voice(
        voices, 'Microsoft David Desktop') == 'Microsoft Zira Desktop'
    assert audio.select_vantage_command_voice(
        ['Microsoft Zira', 'Microsoft David'], 'Microsoft Zira') == (
            'Microsoft Zira')
    assert audio.select_vantage_command_voice(
        ['Microsoft Zira', 'Acme Male Voice'], 'Microsoft Zira') == (
            'Microsoft Zira')
    assert audio.select_vantage_command_voice(
        ['Microsoft Zira', 'Voice B'], 'Voice B') == 'Microsoft Zira'
    assert audio.select_vantage_command_voice([
        _Voice('Unknown voice', 'Female'),
        _Voice('Microsoft Mark', 'Male')]) == 'Unknown voice'
    assert audio.select_vantage_command_voice([], 'Microsoft David') == ''


def test_vantage_command_is_central_default_and_missing_voice_fallback(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    speech.voices = [
        _Voice('Microsoft David'), _Voice('Microsoft Mark'),
        _Voice('Microsoft Zira')]
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, '_DEFAULT_VOICE_NAME', 'Microsoft David')
    timers = _TimerHarness()
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('Default command')
    assert speech.selected == 'Microsoft Zira'
    assert audio.speak_text('Explicit voice', voice_name='Microsoft Zira')
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.selected == 'Microsoft Zira'
    assert audio.speak_text('Missing saved voice', voice_name='Removed Voice')
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.selected == 'Microsoft Zira'


def test_character_profile_voice_wins_then_missing_profile_falls_back(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {
            'druid@green': {
                'character': 'Druid', 'server': 'Green',
                'voice_name': 'Microsoft Zira', 'voice_speed': 0,
                'volume': 100},
            'cleric@green': {
                'character': 'Cleric', 'server': 'Green',
                'voice_name': 'No Longer Installed', 'voice_speed': 0,
                'volume': 100}}}}
    speech = _Speech()
    speech.voices = [
        _Voice('Microsoft David'), _Voice('Microsoft Mark'),
        _Voice('Microsoft Zira')]
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, '_DEFAULT_VOICE_NAME', 'Microsoft David')
    timers = _TimerHarness()
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('Profile', character='Druid', server='Green')
    assert speech.selected == 'Microsoft Zira'
    assert audio.speak_text('Fallback', character='Cleric', server='Green')
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.selected == 'Microsoft Zira'


def test_master_volume_scales_wav_and_speech_after_profile_volume(
        monkeypatch, tmp_path):
    app = _App()
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'RIFF')
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 50},
        'spells': {'audio_profiles': {
            'gandalf@green': {
                'character': 'Gandalf', 'server': 'Green',
                'voice_name': '', 'voice_speed': 0, 'volume': 50}}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, '_ACTIVE_EFFECTS', set())
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'resolve_sound', lambda _path: Path(wav))
    monkeypatch.setattr(audio, 'QSoundEffect', _Effect)
    monkeypatch.setattr(audio, 'QTimer', type(
        'Timer', (), {'singleShot': staticmethod(lambda *_args: None)}))
    speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.play_alert(
        'builtin:test', 80, character='Gandalf', server='Green')
    assert next(iter(audio._ACTIVE_EFFECTS)).volume == 0.2
    assert audio.speak_text(
        'Test', 80, character='Gandalf', server='Green')
    assert speech.volume == 0.2
    assert app.events[-1] == ('Vantage speech', 'tts:Test', 20)

    # The live setter affects the very next playback without save or reload.
    assert audio.set_master_volume(25) == 25
    assert config.data['general']['master_volume'] == 25
    assert audio.play_alert(
        'builtin:test', 80, character='Gandalf', server='Green')
    assert _Effect.instances[-1].volume == 0.1
    audio._ACTIVE_EFFECTS.clear()


def test_zero_master_volume_is_silent_without_enabling_master_mute(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 0},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))

    class _ForbiddenEffect:
        def __init__(self, _parent):
            raise AssertionError('Zero-volume audio created a sound effect')

    monkeypatch.setattr(audio, 'QSoundEffect', _ForbiddenEffect)
    speech = _Speech()
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert not audio.audio_muted()
    assert not audio.play_alert('builtin:test', 100)
    assert not audio.speak_text('Silent test', 100)
    assert config.data['general']['audio_muted'] is False
    assert app.blocked == []
    assert app.events == []
    assert speech.message is None


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


def test_speech_prewarm_is_silent_async_and_scheduled_only_once(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False},
        'spells': {'audio_profiles': {}}}
    callbacks = []
    created = []
    speech = _Speech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, '_SPEECH', None)
    monkeypatch.setattr(audio, '_SPEECH_PREWARM_PENDING', False)
    monkeypatch.setattr(audio, '_DEFAULT_VOICE_NAME', '')
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'QTimer', type('Timer', (), {
        'singleShot': staticmethod(
            lambda delay, callback: callbacks.append((delay, callback)))}))
    monkeypatch.setattr(
        audio, 'QTextToSpeech',
        lambda parent: created.append(parent) or speech)

    assert audio.prewarm_speech_engine()
    assert audio.prewarm_speech_engine()
    assert len(callbacks) == 1
    assert created == []
    assert speech.messages == []

    callbacks[0][1]()

    assert callbacks[0][0] == 0
    assert created == [app]
    assert audio._SPEECH is speech
    assert speech.messages == []
    assert speech.stop_count == 0
    assert audio.prewarm_speech_engine()
    assert len(callbacks) == 1

    # The first real alert reuses the warmed backend; it does not construct a
    # second SAPI engine or wait for another scheduled callback.
    assert audio.speak_text('First live alert', replace_pending=True)
    assert created == [app]
    assert len(callbacks) == 1
    assert speech.events[-1:] == [('say', 'First live alert')]
    assert speech.stop_count == 0


def test_unmute_schedules_a_fresh_silent_backend_after_queue_reset(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': True},
        'spells': {'audio_profiles': {}}}
    callbacks = []
    monkeypatch.setattr(audio, '_MUTED', True)
    monkeypatch.setattr(audio, '_SPEECH', None)
    monkeypatch.setattr(audio, '_SPEECH_PREWARM_PENDING', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'QTimer', type('Timer', (), {
        'singleShot': staticmethod(
            lambda delay, callback: callbacks.append((delay, callback)))}))

    audio.set_audio_muted(False)

    assert config.data['general']['audio_muted'] is False
    assert audio._SPEECH_PREWARM_PENDING is True
    assert len(callbacks) == 1


def test_automatic_speech_waits_for_active_phrase_and_explicit_interrupt_stops(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    timers = _TimerHarness()
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('Old automatic', replace_pending=True)
    assert audio.speak_text('Latest automatic', replace_pending=True)
    assert speech.messages == ['Old automatic']
    assert speech.stop_count == 0

    assert audio.speak_text('Explicit queued', interrupt=False)
    assert speech.messages == ['Old automatic']
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.messages == ['Old automatic', 'Latest automatic']

    assert audio.speak_text('Explicit interrupt', interrupt=True)
    assert speech.events[-2:] == [
        ('stop', None), ('say', 'Explicit interrupt')]
    assert speech.stop_count == 1
    assert audio._SPEECH_PENDING == []


def test_native_enqueue_keeps_rapid_alerts_continuous_without_say_stop_churn(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _NativeSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    phrases = ['First complete phrase', 'Second complete phrase',
               'Third complete phrase']
    for phrase in phrases:
        assert audio.speak_text(phrase, 80, source=phrase, channel='spells')

    assert [message for _utterance_id, message in speech.enqueued] == phrases
    assert not any(event[0] == 'say' for event in speech.events)
    assert speech.stop_count == 0

    for phrase in phrases:
        assert speech.synthesize_next() == phrase
    assert speech.synthesized == phrases
    assert speech.stop_count == 0
    assert [name for name, _value in speech.setter_events].count('voice') == 1
    assert [name for name, _value in speech.setter_events].count('rate') == 1
    assert [name for name, _value in speech.setter_events].count('pitch') == 1
    assert [name for name, _value in speech.setter_events].count('volume') == 1


def test_native_enqueue_applies_each_profile_at_about_to_synthesize(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {
            'first@green': {
                'character': 'First', 'server': 'Green',
                'voice_name': 'Voice A', 'voice_speed': -2, 'volume': 100},
            'second@green': {
                'character': 'Second', 'server': 'Green',
                'voice_name': 'Voice B', 'voice_speed': 6, 'volume': 50}}}}
    speech = _NativeSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.speak_text(
        'First profile', 80, character='First', server='Green')
    assert audio.speak_text(
        'Second profile', 80, character='Second', server='Green', pitch=5)
    assert speech.selected is None

    speech.synthesize_next()
    speech.synthesize_next()

    assert speech.synthesized_profiles == [
        ('Voice A', -0.2, 0.0, 0.8),
        ('Voice B', 0.6, 0.5, 0.4),
    ]


def test_native_voice_change_reapplies_properties_reset_by_backend(
        monkeypatch):
    class ResettingVoiceSpeech(_NativeSpeech):
        def setVoice(self, voice):
            super().setVoice(voice)
            self.rate = None
            self.pitch = None
            self.volume = None

    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {
            'first@green': {
                'character': 'First', 'server': 'Green',
                'voice_name': 'Voice A', 'voice_speed': 4, 'volume': 100},
            'second@green': {
                'character': 'Second', 'server': 'Green',
                'voice_name': 'Voice B', 'voice_speed': 4, 'volume': 100}}}}
    speech = ResettingVoiceSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.speak_text(
        'First voice', 80, character='First', server='Green', pitch=3)
    assert audio.speak_text(
        'Second voice', 80, character='Second', server='Green', pitch=3)
    speech.synthesize_next()
    speech.synthesize_next()

    assert speech.synthesized_profiles == [
        ('Voice A', 0.4, 0.3, 0.8),
        ('Voice B', 0.4, 0.3, 0.8),
    ]
    assert [name for name, _value in speech.setter_events].count('rate') == 2
    assert [name for name, _value in speech.setter_events].count('pitch') == 2
    assert [name for name, _value in speech.setter_events].count('volume') == 2


def test_native_enqueue_coalesces_duplicates_before_synthesis(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _NativeSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    common = {
        'source': 'Spell fading · Clarity', 'channel': 'spells',
        'replace_pending': True}

    assert audio.speak_text('Clarity fading', 40, **common)
    assert audio.speak_text('Clarity fading', 90, **common)
    assert [message for _utterance_id, message in speech.enqueued] == [
        'Clarity fading']

    speech.synthesize_next()
    assert speech.volume == 0.9
    assert audio.speak_text('Clarity fading', 70, **common)
    assert speech.enqueued == []


def test_native_enqueue_bounds_waiting_work_without_interrupting_head(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _NativeSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    accepted = ['Queue head'] + [
        f'Waiting {index}' for index in range(audio._SPEECH_MAX_PENDING)]
    for phrase in accepted:
        assert audio.speak_text(
            phrase, source=phrase, channel='spells', replace_pending=True)
    assert not audio.speak_text(
        'Overflow', source='Overflow route', channel='spells',
        replace_pending=True)

    assert [message for _utterance_id, message in speech.enqueued] == accepted
    assert speech.stop_count == 0
    assert app.blocked[-1] == (
        'Overflow route', 'speech queue full', 'spells')


def test_native_enqueue_rejects_invalid_ids_without_stuck_pending_work(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))

    for invalid_id in (-1, None, 'invalid', 1.5, True):
        speech = _NativeSpeech()
        speech.enqueue = lambda _message, result=invalid_id: result
        monkeypatch.setattr(audio, '_SPEECH', speech)

        assert not audio.speak_text(
            'Rejected native request', source='Rejected route',
            channel='spells')
        assert audio._SPEECH_PENDING == []
        assert audio._SPEECH_ACTIVE is None
        assert app.blocked[-1] == (
            'Rejected route', 'speech enqueue failed', 'spells')


def test_native_enqueue_mute_and_explicit_interrupt_clear_native_work(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _NativeSpeech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.speak_text('Old one')
    assert audio.speak_text('Old two')
    assert audio.speak_text('Interrupt now', interrupt=True)
    assert speech.stop_count == 1
    assert [message for _utterance_id, message in speech.enqueued] == [
        'Interrupt now']
    assert audio._SPEECH_PENDING[0]['message'] == 'Interrupt now'

    audio.set_audio_muted(True)
    assert speech.stop_count == 2
    assert speech.enqueued == []
    assert audio._SPEECH_PENDING == []
    assert audio._SPEECH_ACTIVE is None
    assert audio._SPEECH is None


def test_native_runtime_error_reports_all_work_and_recreates_backend(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    failed = _NativeSpeech()
    fresh = _NativeSpeech()
    created = []
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', failed)
    monkeypatch.setattr(
        audio, 'QTextToSpeech',
        lambda parent: created.append(parent) or fresh)

    assert audio.speak_text(
        'Active before error', source='Active route', channel='spells')
    assert audio.speak_text(
        'Pending before error', source='Pending route', channel='spells')
    failed.synthesize_next()
    failed._state = 'Error'
    failed.stateChanged.emit(failed._state)

    assert audio._SPEECH is None
    assert audio._SPEECH_PENDING == []
    assert audio._SPEECH_ACTIVE is None
    assert failed.deleted is True
    assert app.blocked[-2:] == [
        ('Active route', 'speech backend error', 'spells'),
        ('Pending route', 'speech backend error', 'spells'),
    ]

    assert audio.speak_text(
        'Fresh backend alert', source='Fresh route', channel='spells')
    assert created == [app]
    assert audio._SPEECH is fresh
    assert [message for _utterance_id, message in fresh.enqueued] == [
        'Fresh backend alert']
    fresh.synthesize_next()
    assert fresh.synthesized == ['Fresh backend alert']


def test_bard_count_speech_queues_without_forced_interrupt(monkeypatch):
    import vantage.parsers.spells as spells_module

    calls = []
    notices = []
    app = SimpleNamespace(
        _queue_quickbar_notice=notices.append,
        show_overlay_notification=lambda *_args, **_kwargs: None)
    owner = SimpleNamespace(
        _bard_group=SimpleNamespace(add_summary=lambda _summary: None),
        _active_character='Singer', _active_server='Green')
    config.data = {'spells': {
        'bard_count_overlay': False,
        'bard_count_audio': True,
        'fade_sound_volume': 75,
    }}
    monkeypatch.setattr(spells_module, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(
        spells_module, 'speak_text',
        lambda *args, **kwargs: calls.append((args, kwargs)) or True)

    spells_module.Spells._handle_bard_summaries(
        owner, [SimpleNamespace(text='6 Total | 5 Hits | 1 Resist')])

    assert notices == ['6 Total | 5 Hits | 1 Resist']
    assert calls[0][0] == ('6 Total | 5 Hits | 1 Resist', 75)
    assert 'interrupt' not in calls[0][1]


def test_only_explicit_interrupt_requests_qt_immediate_boundary(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}

    class Speech(_Speech):
        def stop(self, boundary=None):
            self.stop_count += 1
            self.events.append(('stop', boundary))
            self._state = 'Ready'
            self.stateChanged.emit(self._state)

    class SpeechApi:
        class BoundaryHint:
            Immediate = 'immediate'

    speech = Speech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, 'QTextToSpeech', SpeechApi)
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert audio.speak_text('Latest event', replace_pending=True)
    assert speech.events == [('say', 'Latest event')]

    assert audio.speak_text('Break in now', interrupt=True)
    assert speech.events[-2:] == [
        ('stop', 'immediate'), ('say', 'Break in now')]


def test_serial_speech_finishes_in_fifo_order_with_gap_and_per_item_voice(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {
            'first@green': {
                'character': 'First', 'server': 'Green',
                'voice_name': 'Voice A', 'voice_speed': -2, 'volume': 100},
            'second@green': {
                'character': 'Second', 'server': 'Green',
                'voice_name': 'Voice B', 'voice_speed': 6, 'volume': 50}}}}
    speech = _Speech()
    timers = _TimerHarness()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text(
        'First phrase must finish', 80, character='First', server='Green',
        source='Route one', channel='spells', replace_pending=True)
    assert audio.speak_text(
        'Second phrase follows', 80, character='Second', server='Green',
        source='Route two', channel='spells', voice_name='Voice B', pitch=5,
        replace_pending=True)

    assert speech.messages == ['First phrase must finish']
    assert speech.selected == 'Voice A'
    assert speech.rate == -0.2
    assert speech.stop_count == 0

    speech.complete()
    assert speech.messages == ['First phrase must finish']
    timers.run_next(audio._SPEECH_GAP_MS)

    assert speech.messages == [
        'First phrase must finish', 'Second phrase follows']
    assert speech.selected == 'Voice B'
    assert speech.rate == 0.6
    assert speech.pitch == 0.5
    assert speech.volume == 0.4
    assert speech.stop_count == 0


def test_automatic_exact_duplicates_coalesce_active_and_pending(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    timers = _TimerHarness()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, 'QTimer', timers)

    common = {
        'source': 'Spell fading · Clarity fading', 'channel': 'spells',
        'replace_pending': True}
    assert audio.speak_text('Clarity fading', 70, **common)
    assert audio.speak_text('Clarity fading', 90, **common)
    assert speech.messages == ['Clarity fading']
    assert audio._SPEECH_PENDING == []

    queued = {
        'source': 'Tell · Tell from Ayla', 'channel': 'chat',
        'replace_pending': True}
    assert audio.speak_text('Incoming tell from Ayla', 40, **queued)
    assert audio.speak_text('Incoming tell from Ayla', 85, **queued)
    assert len(audio._SPEECH_PENDING) == 1
    assert audio._SPEECH_PENDING[0]['base_volume'] == 85

    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.messages == ['Clarity fading', 'Incoming tell from Ayla']
    assert speech.volume == 0.85
    assert speech.stop_count == 0


def test_speech_queue_is_bounded_without_disturbing_active_or_fifo(monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    timers = _TimerHarness()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('Active phrase', replace_pending=True)
    accepted = []
    for index in range(audio._SPEECH_MAX_PENDING):
        message = f'Pending {index}'
        assert audio.speak_text(
            message, source=f'Route {index}', replace_pending=True)
        accepted.append(message)
    assert not audio.speak_text(
        'Overflow', source='Overflow route', channel='spells',
        replace_pending=True)

    assert speech.messages == ['Active phrase']
    assert [item['message'] for item in audio._SPEECH_PENDING] == accepted
    assert speech.stop_count == 0
    assert app.blocked[-1] == (
        'Overflow route', 'speech queue full', 'spells')

    for expected in accepted:
        speech.complete()
        timers.run_next(audio._SPEECH_GAP_MS)
        assert speech.messages[-1] == expected
    assert speech.messages == ['Active phrase', *accepted]
    assert speech.stop_count == 0


def test_waiting_speech_uses_live_master_volume_when_it_actually_starts(
        monkeypatch):
    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    timers = _TimerHarness()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('First', 80)
    assert audio.speak_text('Queued', 80)
    audio.set_master_volume(25)
    speech.complete()
    timers.run_next(audio._SPEECH_GAP_MS)

    assert speech.messages == ['First', 'Queued']
    assert speech.volume == 0.2
    assert app.events[-1] == ('Vantage speech', 'tts:Queued', 20)


def test_scheduler_falls_back_without_qt_state_signal_or_state_method(
        monkeypatch):
    class LegacySpeech(_Speech):
        stateChanged = None
        state = None

        def __init__(self):
            super().__init__()
            self.stateChanged = None

        def say(self, message):
            self.message = message
            self.messages.append(message)
            self.events.append(('say', message))

    app = _App()
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = LegacySpeech()
    timers = _TimerHarness()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)
    monkeypatch.setattr(audio, 'QTimer', timers)

    assert audio.speak_text('Legacy first phrase')
    assert audio.speak_text('Legacy second phrase')
    assert speech.messages == ['Legacy first phrase']

    timers.run_next(audio._SPEECH_POLL_MS)
    timers.run_next(audio._speech_fallback_duration('Legacy first phrase'))
    timers.run_next(audio._SPEECH_GAP_MS)
    assert speech.messages == ['Legacy first phrase', 'Legacy second phrase']
    assert speech.stop_count == 0


def test_replacement_speech_still_honors_hidden_and_mute_gates(monkeypatch):
    app = _App()
    app.channel_visible = False
    config.data = {
        'general': {'audio_muted': False, 'master_volume': 100},
        'spells': {'audio_profiles': {}}}
    speech = _Speech()
    monkeypatch.setattr(audio, '_MUTED', False)
    monkeypatch.setattr(audio, 'QApplication', type(
        'Application', (), {'instance': staticmethod(lambda: app)}))
    monkeypatch.setattr(audio, '_SPEECH', speech)

    assert not audio.speak_text(
        'Blocked automatic', channel='vitals', replace_pending=True)
    assert speech.events == []
    assert audio._SPEECH_PENDING == []
    assert app.blocked[-1] == (
        'Vantage speech', 'window hidden', 'vitals')

    app.channel_visible = True
    config.data['general']['audio_muted'] = True
    assert not audio.speak_text(
        'Muted automatic', channel='vitals', replace_pending=True)
    assert not any(event == ('say', 'Muted automatic') for event in speech.events)
    assert audio._SPEECH_PENDING == []


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
    assert audio.speak_text(
        'Waiting speech', 80, source='Waiting speech', channel='spells')
    assert [item['message'] for item in audio._SPEECH_PENDING] == [
        'Waiting speech']
    active_effect = _Effect.instances[-1]
    audio.set_audio_muted(True)

    assert active_effect.muted is True
    assert active_effect.volume == 0.0
    assert active_effect.stop_count == 1
    assert speech.volume == 0.0
    assert speech.stop_count == 1
    assert audio._SPEECH_PENDING == []
    assert audio._SPEECH_ACTIVE is None
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
