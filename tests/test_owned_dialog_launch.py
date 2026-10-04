"""Native launch tests with disposable profiles and no external services."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(script):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "tests"), str(ROOT / "src")))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=ROOT, env=env,
        check=False, capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


SCOPED_SCRIPT = r"""
import json
from native_audit_fixture import isolate
isolate()
from PySide6.QtWidgets import QMenu
from vantage.helpers.application import VantageApp
from vantage.helpers import parser as parser_module

app = VantageApp([])
class SelectOwnedSettingsMenu(QMenu):
    def exec(self, *_args):
        return next(action for action in self.actions()
                    if action.text().startswith('Open '))
parser_module.QMenu = SelectOwnedSettingsMenu
results = {}
owners = {
    'maps': 'Maps', 'spells': 'Buffs & Triggers', 'timers': 'Smart Timers',
    'combat': 'Combat', 'market': 'Market', 'quickbar': 'Quick Bar',
    'tick': 'Appearance', 'random_parser': 'Appearance',
}
for name, section in owners.items():
    owner = app._parsers_dict[name]
    owner._auto_hide_menu = False
    owner._set_collapsed(False)
    owner._set_header_revealed(True)
    owner.show()
    app.processEvents()
    owner._settings_button.click()
    app.processEvents()
    dialog = app._feature_settings_instances[section]
    first_dialog = dialog
    launch = {
        'visible': dialog.isVisible(), 'section': dialog._scoped_section,
        'sections': [dialog._list_widget.item(index).text()
                     for index in range(dialog._list_widget.count())],
        'navigation_hidden': dialog._list_widget.isHidden(),
        'parent_is_owner': dialog.parentWidget() is owner,
        'recorded_owner': dialog._feature_settings_owner is owner,
        'title': dialog.windowTitle(),
    }
    dialog.reject()
    app.processEvents()
    launch['focus_returned'] = owner._settings_button.hasFocus()
    owner._settings_button.click()
    app.processEvents()
    launch['same_dialog'] = app._feature_settings_instances[section] is first_dialog
    dialog.reject()
    owner.hide()
    results[name] = launch
heals = app._parsers_dict['heals']
heals._auto_hide_menu = False
heals._set_header_revealed(True)
heals._settings_button.click()
app.processEvents()
results['heals'] = {
    'inline_settings': heals.tabs.currentWidget() is heals.settings_tab,
    'no_owned_dialog': 'Heal Chain' not in app._feature_settings_instances,
}
results['global_settings_stayed_lazy'] = app._settings_instance is None
print(json.dumps(results))
app.quit()
"""


def test_header_gears_launch_the_owned_settings_and_restore_focus():
    result = _run(SCOPED_SCRIPT)
    expected = {
        "maps": "Maps", "spells": "Buffs & Triggers", "timers": "Smart Timers",
        "combat": "Combat", "market": "Market", "quickbar": "Quick Bar",
        "tick": "Appearance", "random_parser": "Appearance",
    }
    for owner, section in expected.items():
        launch = result[owner]
        assert launch["section"] == section
        assert launch["sections"] == [section]
        assert launch["title"] == f"Vantage · {section} Settings"
        for field in ("visible", "navigation_hidden", "parent_is_owner",
                      "recorded_owner", "focus_returned", "same_dialog"):
            assert launch[field] is True, (owner, field, launch)
    assert result["heals"] == {"inline_settings": True, "no_owned_dialog": True}
    assert result["global_settings_stayed_lazy"] is True


SIGN_IN_SCRIPT = r"""
import json
from types import SimpleNamespace
from native_audit_fixture import isolate
isolate()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget
from vantage.parsers.opendkp import OpenDKP, OpenDkpLoginDialog

