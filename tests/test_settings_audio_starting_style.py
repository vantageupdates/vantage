import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import copy
import json

from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.settings import SettingsWindow


app = VantageApp([])
routes = config.data['sounds']['routes']
routes['market_sale'].update({
    'delivery': 'sound', 'sound': 'portable:sounds/my-sale.wav', 'voice': ''})
routes['tell_message'].update({
    'delivery': 'voice', 'voice': 'My narrator'})
routes['death_loop']['delivery'] = 'off'
routes['spell_resisted'].update({
    'delivery': 'sound', 'sound': 'builtin:portal-ping'})
config.data['sounds']['starting_delivery'] = 'sound'
config.save()

settings = SettingsWindow()
settings.show()
app.processEvents()
before_apply = copy.deepcopy(config.data['sounds'])
settings.audio_starting_style.setCurrentIndex(
    settings.audio_starting_style.findData('voice'))
settings.apply_audio_starting_style_button.setFocus()
focus_before = app.focusWidget()
result = settings._apply_audio_starting_style()
app.processEvents()
preview_deliveries = {
    key: delivery.currentData()
    for key, delivery, _picker in settings._notification_route_widgets}
preview_pickers = {
    key: picker.currentData()
    for key, _delivery, picker in settings._notification_route_widgets}
status_after_apply = settings.audio_starting_style_status.text()
focus_after = app.focusWidget()
config_unchanged_during_preview = config.data['sounds'] == before_apply

settings._cancelled()
settings.show()
app.processEvents()
cancelled_deliveries = {
    key: delivery.currentData()
    for key, delivery, _picker in settings._notification_route_widgets}
cancelled_mode = settings.audio_starting_style.currentData()

settings.audio_starting_style.setCurrentIndex(
    settings.audio_starting_style.findData('voice'))
settings._apply_audio_starting_style()
settings._save()
saved = copy.deepcopy(config.data['sounds'])

settings.show()
app.processEvents()
reopened_mode = settings.audio_starting_style.currentData()
reopened_deliveries = {
    key: delivery.currentData()
    for key, delivery, _picker in settings._notification_route_widgets}
settings.audio_starting_style.setCurrentIndex(
    settings.audio_starting_style.findData('sound'))
settings._apply_audio_starting_style()
settings._cancelled()
unchanged_after_cancel = config.data['sounds'] == saved

print(json.dumps({
    'changed': list(result.changed_keys),
    'preserved': list(result.preserved_keys),
    'config_unchanged_during_preview': config_unchanged_during_preview,
    'preview_deliveries': preview_deliveries,
    'preview_pickers': preview_pickers,
    'status_after_apply': status_after_apply,
    'focus_preserved': focus_before is focus_after,
    'cancelled_deliveries': cancelled_deliveries,
    'cancelled_mode': cancelled_mode,
    'saved_mode': saved['starting_delivery'],
    'saved_routes': saved['routes'],
    'reopened_mode': reopened_mode,
    'reopened_deliveries': reopened_deliveries,
    'unchanged_after_cancel': unchanged_after_cancel,
    'label_buddy': settings.audio_starting_style_label.buddy()
                   is settings.audio_starting_style,
    'combo_accessible': settings.audio_starting_style.accessibleName(),
    'button_accessible':
        settings.apply_audio_starting_style_button.accessibleName(),
    'status_accessible': settings.audio_starting_style_status.accessibleName(),
    'tab_to_apply': settings.audio_starting_style.nextInFocusChain()
                    is settings.apply_audio_starting_style_button,
}))
settings.close()
app.quit()
"""


def test_audio_starting_style_is_safe_staged_persistent_and_accessible(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=45)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert set(result['changed']) == {
        'spell_fading', 'spell_worn_off', 'smart_timer',
        'raid_encounter', 'opendkp_auction'}
    assert len(result['preserved']) == 5
    assert result['config_unchanged_during_preview'] is True
    assert result['preview_deliveries']['spell_fading'] == 'voice'
    assert result['preview_deliveries']['market_sale'] == 'sound'
    assert result['preview_pickers']['market_sale'] == (
        'portable:sounds/my-sale.wav')
    assert result['preview_pickers']['tell_message'] == 'My narrator'
    assert '5 default routes changed' in result['status_after_apply']
    assert '5 routes preserved' in result['status_after_apply']
    assert result['focus_preserved'] is True

    assert result['cancelled_mode'] == 'sound'
    assert result['cancelled_deliveries']['spell_fading'] == 'sound'
    assert result['saved_mode'] == 'voice'
    assert result['saved_routes']['spell_fading']['delivery'] == 'voice'
    assert result['saved_routes']['market_sale']['sound'] == (
        'portable:sounds/my-sale.wav')
    assert result['saved_routes']['tell_message']['voice'] == 'My narrator'
    assert result['saved_routes']['death_loop']['delivery'] == 'off'
    assert result['reopened_mode'] == 'voice'
    assert result['reopened_deliveries']['spell_fading'] == 'voice'
    assert result['unchanged_after_cancel'] is True

    assert result['label_buddy'] is True
    assert result['combo_accessible'] == 'Starting notification style'
    assert result['button_accessible'] == (
        'Apply starting notification style to default routes')
    assert result['status_accessible'] == (
        'Starting notification style result')
    assert result['tab_to_apply'] is True
