import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import datetime
import json
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QComboBox, QLineEdit, QWidget)
from vantage.helpers.application import VantageApp
from vantage.parsers.combat import CombatExportOptionsDialog
import vantage.parsers.combat as combat_module

output = Path(os.environ['VANTAGE_TEST_OUTPUT'])
output.mkdir(parents=True, exist_ok=True)
app = VantageApp([])
combat = app._parsers_dict['combat']
combat.show()
stamp = datetime.datetime.now()
combat.parse(stamp, 'Alice slashes a crystalline watcher for 1000 points of damage.')
combat.parse(stamp + datetime.timedelta(seconds=5), 'You kick a crystalline watcher for 500 points of damage.')
combat.parse(stamp + datetime.timedelta(seconds=10), 'Alice tries to slash a crystalline watcher, but misses!')
combat.parse(stamp + datetime.timedelta(seconds=20), 'You have slain a crystalline watcher!')
combat.mode.setCurrentIndex(combat.mode.findData('last'))
combat.refresh()
# Row zero is GamParse's Total row; select the first ranked attacker.
combat.tables['Overview'].selectRow(1)

options = dict(combat._output_options())
options.update({
    'output_channel': '/gu', 'top_players': 10,
    'plain_show_type': True, 'plain_show_crit': True,
    'plain_show_accuracy': True, 'html_theme': 'slate',
})
combat_module.config.data['combat']['export_options'] = options

# The compact header's primary export action is the GamParse-style EQ output.
combat.export.click()
eq_text = app.clipboard().text()
combat._copy_eq_summary(highlighted=True)
highlighted_text = app.clipboard().text()
combat._copy_detailed_text()
plain_text = app.clipboard().text()
combat._copy_current_bbcode()
bbcode = app.clipboard().text()
combat._copy_current_html()
mime = app.clipboard().mimeData()
html_clipboard = mime.hasHtml() and 'a crystalline watcher' in mime.html()
app.processEvents()

html_path = output / 'encounter.html'
xml_path = output / 'encounter.xml'
png_path = output / 'overview.png'
save_paths = iter((html_path, xml_path, png_path))
combat_module.QFileDialog.getSaveFileName = staticmethod(
    lambda *args, **kwargs: (str(next(save_paths)), ''))
combat._save_full_html()
combat._save_full_xml()
combat._save_current_view_png()

dialog = CombatExportOptionsDialog(options, combat)
dialog.show()
app.processEvents()
missing_dialog_tooltips = []
interactive = (QAbstractButton, QAbstractItemView, QComboBox, QLineEdit)
for widget in dialog.findChildren(QWidget):
    if (isinstance(widget, interactive) and widget.isVisibleTo(dialog)
            and not widget.toolTip().strip()):
        missing_dialog_tooltips.append(
            widget.accessibleName() or widget.objectName() or type(widget).__name__)
dialog_value = dialog.value()

menu_tooltips = []
for action in combat.export_menu.actions():
    if action.isSeparator():
        continue
    menu_tooltips.append(bool(action.toolTip()))
    if action.menu():
        menu_tooltips.extend(
            bool(child.toolTip()) for child in action.menu().actions()
            if not child.isSeparator())

print(json.dumps({
    'eq_prefix': eq_text.startswith('/gu '),
    'eq_primary_action': 'paste-ready EQ chat summary' in combat.export.toolTip(),
    'eq_has_players': 'Alice' in eq_text and 'You' in eq_text,
    'highlighted_one_rank': highlighted_text.count('#') == 1,
    'plain_shape': all(value in plain_text for value in (
        '--- DMG:', '------ Total:', 'Critical hits:', 'Accuracy:',
        'Produced by Vantage')),
    'bbcode_shape': '[table]' in bbcode and '[/table]' in bbcode,
    'html_clipboard': html_clipboard,
    'html_file': html_path.is_file() and '<!doctype html>' in html_path.read_text(encoding='utf-8'),
    'xml_file': xml_path.is_file() and '<vantage-combat-report>' in xml_path.read_text(encoding='utf-8'),
    'png_file': png_path.is_file() and png_path.stat().st_size > 100,
    'dialog_top': dialog_value['top_players'],
    'missing_dialog_tooltips': missing_dialog_tooltips,
    'menu_tooltips': menu_tooltips,
}))
dialog.close()
combat.close()
app.quit()
"""


def test_combat_output_formats_dialog_menu_and_files(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    env['VANTAGE_TEST_OUTPUT'] = str(tmp_path / 'exports')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        'eq_prefix': True,
        'eq_primary_action': True,
        'eq_has_players': True,
        'highlighted_one_rank': True,
        'plain_shape': True,
        'bbcode_shape': True,
        'html_clipboard': True,
        'html_file': True,
        'xml_file': True,
        'png_file': True,
        'dialog_top': 10,
        'missing_dialog_tooltips': [],
        'menu_tooltips': [True] * 17,
    }