app = QApplication([])
real_exec = OpenDkpLoginDialog.exec
results = {}
for outcome, accepted, login_succeeds in (
        ('accepted', True, True), ('rejected', False, True),
        ('login_failed', True, False)):
    parent = QWidget()
    calls, saves, prompts = [], [], []
    parent.client = SimpleNamespace(
        slug='synthetic-guild', username='fallback-user',
        login=lambda username, password: calls.append((username, password)) or login_succeeds)
    parent._guild_name = lambda: 'Synthetic Guild'
    parent._profile = lambda: {'username': 'remembered-user'}
    parent._save_profile = lambda **values: saves.append(values)

    def execute(dialog):
        prompts.append({
            'title': dialog.windowTitle(),
            'remembered_username': dialog.username.text(),
            'password_masked': dialog.password.echoMode() == QLineEdit.EchoMode.Password,
            'parent_is_owner': dialog.parentWidget() is parent,
        })
        def finish():
            dialog.username.setText('  fixture-user  ')
            dialog.password.setText('synthetic-only-password')
            dialog.accept() if accepted else dialog.reject()
        QTimer.singleShot(0, finish)
        return real_exec(dialog)

    OpenDkpLoginDialog.exec = execute
    OpenDKP._sign_in(parent)
    results[outcome] = {'prompts': prompts, 'calls': calls, 'saves': saves}
    parent.close()

parent = QWidget()
parent.client = SimpleNamespace(slug='')
OpenDkpLoginDialog.exec = lambda _dialog: (_ for _ in ()).throw(
    AssertionError('A guild must be selected before sign-in'))
OpenDKP._sign_in(parent)
results['no_guild_does_not_prompt'] = True
print(json.dumps(results))
app.quit()
"""


def test_opendkp_sign_in_acceptance_rejection_and_failed_login_use_fake_session():
    result = _run(SIGN_IN_SCRIPT)
    for outcome in ("accepted", "rejected", "login_failed"):
        assert result[outcome]["prompts"] == [{
            "title": "Sign in · Synthetic Guild",
            "remembered_username": "remembered-user", "password_masked": True,
            "parent_is_owner": True,
        }]
    assert result["accepted"]["calls"] == [["fixture-user", "synthetic-only-password"]]
    assert result["accepted"]["saves"] == [{"username": "fixture-user"}]
    assert result["rejected"]["calls"] == result["rejected"]["saves"] == []
    assert result["login_failed"]["calls"] == [["fixture-user", "synthetic-only-password"]]
    assert result["login_failed"]["saves"] == []
    assert result["no_guild_does_not_prompt"] is True


def test_native_audit_fixture_keeps_eq_paths_synthetic_after_application_import():
    result = _run(r"""
import json
from pathlib import Path
from urllib.error import URLError
import urllib.request
from native_audit_fixture import isolate
profile = isolate()
from vantage.helpers.application import VantageApp
from vantage.helpers import config, ui_profile_manager
app = VantageApp([])
panel = app._parsers_dict['vantage_ui']
eq_root = Path(panel.path_edit.text()).resolve()
try:
    urllib.request.urlopen('https://invalid.example')
except URLError as error:
    python_network_blocked = 'synthetic native audit' in str(error)
else:
    python_network_blocked = False
result = {
    'eq_path_is_synthetic': eq_root.is_relative_to(profile),
    'log_path_is_synthetic': Path(config.data['general']['eq_log_dir']).resolve().is_relative_to(profile),
    'characters': [item.character for item in ui_profile_manager.discover_character_profiles(eq_root)],
    'audio_muted': config.data['general']['audio_muted'],
    'master_volume': config.data['general']['master_volume'],
    'auto_update': config.data['vantage_ui']['auto_update'],
    'auto_apply_profiles': config.data['vantage_ui']['auto_apply_profiles'],
    'pending_profile_sync': config.data['vantage_ui']['pending_profile_sync'],
    'automatic_timer_active': panel._automatic_timer.isActive(),
    'profile_sync_timer_active': panel._profile_sync_timer.isActive(),
    'python_network_blocked': python_network_blocked,
}
print(json.dumps(result))
app.quit()
""")
    assert result == {
        "eq_path_is_synthetic": True, "log_path_is_synthetic": True,
        "characters": ["AuditCleric", "AuditWarrior", "AuditWizard"],
        "audio_muted": True, "master_volume": 0, "auto_update": False,
        "auto_apply_profiles": False, "pending_profile_sync": {},
        "automatic_timer_active": False, "profile_sync_timer_active": False,
        "python_network_blocked": True,
    }
