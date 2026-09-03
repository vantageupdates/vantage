import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from pathlib import Path
from PySide6.QtWidgets import QFileDialog
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.portable import resolve_portable_path
from vantage.helpers.settings import SettingsWindow, GinaImportPreviewDialog
from vantage.parsers.spells import CustomTrigger

app = VantageApp([])
settings = SettingsWindow()
preview = GinaImportPreviewDialog([
    CustomTrigger(
        name='Entrance {S}', text='{S} has been entranced.',
        time='00:01:14', timer_type='countdown',
        alert_text='MEZ', text_color='#E5C267', enabled=False),
    CustomTrigger(
        name='Charm break', text='Your charm spell has worn off.',
        alert_text='CHARM BROKE', enabled=False),
])
settings.show()
preview.show()
app.processEvents()
settings._list_widget.setCurrentRow(4)
settings._list_widget.setFocus()
app.processEvents()
selected_rect = settings._list_widget.visualItemRect(
    settings._list_widget.currentItem())
nav_image = settings._list_widget.grab().toImage()
selected_center = nav_image.pixelColor(
    selected_rect.center()).getRgb()[:3]
indicator_pixels = [
    nav_image.pixelColor(x, selected_rect.center().y()).getRgb()[:3]
    for x in range(0, min(12, nav_image.width()))]
preview._rows[1][0].setChecked(False)
market_sound = next(
    combo for combo in settings._notification_sound_combos
    if combo.objectName() == 'sounds:market_sale')
market_sound.setCurrentIndex(market_sound.findData('builtin:portal-ping'))
timer_sound = next(
    combo for combo in settings._notification_sound_combos
    if combo.objectName() == 'sounds:timer_default')
source_wav = Path('data/sounds/amber_chime.wav').resolve()
QFileDialog.getOpenFileName = staticmethod(
    lambda *args, **kwargs: (str(source_wav), 'WAV Audio (*.wav)'))
settings._choose_notification_sound(timer_sound)
custom_sound = timer_sound.currentData()
trigger_saved = None
if settings._trigger_sound_routes:
    item_index, field_index, trigger_combo = settings._trigger_sound_routes[0]
    trigger_combo.setCurrentIndex(
        trigger_combo.findData('builtin:arcane-bloom'))
    trigger_saved = [item_index, field_index]
settings._save()
print(json.dumps({
    'settings_sections': settings._list_widget.count(),
    'section_names': [settings._list_widget.item(row).text()
                      for row in range(settings._list_widget.count())],
    'sound_routes': len(settings._notification_sound_combos),
    'sound_choices': [combo.count()
                      for combo in settings._notification_sound_combos],
    'market_sound_saved': config.data['sounds']['market_sale'],
    'custom_sound': custom_sound,
    'custom_sound_exists': resolve_portable_path(custom_sound).is_file(),
    'trigger_sound_saved': (
        config.data['spells']['custom_timers'][trigger_saved[0]][trigger_saved[1]]
        if trigger_saved else ''),
    'settings_stack': settings._widget_stack.count(),
    'preview_rows': preview.table.rowCount(),
    'selected': [trigger.name for trigger in preview.selected_triggers()],
    'preview_tooltip': bool(preview.table.toolTip()),
    'settings_icon_size': [settings._list_widget.iconSize().width(),
                           settings._list_widget.iconSize().height()],
    'settings_spacing': settings._list_widget.spacing(),
    'settings_uniform_rows': settings._list_widget.uniformItemSizes(),
    'settings_row_height': selected_rect.height(),
    'settings_page_sync': settings._widget_stack.currentIndex(),
    'settings_selected_center': selected_center,
    'settings_indicator_pixels': indicator_pixels,
}))
preview.close()
settings.close()
app.quit()
"""


def test_settings_and_gtt_preview_open_as_independent_dialogs(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result['settings_sections'] == result['settings_stack']
    assert result['settings_sections'] >= 8
    assert 'Sounds' in result['section_names']
    assert result['sound_routes'] >= 5
    assert min(result['sound_choices']) == 21
    assert max(result['sound_choices']) == 22
    assert result['market_sound_saved'] == 'builtin:portal-ping'
    assert result['custom_sound'] == 'portable:sounds/amber_chime.wav'
    assert result['custom_sound_exists'] is True
    assert result['trigger_sound_saved'] == 'builtin:arcane-bloom'
    assert result['preview_rows'] == 2
    assert result['selected'] == ['Entrance {S}']
    assert result['preview_tooltip'] is True
    assert result['settings_icon_size'] == [15, 15]
    assert result['settings_spacing'] == 1
    assert result['settings_uniform_rows'] is True
    assert 27 <= result['settings_row_height'] <= 30
    assert result['settings_page_sync'] == 4
    # The selected navigation row is a restrained blue-charcoal surface, not
    # the old solid brown form-field treatment.
    red, green, blue = result['settings_selected_center']
    assert blue > red and green > red
    # Its compact gold side marker remains visible, including with keyboard
    # focus on the navigation list.
    assert any(red > 120 and red > green > blue
               for red, green, blue in result['settings_indicator_pixels'])
