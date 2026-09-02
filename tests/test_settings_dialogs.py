import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from vantage.helpers.application import VantageApp
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
preview._rows[1][0].setChecked(False)
print(json.dumps({
    'settings_sections': settings._list_widget.count(),
    'settings_stack': settings._widget_stack.count(),
    'preview_rows': preview.table.rowCount(),
    'selected': [trigger.name for trigger in preview.selected_triggers()],
    'preview_tooltip': bool(preview.table.toolTip()),
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
    assert result['preview_rows'] == 2
    assert result['selected'] == ['Entrance {S}']
    assert result['preview_tooltip'] is True
