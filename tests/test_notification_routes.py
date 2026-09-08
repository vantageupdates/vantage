import copy

import pytest

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.notification_routes import (
    NOTIFICATION_ROUTES, NotificationDeliveryResult,
    TellAudioCooldown, classify_chat_notification)


EXPECTED_ROUTES = {
    'spell_fading', 'spell_resisted', 'spell_worn_off', 'tell_message',
    'hail', 'smart_timer', 'raid_encounter', 'market_sale',
    'opendkp_auction', 'death_loop'}


@pytest.fixture(autouse=True)
def _restore_sounds_key_after_each_test():
    """Do not turn an absent optional section into an explicit None."""
    existed = 'sounds' in config.data
    original = copy.deepcopy(config.data.get('sounds'))
    yield
    if existed:
        config.data['sounds'] = original
    else:
        config.data.pop('sounds', None)


def test_route_catalog_is_complete_and_immutable():
    assert set(NOTIFICATION_ROUTES) == EXPECTED_ROUTES
    try:
        NOTIFICATION_ROUTES['extra'] = object()
    except TypeError:
        pass
    else:  # pragma: no cover - documents the immutability contract
        raise AssertionError('route catalog accepted mutation')


def test_chat_classifier_rejects_private_and_non_player_noise():
    tell = classify_chat_notification(
        "Ayla tells you, 'meet me by the tunnel'", 'Mindflux')
    assert tell.semantic_text == 'Tell from Ayla'
    assert tell.voice_text == 'Incoming tell from Ayla'
    assert 'meet me' not in tell.voice_text
    hail = classify_chat_notification(
        "Ayla says, 'Hail, Mindflux'", 'Mindflux')
    assert hail.route_key == 'hail'
    assert classify_chat_notification(
        "You tell Ayla, 'hello'", 'Mindflux') is None
    assert classify_chat_notification(
        "Gabtik tells you, 'Attacking a frost giant Master.'",
        'Mindflux', ('Gabtik',)) is None
    assert classify_chat_notification(
        "Trader auctions, 'WTS Manastone'", 'Mindflux') is None
    assert classify_chat_notification(
        "Camper tells you, 'VTS1:abcdefghijklmnop'", 'Mindflux') is None
    assert classify_chat_notification(
        "a frost giant tells you, 'Begone'", 'Mindflux') is None


def test_tell_audio_cooldown_is_per_sender_character_and_server():
    now = [100.0]
    cooldown = TellAudioCooldown(clock=lambda: now[0])

    assert cooldown.allow("Ayla", "Mindflux", "Green") is True
    now[0] += 10
    assert cooldown.allow("ayla", "MINDFLUX", "green") is False
    assert cooldown.allow("Borin", "Mindflux", "Green") is True
    assert cooldown.allow("Ayla", "Altflux", "Green") is True
    assert cooldown.allow("Ayla", "Mindflux", "Blue") is True

    now[0] = 130.0
    assert cooldown.allow("Ayla", "Mindflux", "Green") is True


def test_tell_audio_cooldown_prunes_to_a_fixed_bound():
    now = [0.0]
    cooldown = TellAudioCooldown(
        clock=lambda: now[0], cooldown=30, max_entries=2)
    for sender in ("Ayla", "Borin", "Ceryn"):
        assert cooldown.allow(sender, "Mindflux", "Green") is True
        now[0] += 1
    assert len(cooldown) == 2


def test_repeated_tells_remain_visual_but_audio_is_suppressed_per_sender():
    now = [500.0]

    class Host:
        def __init__(self):
            self._tell_audio_cooldown = TellAudioCooldown(
                clock=lambda: now[0])
            self.calls = []

        def notify_event(self, route_key, semantic_text, **options):
            self.calls.append((route_key, semantic_text, options))
            return options.get("delivery_override")

    host = Host()
    ayla = classify_chat_notification(
        "Ayla tells you, 'first'", "Mindflux")
    borin = classify_chat_notification(
        "Borin tells you, 'hello'", "Mindflux")
    assert ayla is not None and borin is not None

    VantageApp._deliver_chat_notification(
        host, ayla, "Mindflux", "Green")
    now[0] += 5
    VantageApp._deliver_chat_notification(
        host, ayla, "Mindflux", "Green")
    VantageApp._deliver_chat_notification(
        host, borin, "Mindflux", "Green")

    assert [call[1] for call in host.calls] == [
        "Tell from Ayla", "Tell from Ayla", "Tell from Borin"]
    assert [call[2].get("delivery_override") for call in host.calls] == [
        None, "off", None]
    assert all(call[2]["overlay_id"] == "alerts" for call in host.calls)

    now[0] = 530.0
    VantageApp._deliver_chat_notification(
        host, ayla, "Mindflux", "Green")
    assert host.calls[-1][2].get("delivery_override") is None


class _DispatchHost:
    def __init__(self):
        self.events = []

    def show_overlay_notification(self, title, message, **kwargs):
        self.events.append(('text', message))
        return True

    def _queue_quickbar_notice(self, message):
        self.events.append(('rail', message))


