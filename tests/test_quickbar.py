import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
bar = app._parsers_dict['quickbar']
maps = app._parsers_dict['maps']
app.processEvents()

initial = {
    'orientation': bar._orientation,
    'design': [bar._design_size.width(), bar._design_size.height()],
    'tool_window': bool(bar.windowFlags() & Qt.WindowType.Tool),
    'always_on_top': bool(
        bar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
    'buttons': sorted(bar._buttons),
    'visible_buttons': sum(button.isVisible() for button in bar._buttons.values()),
    'tooltips_complete': all(
        button.toolTip() for button in
        [bar.orientation_button, *bar._buttons.values()]),
    'maps_checked': bar._buttons['maps'].isChecked(),
    'maps_dot': bar._enabled_dots['maps'].isVisible(),
    'maps_visible': maps.isVisible(),
    'scroll_areas': len(bar._surface.findChildren(QScrollArea)),
    'header_visible': bar._menu.isVisible(),
    'tick_readout_visible': bar.tick_readout.isVisible(),
    'support_highlight': bar._buttons['support'].property('Support'),
    'support_pulsing': bar._support_pulse_timer.isActive(),
    'support_tooltip': bar._buttons['support'].toolTip(),
    'support_icon_visible': not bar._buttons['support'].icon().isNull(),
    'sharp_surface': not bool(
        bar._scale_view.renderHints() &
        QPainter.RenderHint.SmoothPixmapTransform),
    'full_font_hinting': app.font().hintingPreference() ==
        QFont.HintingPreference.PreferFullHinting,
}

support_calls = []
app.show_support = lambda: support_calls.append('opened') or True
support_button = bar._buttons['support']
logical = support_button.mapTo(
    bar._surface, support_button.rect().center())
scene = bar._scale_proxy.mapToScene(QPointF(logical))
viewport = bar._scale_view.mapFromScene(scene)
QTest.mouseClick(
    bar._scale_view.viewport(), Qt.MouseButton.LeftButton, pos=viewport)
reload_calls = []
app.reload_ui = lambda: reload_calls.append('reloaded') or True
bar._trigger('reload_ui')

tick = app._parsers_dict['tick']
tick.sync_now()
app.processEvents()
tick_readout = {
    'text': bar.tick_countdown.text(),
    'progress': bar.tick_progress.value(),
    'tooltip': bar.tick_countdown.toolTip(),
}

header_height = bar._design_size.height()
bar.toggle_header(False)
app.processEvents()
menu, actions = bar._build_window_context_menu()
buttons_only = {
    'header_visible': bar._menu.isVisible(),
    'height': bar._design_size.height(),
    'window_height': bar.height(),
    'show_header_checked': actions['quickbar_header'].isChecked(),
    'roll_visible': actions['roll'].isVisible(),
}
menu.deleteLater()
bar.toggle_header(True)
app.processEvents()

bar._trigger('maps')
app.processEvents()
toggled = {
    'maps_checked': bar._buttons['maps'].isChecked(),
    'maps_dot': bar._enabled_dots['maps'].isVisible(),
    'maps_visible': maps.isVisible(),
}

config.data['quickbar']['orientation'] = 'vertical'
config.data['quickbar']['show_market'] = False
config.data['general']['reduce_motion'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
vertical = {
    'orientation': bar._orientation,
    'design': [bar._design_size.width(), bar._design_size.height()],
    'market_visible': bar._buttons['market'].isVisible(),
    'switch_tooltip': bar.orientation_button.toolTip(),
    'support_pulsing': bar._support_pulse_timer.isActive(),
    'support_pulse': bool(bar._buttons['support'].property('Pulse')),
}

settings = app._settings
settings.select_section('Quick Bar')
settings_page = {
    'selected': settings._list_widget.currentItem().text(),
    'orientation_control': settings._widget_stack.findChild(
        type(settings._section_combo), 'quickbar:orientation') is not None,
    'header_control': settings._widget_stack.findChild(
        __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
        'quickbar:show_header') is not None,
    'tick_control': settings._widget_stack.findChild(
        __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
        'quickbar:show_server_tick') is not None,
    'all_item_controls': all(
        settings._widget_stack.findChild(
            __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
            f'quickbar:show_{key}') is not None
        for key in QUICKBAR_ITEM_KEYS),
}

print(json.dumps({
    'initial': initial,
    'tick_readout': tick_readout,
    'buttons_only': buttons_only,
    'header_height': header_height,
    'toggled': toggled,
    'vertical': vertical,
    'settings': settings_page,
    'support_calls': support_calls,
    'reload_calls': reload_calls,
}))
app.quit()
"""


VERTICAL_AND_PULSE_SCRIPT = r"""
import json
from PySide6.QtCore import Qt
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar.show()
app.processEvents()

position_before = [bar.x(), bar.y()]
config.data['quickbar']['orientation'] = 'vertical'
config.data['quickbar']['show_header'] = True
config.data['quickbar']['show_server_tick'] = True
config.data['quickbar']['show_support'] = True
config.data['general']['reduce_motion'] = False
app._signals['settings'].config_updated.emit()
app.processEvents()

support = bar._buttons['support']
animation = bar._support_pulse_timer
vertical_header = {
    'design': [bar._design_size.width(), bar._design_size.height()],
    'window_width': bar.width(),
    'minimum_width': bar.minimumWidth(),
    'action_hint_width': bar.action_frame.sizeHint().width(),
    'header_required_width': bar._compact_header_width(),
    'position': [bar.x(), bar.y()],
    'header_visible': bar._menu.isVisible(),
    'logo_visible': bar._title_icon.isVisible(),
    'logo_pixmap': not bar._title_icon.pixmap().isNull(),
    'frame_visible': bar._button.isVisible(),
    'title_visible': bar._title.isVisible(),
    'roll_visible': bar._roll_button.isVisible(),
    'minimize_visible': bar._minimize_button.isVisible(),
    'targets_24': all(
        button.width() == 24 and button.height() == 24
        for button in [bar.orientation_button, *bar._buttons.values()]),
    'always_tooltips': bar.testAttribute(
        Qt.WidgetAttribute.WA_AlwaysShowToolTips),
    'surface_always_tooltips': bar._surface.testAttribute(
        Qt.WidgetAttribute.WA_AlwaysShowToolTips),
    'tick_width': bar.tick_readout.width(),
    'tick_countdown_width': bar.tick_countdown.width(),
}

bar.toggle_header(False)
app.processEvents()
vertical_header_hidden = {
    'design_width': bar._design_size.width(),
    'header_visible': bar._menu.isVisible(),
    'tick_visible': bar.tick_readout.isVisible(),
}

config.data['quickbar']['show_server_tick'] = False
app._signals['settings'].config_updated.emit()
app.processEvents()
vertical_without_tick = {
    'design_width': bar._design_size.width(),
    'window_width': bar.width(),
    'minimum_width': bar.minimumWidth(),
}

bar.toggle_header(True)
config.data['quickbar']['show_server_tick'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
pulse_visible = {
    'running': animation.isActive(),
    'button_icon_visible': not support.icon().isNull(),
    'pulse_property': bool(support.property('Pulse')),
    'interval': animation.interval(),
}

config.data['quickbar']['show_support'] = False
app._signals['settings'].config_updated.emit()
app.processEvents()
pulse_support_hidden = {
    'running': animation.isActive(),
    'pulse_property': bool(support.property('Pulse')),
}

config.data['quickbar']['show_support'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
pulse_support_restored = animation.isActive()
bar.hide()
app.processEvents()
pulse_bar_hidden = {
    'running': animation.isActive(),
    'pulse_property': bool(support.property('Pulse')),
}
bar.show()
app.processEvents()
pulse_bar_restored = animation.isActive()

config.data['general']['reduce_motion'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
pulse_reduced_motion = {
    'running': animation.isActive(),
    'pulse_property': bool(support.property('Pulse')),
}

# A rapid orientation double-click is one gesture. It must not toggle twice
# or let the compact strip retain an accidentally oversized geometry.
bar.toggle_orientation()
bar.toggle_orientation()
app.processEvents()
double_click_orientation = bar._orientation
bar.resize(bar._design_size.width() * 4, bar._design_size.height() * 4)
bar._update_uniform_scale()
app.processEvents()
compact_after_oversize = {
    'window': [bar.width(), bar.height()],
    'design': [bar._design_size.width(), bar._design_size.height()],
}

config.data['quickbar']['orientation'] = 'horizontal'
app._signals['settings'].config_updated.emit()
app.processEvents()
horizontal_restored = {
    'orientation': bar._orientation,
    'design': [bar._design_size.width(), bar._design_size.height()],
    'logo_visible': bar._title_icon.isVisible(),
    'title_visible': bar._title.isVisible(),
    'frame_visible': bar._button.isVisible(),
    'minimize_visible': bar._minimize_button.isVisible(),
}

print(json.dumps({
    'position_before': position_before,
    'vertical_header': vertical_header,
    'vertical_header_hidden': vertical_header_hidden,
    'vertical_without_tick': vertical_without_tick,
    'pulse_visible': pulse_visible,
    'pulse_support_hidden': pulse_support_hidden,
    'pulse_support_restored': pulse_support_restored,
    'pulse_bar_hidden': pulse_bar_hidden,
    'pulse_bar_restored': pulse_bar_restored,
    'pulse_reduced_motion': pulse_reduced_motion,
    'double_click_orientation': double_click_orientation,
    'compact_after_oversize': compact_after_oversize,
    'horizontal_restored': horizontal_restored,
}))
app.quit()
"""


def test_quickbar_config_defaults_are_safe_and_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'config.json'))
    original = config.data
    config.data = {}
    try:
        config.verify_settings()
        quickbar = config.data['quickbar']
        assert quickbar['orientation'] == 'horizontal'
        assert quickbar['always_on_top'] is True
        assert quickbar['clickthrough'] is False
        assert quickbar['opacity'] == 92
        assert quickbar['show_header'] is True
        assert quickbar['show_server_tick'] is True
        assert all(quickbar[f'show_{key}'] for key in QUICKBAR_ITEM_KEYS)
        assert quickbar['support_visibility_version'] == 1
    finally:
        config.data = original


def test_quickbar_uses_one_distinct_icon_per_action():
    from vantage.helpers.quickbar_items import QUICKBAR_ITEMS

    icons = [icon for _key, _label, icon, _group in QUICKBAR_ITEMS]
    assert len(icons) == len(set(icons))
    assert all(icon.startswith("ph-") for icon in icons)


def test_quickbar_repairs_hidden_support_once_and_preserves_later_choice(
        tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_filename', str(tmp_path / 'config.json'))
    original = config.data
    try:
        config.data = {'quickbar': {'show_support': False}}
        config.verify_settings()
        assert config.data['quickbar']['show_support'] is True
        assert config.data['quickbar']['support_visibility_version'] == 1

        config.data['quickbar']['show_support'] = False
        config.verify_settings()
        assert config.data['quickbar']['show_support'] is False
    finally:
        config.data = original


def test_quickbar_controls_windows_orientation_and_visibility(tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    initial = result['initial']
    assert initial['orientation'] == 'horizontal'
    assert initial['design'][0] > initial['design'][1]
    assert initial['tool_window'] is True
    assert initial['always_on_top'] is True
    assert initial['buttons'] == sorted(QUICKBAR_ITEM_KEYS)
    assert initial['visible_buttons'] == len(QUICKBAR_ITEM_KEYS)
    assert initial['tooltips_complete'] is True
    assert initial['maps_checked'] == initial['maps_visible'] is False
    assert initial['maps_dot'] is False
    assert initial['scroll_areas'] == 0
    assert initial['header_visible'] is True
    assert initial['tick_readout_visible'] is True
    assert initial['support_highlight'] is True
    assert initial['support_pulsing'] is True
    assert 'default browser' in initial['support_tooltip']
    assert initial['support_icon_visible'] is True
    assert initial['sharp_surface'] is True
    assert initial['full_font_hinting'] is True
    assert result['support_calls'] == ['opened']
    assert result['reload_calls'] == ['reloaded']

    assert result['tick_readout']['text'] == 'TICK'
    assert result['tick_readout']['progress'] == 1000
    assert 'click to toggle' in result['tick_readout']['tooltip']
    assert result['buttons_only']['header_visible'] is False
    assert result['buttons_only']['height'] < result['header_height']
    assert result['buttons_only']['window_height'] <= \
        result['buttons_only']['height'] + 1
    assert result['buttons_only']['show_header_checked'] is False
    assert result['buttons_only']['roll_visible'] is False

    assert result['toggled'] == {
        'maps_checked': True,
        'maps_dot': True,
        'maps_visible': True,
    }
    vertical = result['vertical']
    assert vertical['orientation'] == 'vertical'
    assert vertical['design'][1] > vertical['design'][0]
    assert vertical['market_visible'] is False
    assert 'horizontal' in vertical['switch_tooltip']
    assert vertical['support_pulsing'] is False
    assert vertical['support_pulse'] is False
    assert result['settings'] == {
        'selected': 'Quick Bar',
        'orientation_control': True,
        'header_control': True,
        'tick_control': True,
        'all_item_controls': True,
    }


def test_vertical_quickbar_shrinkwrap_logo_tooltips_and_pulse_lifecycle(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', VERTICAL_AND_PULSE_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    vertical = result['vertical_header']
    assert vertical['design'][0] == 30
    assert vertical['window_width'] == 30
    assert vertical['minimum_width'] == 30
    assert vertical['action_hint_width'] == 30
    assert vertical['header_required_width'] <= 30
    assert vertical['position'] == result['position_before']
    assert vertical['header_visible'] is True
    assert vertical['logo_visible'] is True
    assert vertical['logo_pixmap'] is True
    assert vertical['targets_24'] is True
    assert vertical['always_tooltips'] is True
    assert vertical['surface_always_tooltips'] is True
    assert vertical['tick_width'] == 24
    assert vertical['tick_countdown_width'] == 20
    assert vertical['frame_visible'] is False
    assert vertical['title_visible'] is False
    assert vertical['roll_visible'] is False
    assert vertical['minimize_visible'] is False

    assert result['vertical_header_hidden'] == {
        'design_width': 30,
        'header_visible': False,
        'tick_visible': True,
    }
    assert result['vertical_without_tick'] == {
        'design_width': 30,
        'window_width': 30,
        'minimum_width': 30,
    }
    assert result['pulse_visible'] == {
        'running': True,
        'button_icon_visible': True,
        'pulse_property': True,
        'interval': 520,
    }
    assert result['pulse_support_hidden'] == {
        'running': False,
        'pulse_property': False,
    }
    assert result['pulse_support_restored'] is True
    assert result['pulse_bar_hidden'] == {
        'running': False,
        'pulse_property': False,
    }
    assert result['pulse_bar_restored'] is True
    assert result['pulse_reduced_motion'] == {
        'running': False,
        'pulse_property': False,
    }
    assert result['double_click_orientation'] == 'horizontal'
    assert result['compact_after_oversize']['window'] == \
        result['compact_after_oversize']['design']
    horizontal = result['horizontal_restored']
    assert horizontal['orientation'] == 'horizontal'
    assert horizontal['design'][0] > horizontal['design'][1]
    assert horizontal['logo_visible'] is True
    assert horizontal['title_visible'] is True
    assert horizontal['frame_visible'] is True
    assert horizontal['minimize_visible'] is True
