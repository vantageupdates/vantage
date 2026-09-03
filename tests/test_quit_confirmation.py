import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json

from PySide6.QtWidgets import QMessageBox

from vantage.helpers import config
from vantage.helpers.application import VantageApp


app = VantageApp([])
bar = app._parsers_dict['quickbar']
prompt_calls = []
quit_calls = []
app.quit = lambda: quit_calls.append('quit')


def answer_with(button):
    def question(parent, title, text, buttons, default):
        prompt_calls.append({
            'parent_is_quickbar': parent is bar,
            'title': title,
            'text': text,
            'has_yes': bool(buttons & QMessageBox.StandardButton.Yes),
            'has_no': bool(buttons & QMessageBox.StandardButton.No),
            'default_is_no': default == QMessageBox.StandardButton.No,
        })
        return button
    return question


QMessageBox.question = answer_with(QMessageBox.StandardButton.No)
cancelled = app.quit_vantage(parent=bar)
cancel_state = {
    'result': cancelled,
    'quit_calls': len(quit_calls),
    'app_exit': config.APP_EXIT,
}

QMessageBox.question = answer_with(QMessageBox.StandardButton.Yes)
confirmed = app.quit_vantage(parent=bar)
confirm_state = {
    'result': confirmed,
    'quit_calls': len(quit_calls),
    'app_exit': config.APP_EXIT,
}

# An explicitly authorized internal shutdown remains available to update and
# restart flows and must not open another manual warning.
config.APP_EXIT = False
bypassed = app.quit_vantage(confirm=False)
bypass_state = {
    'result': bypassed,
    'quit_calls': len(quit_calls),
    'prompt_calls': len(prompt_calls),
    'app_exit': config.APP_EXIT,
}

print(json.dumps({
    'prompts': prompt_calls,
    'cancel': cancel_state,
    'confirm': confirm_state,
    'bypass': bypass_state,
}))
"""


def test_manual_quit_warns_and_cancel_is_the_safe_default(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=40)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['cancel'] == {
        'result': False, 'quit_calls': 0, 'app_exit': False}
    assert result['confirm'] == {
        'result': True, 'quit_calls': 1, 'app_exit': True}
    assert result['bypass'] == {
        'result': True, 'quit_calls': 2, 'prompt_calls': 2,
        'app_exit': True}

    assert len(result['prompts']) == 2
    prompt = result['prompts'][0]
    assert prompt['parent_is_quickbar'] is True
    assert prompt['title'] == 'Quit Vantage?'
    assert prompt['has_yes'] is True
    assert prompt['has_no'] is True
    assert prompt['default_is_no'] is True
    assert 'Log monitoring, alerts, overlays, and phone sync will stop' in \
        prompt['text']
    assert 'timers are saved and keep counting' in prompt['text']
    assert 'EverQuest and WinEQ will remain open' in prompt['text']