def test_dispatch_registers_semantics_before_exactly_one_audio(monkeypatch):
    import vantage.helpers.application as application
    host = _DispatchHost()
    original = config.data.get('sounds')
    config.data['sounds'] = {'routes': {
        'tell_message': {'delivery': 'voice', 'sound': '', 'voice': 'Amy'}}}
    monkeypatch.setattr(application, 'speak_text', lambda text, *a, **k: (
        host.events.append(('voice', text, k.get('voice_name'))) or True))
    monkeypatch.setattr(application, 'play_alert', lambda *a, **k: (
        host.events.append(('sound', a[0])) or True))
    try:
        result = VantageApp.notify_event(
            host, 'tell_message', 'Tell from Ayla',
            voice_text='Incoming tell from Ayla')
        assert (result.delivery, result.state, bool(result)) == (
            'voice', 'played', True)
        assert host.events == [
            ('text', 'Tell from Ayla'),
            ('voice', 'Incoming tell from Ayla', 'Amy')]
    finally:
        config.data['sounds'] = original


def test_dispatch_off_is_visual_only(monkeypatch):
    import vantage.helpers.application as application
    host = _DispatchHost()
    original = config.data.get('sounds')
    config.data['sounds'] = {'routes': {
        'market_sale': {'delivery': 'off', 'sound': 'builtin:crystal-ping'}}}
    monkeypatch.setattr(application, 'play_alert', lambda *a, **k: 1 / 0)
    try:
        result = VantageApp.notify_event(
            host, 'market_sale', 'Manastone for sale')
        assert (result.delivery, result.state, bool(result)) == (
            'off', 'off', False)
        assert host.events == [('text', 'Manastone for sale')]
    finally:
        config.data['sounds'] = original


def test_dispatch_exposes_hidden_window_as_the_true_block_reason(monkeypatch):
    import vantage.helpers.application as application
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    host = _DispatchHost()
    original = config.data.get('sounds')
    config.data['sounds'] = {'routes': {'market_sale': {
        'delivery': 'sound', 'sound': 'builtin:crystal-ping', 'voice': ''}}}
    monkeypatch.setattr(
        app, 'audio_playback_allowed', lambda channel: channel != 'market',
        raising=False)
    monkeypatch.setattr(application, 'play_alert', lambda *a, **k: False)
    try:
        result = VantageApp.notify_event(
            host, 'market_sale', 'Manastone for sale', channel='market')
        assert result == NotificationDeliveryResult(
            'market_sale', 'sound', 'blocked', False, 'window hidden')
    finally:
        config.data['sounds'] = original


def test_explicit_sound_override_wins_but_empty_override_is_silent(monkeypatch):
    import vantage.helpers.application as application
    host = _DispatchHost()
    original = config.data.get('sounds')
    config.data['sounds'] = {'routes': {'smart_timer': {
        'delivery': 'voice', 'sound': 'builtin:soft-tick', 'voice': ''}}}
    monkeypatch.setattr(application, 'play_alert', lambda path, *a, **k: (
        host.events.append(('sound', path)) or True))
    monkeypatch.setattr(application, 'speak_text', lambda *a, **k: (
        host.events.append(('voice', a[0])) or True))
    try:
        inherited = VantageApp.notify_event(
            host, 'smart_timer', 'Frenzy due', sound_override=None)
        override = VantageApp.notify_event(
            host, 'smart_timer', 'Frenzy due',
            sound_override='builtin:portal-ping')
        silent = VantageApp.notify_event(
            host, 'smart_timer', 'Frenzy due', sound_override='')
        assert inherited.delivery == 'voice'
        assert override.delivery == 'sound'
        assert (silent.delivery, silent.state) == ('off', 'off')
        assert [event[0] for event in host.events].count('voice') == 1
        assert ('sound', 'builtin:portal-ping') in host.events
    finally:
        config.data['sounds'] = original


@pytest.mark.parametrize('route_key', sorted(EXPECTED_ROUTES))
def test_every_route_has_one_visual_and_one_sound_delivery(route_key, monkeypatch):
    import vantage.helpers.application as application
    host = _DispatchHost()
    original = config.data.get('sounds')
    config.data['sounds'] = {'routes': {route_key: {
        'delivery': 'sound', 'sound': 'builtin:soft-tick', 'voice': ''}}}
    monkeypatch.setattr(application, 'play_alert', lambda *a, **k: (
        host.events.append(('sound', a[0])) or True))
    monkeypatch.setattr(application, 'speak_text', lambda *a, **k: 1 / 0)
    try:
        assert VantageApp.notify_event(host, route_key, f'{route_key} happened')
        assert host.events == [
            ('text', f'{route_key} happened'),
            ('sound', 'builtin:soft-tick')]
    finally:
        config.data['sounds'] = original


def test_config_removes_afk_route_and_repairs_malformed_routes():
    original = copy.deepcopy(config.data)
    try:
        config.data.setdefault('timers', {})['afk_attacked_enabled'] = True
        config.data['timers']['safety_sound_enabled'] = True
        config.data.setdefault('sounds', {})['routes'] = {
            'tell_message': {'delivery': 'LOUD', 'sound': 123,
                             'voice': ['not a voice']}}
        config.verify_settings()
        assert 'afk_attacked_enabled' not in config.data['timers']
        assert 'safety_sound_enabled' not in config.data['timers']
        assert set(config.data['sounds']['routes']) == EXPECTED_ROUTES
        assert config.data['sounds']['routes']['tell_message'] == {
            'delivery': 'voice', 'sound': 'builtin:gentle-knock',
            'voice': ''}
    finally:
        config.data.clear()
        config.data.update(original)
