import json
import os
from pathlib import Path
import subprocess
import sys

from vantage.helpers import config
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS, QUICKBAR_ITEMS


ROOT = Path(__file__).resolve().parents[1]


SCRIPT = r"""
import json
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QAccessible, QFont, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QLabel, QScrollArea, QSlider, QToolButton, QWidgetAction)
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.audio import (
    audio_muted, set_audio_muted, set_master_volume)
from vantage.helpers.icons import game_icon
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS

config.data['general']['startup_window_state'] = 'normal'
app = VantageApp([])
bar = app._parsers_dict['quickbar']
maps = app._parsers_dict['maps']
app.processEvents()

def relative_luminance(color):
    channels = [int(color[index:index + 2], 16) / 255
                for index in (1, 3, 5)]
    channels = [
        value / 12.92 if value <= 0.04045 else
        ((value + 0.055) / 1.055) ** 2.4
        for value in channels]
    return (0.2126 * channels[0] + 0.7152 * channels[1] +
            0.0722 * channels[2])

def contrast_ratio(first, second):
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True)
    return round((lighter + 0.05) / (darker + 0.05), 2)

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
    'support_is_last': bar.action_layout.itemAt(
        bar.action_layout.count() - 1).widget() is bar._buttons['support'],
    'dialog_actions_checkable': all(
        bar._buttons[key].isCheckable() for key in bar._DIALOG_ACTIONS),
    'volume_visible': bar.volume_rocker.isVisible(),
    'volume_priority': bar.volume_rocker.property('HeaderPriority'),
    'volume_compact': bar.volume_rocker.width() <= 130,
    'volume_control_size': [
        bar.volume_rocker.width(), bar.volume_rocker.height()],
    'volume_slider_size': [
        bar.volume_slider.width(), bar.volume_slider.height()],
    'mute_semantics': {
        'native': isinstance(bar.master_mute_button, QToolButton),
        'checkable': bar.master_mute_button.isCheckable(),
        'checked': bar.master_mute_button.isChecked(),
        'name': bar.master_mute_button.accessibleName(),
        'description': bar.master_mute_button.accessibleDescription(),
        'size': [bar.master_mute_button.width(),
                 bar.master_mute_button.height()],
        'dot_state': bar._master_mute_dot.property('State'),
        'dot_visible': bar._master_mute_dot.isVisible(),
        'icon_visible': not bar.master_mute_button.icon().isNull(),
        'focus_style': ':focus' in bar.master_mute_button.styleSheet(),
    },
    'volume_semantics': {
        'native': isinstance(bar.volume_slider, QSlider),
        'horizontal': (
            bar.volume_slider.orientation() == Qt.Orientation.Horizontal),
        'range': [bar.volume_slider.minimum(), bar.volume_slider.maximum()],
        'steps': [
            bar.volume_slider.singleStep(), bar.volume_slider.pageStep()],
        'name': bar.volume_slider.accessibleName(),
        'description': bar.volume_slider.accessibleDescription(),
        'role_slider': QAccessible.queryAccessibleInterface(
            bar.volume_slider).role() == QAccessible.Role.Slider,
        'focusable': (
            bar.volume_slider.focusPolicy() != Qt.FocusPolicy.NoFocus),
        'label_focusable': (
            bar.volume_value_label.focusPolicy() != Qt.FocusPolicy.NoFocus),
        'label_width': bar.volume_value_label.width(),
        'label_required': (
            bar.volume_value_label.fontMetrics().horizontalAdvance('100%') +
            8),
        'custom_paint': type(bar.volume_slider).__name__ ==
                        'QuickBarVolumeSlider',
        'platform_parts_removed': '::' not in bar.volume_slider.styleSheet(),
        'style_has_white': any(
            token in bar.volume_slider.styleSheet().upper()
            for token in ('#FFF', 'WHITE', 'IVORY')),
        'visual_palette': dict(bar.volume_slider.VISUAL_COLORS),
        'palette_has_near_white': any(
            min(int(value[index:index + 2], 16)
                for index in (1, 3, 5)) >= 235
            for value in bar.volume_slider.VISUAL_COLORS.values()),
        'contrast': [
            contrast_ratio('#687A86', '#182127'),
            contrast_ratio('#9A7541', '#182127'),
            contrast_ratio('#362916', '#9A7541'),
            contrast_ratio('#C6A15A', '#182127'),
            contrast_ratio('#D0A45B', '#11181D'),
        ],
    },
    'header_tab_order': [
        bar._button.nextInFocusChain() is bar.master_mute_button,
        bar.master_mute_button.nextInFocusChain() is bar.volume_slider,
        bar.volume_slider.nextInFocusChain() is bar._settings_button,
        bar._settings_button.nextInFocusChain() is bar._roll_button,
        bar._roll_button.nextInFocusChain() is bar._minimize_button,
    ],
}

large_label = QLabel()
large_font = QFont(large_label.font())
large_font.setPointSizeF(max(14.0, large_font.pointSizeF() * 1.5))
large_label.setFont(large_font)
large_label_width = bar._configure_percentage_label(large_label)
large_slider_width = bar._compact_volume_slider_width(large_label_width)
initial['large_font_layout'] = {
    'label_width': large_label_width,
    'label_required': large_label.fontMetrics().horizontalAdvance('100%') + 8,
    'slider_width': large_slider_width,
    'composite_width': 2 + 24 + 2 + large_slider_width + 2 +
                       large_label_width + 2,
}

# The native header slider is a live view of the same master volume used by
# Settings. Dragging updates audio continuously but writes once on release;
# keyboard bursts coalesce through the short save timer. Master Mute is
# deliberately independent.
def focus_header_control(control):
    bar.activateWindow()
    bar._scale_scene.setFocusItem(bar._scale_proxy)
    control.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    return bar._surface.focusWidget()

set_master_volume(50)
app._signals['settings'].config_updated.emit()
app.processEvents()
volume_from_settings = {
    'value': bar.volume_slider.value(),
    'text': bar.volume_value_label.text(),
    'name': bar.volume_slider.accessibleName(),
    'description': bar.volume_slider.accessibleDescription(),
}

real_config_save = config.save
save_calls = []
def tracked_config_save():
    save_calls.append(config.data['general']['master_volume'])
    return real_config_save()
config.save = tracked_config_save
set_audio_muted(True)
bar.refresh_state()

slider = bar.volume_slider
slider_start = QPoint(slider.width() // 2, slider.height() // 2)
slider_end = QPoint(slider.width() - 6, slider.height() // 2)
QTest.mousePress(
    slider, Qt.MouseButton.LeftButton, pos=slider_start)
QTest.mouseMove(slider, slider_end, delay=20)
app.processEvents()
pointer_during_drag = {
    'value': slider.value(),
    'writes': list(save_calls),
}
QTest.mouseRelease(
    slider, Qt.MouseButton.LeftButton, pos=slider_end)
app.processEvents()
with open(config._filename, encoding='utf-8') as saved_file:
    saved_after_pointer = json.load(saved_file)['general']['master_volume']
volume_after_pointer = {
    'live_value': slider.value(),
    'saved_value': saved_after_pointer,
    'text': bar.volume_value_label.text(),
    'muted': audio_muted(),
    'writes': list(save_calls),
}

# Native key behavior includes exact 1% arrows, 10% pages, and Home/End.
set_audio_muted(False)
set_master_volume(50)
bar.refresh_state()
bar._volume_save_timer.stop()
save_calls.clear()
focus_header_control(slider)
QTest.keyClick(slider, Qt.Key.Key_Home)
home_value = slider.value()
QTest.keyClick(slider, Qt.Key.Key_PageUp)
page_value = slider.value()
QTest.keyClick(slider, Qt.Key.Key_PageDown)
page_down_value = slider.value()
QTest.keyClick(slider, Qt.Key.Key_PageUp)
QTest.keyClick(slider, Qt.Key.Key_Right)
arrow_value = slider.value()
QTest.keyClick(slider, Qt.Key.Key_End)
keyboard_before_debounce = list(save_calls)
QTest.qWait(220)
app.processEvents()
volume_after_keyboard = {
    'home': home_value,
    'page_up': page_value,
    'page_down': page_down_value,
    'right': arrow_value,
    'end': slider.value(),
    'text': bar.volume_value_label.text(),
    'writes_before_debounce': keyboard_before_debounce,
    'writes_after_debounce': list(save_calls),
    'focused': bar._surface.focusWidget() is slider,
    'enabled_at_boundary': slider.isEnabled(),
}

# Wheel input is ignored until the slider itself has explicit keyboard focus.
set_master_volume(50)
bar.refresh_state()
bar._volume_save_timer.stop()
bar._settings_button.setFocus(Qt.FocusReason.TabFocusReason)
app.processEvents()
wheel_pos = QPointF(slider.rect().center())
wheel_global = QPointF(slider.mapToGlobal(slider.rect().center()))
unfocused_wheel = QWheelEvent(
    wheel_pos, wheel_global, QPoint(), QPoint(0, 120),
    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    Qt.ScrollPhase.ScrollUpdate, False)
QApplication.sendEvent(slider, unfocused_wheel)
wheel_unfocused_value = slider.value()
focus_header_control(slider)
focused_wheel = QWheelEvent(
    wheel_pos, wheel_global, QPoint(), QPoint(0, 120),
    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    Qt.ScrollPhase.ScrollUpdate, False)
QApplication.sendEvent(slider, focused_wheel)
wheel_guard = {
    'unfocused': wheel_unfocused_value,
    'focused_changed': slider.value() != wheel_unfocused_value,
}

# External Settings refresh updates both value and readout without feeding a
# save back through the slider.
bar._volume_save_timer.stop()
save_calls.clear()
set_master_volume(65)
app._signals['settings'].config_updated.emit()
app.processEvents()
volume_resynced = {
    'value': slider.value(),
    'text': bar.volume_value_label.text(),
    'label_name': bar.volume_value_label.accessibleName(),
    'writes': list(save_calls),
    'muted': audio_muted(),
}
config.save = real_config_save

# When the composite slider moves into overflow, remember and restore the
# focused slider itself. The overflow menu supplies the same native control.
original_design = QSize(bar._design_size)
original_logical_width = bar._logical_surface_width
focus_header_control(slider)
bar._design_size = QSize(180, original_design.height())
bar._logical_surface_width = 180
bar._pack_header_controls()
bar._overflow_volume_slider.setValue(72)
app.processEvents()
overflow_live_value = {
    'master': config.data['general']['master_volume'],
    'header': slider.value(),
    'overflow': bar._overflow_volume_slider.value(),
    'label': bar.volume_value_label.text(),
}
bar._volume_save_timer.stop()
overflow_focus = {
    'rocker_hidden': bar.volume_rocker.isHidden(),
    'overflow_visible': bar._header_overflow_button.isVisible(),
    'saved_child': bar._header_focus_restore is slider,
    'overflow_slider': (
        bar._overflow_volume_slider is not None and
        bar._overflow_volume_slider.accessibleName() ==
        'Notification volume'),
    'overflow_mute': (
        bar._overflow_master_mute_button is not None and
        bar._overflow_master_mute_button.accessibleName() ==
        'Master Mute: OFF'),
    'live_value': overflow_live_value,
    'menu_action_count': len(bar._header_overflow_menu.actions()),
    'volume_widget_actions': sum(
        isinstance(action, QWidgetAction) and
        action.defaultWidget() is not None
        for action in bar._header_overflow_menu.actions()),
    'empty_actions': sum(
        not action.text().strip() and
        (not isinstance(action, QWidgetAction) or
         action.defaultWidget() is None)
        for action in bar._header_overflow_menu.actions()),
    'tab_order': [
        bar._button.nextInFocusChain() is bar._header_overflow_button,
        bar._header_overflow_button.nextInFocusChain() is
        bar._settings_button,
        bar._settings_button.nextInFocusChain() is bar._roll_button,
        bar._roll_button.nextInFocusChain() is bar._minimize_button,
    ],
}

# Open the actual QMenu and exercise its embedded QWidgetAction by keyboard.
# The about-to-show focus transfer must put the real focus widget on the
# native slider before any key is sent.
menu_keyboard = {}
def exercise_overflow_menu():
    control = bar._overflow_volume_slider
    mute_control = bar._overflow_master_mute_button
    menu_keyboard['menu_visible'] = bar._header_overflow_menu.isVisible()
    menu_keyboard['focus_proxy'] = (
        bar._header_overflow_menu.focusProxy() is mute_control)
    menu_keyboard['initial_focus'] = QApplication.focusWidget() is mute_control
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Backtab)
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Space)
    menu_keyboard['mute_on'] = {
        'checked': mute_control.isChecked(),
        'state': mute_control.property('State'),
        'dot': bar._overflow_master_mute_dot.property('State'),
        'audio_muted': audio_muted(),
        'menu_open': bar._header_overflow_menu.isVisible(),
    }
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Space)
    menu_keyboard['mute_off'] = {
        'checked': mute_control.isChecked(),
        'state': mute_control.property('State'),
        'dot': bar._overflow_master_mute_dot.property('State'),
        'audio_muted': audio_muted(),
    }
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Tab)
    menu_keyboard['tab_focus_requested'] = (
        control._last_focus_reason == Qt.FocusReason.TabFocusReason)
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Home)
    home = control.value()
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_PageUp)
    page_up = control.value()
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_Right)
    arrow = control.value()
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_End)
    end = control.value()
    QTest.keyClick(bar._header_overflow_menu, Qt.Key.Key_PageDown)
    page_down = control.value()
    menu_keyboard['values'] = [home, page_up, arrow, end, page_down]
    menu_keyboard['menu_stayed_open'] = (
        bar._header_overflow_menu.isVisible())
    bar._header_overflow_menu.close()

set_master_volume(50)
bar.refresh_state()
bar._header_overflow_menu.popup(
    bar._header_overflow_button.mapToGlobal(
        bar._header_overflow_button.rect().bottomLeft()))
QTest.qWait(35)
app.processEvents()
exercise_overflow_menu()
QTest.qWait(220)
app.processEvents()
menu_keyboard['saved'] = config.data['general']['master_volume']
overflow_focus['keyboard_menu'] = menu_keyboard

bar._scale_scene.setFocusItem(bar._scale_proxy)
bar._header_overflow_button.setFocus(Qt.FocusReason.TabFocusReason)
set_master_volume(100)
bar.refresh_state()
app.processEvents()
overflow_focus.update({
    'saved_child_unchanged': bar._header_focus_restore is slider,
    'overflow_value': bar._overflow_volume_slider.value(),
    'overflow_kept_focus': (
        bar._surface.focusWidget() is bar._header_overflow_button),
})
bar._design_size = original_design
bar._logical_surface_width = original_logical_width
bar._pack_header_controls()
app.processEvents()
overflow_focus.update({
    'rocker_restored': bar.volume_rocker.isVisible(),
    'focus_restored': bar._surface.focusWidget() is slider,
    'restored_tab_order': [
        bar._button.nextInFocusChain() is bar.master_mute_button,
        bar.master_mute_button.nextInFocusChain() is slider,
        slider.nextInFocusChain() is bar._settings_button,
        bar._settings_button.nextInFocusChain() is bar._roll_button,
        bar._roll_button.nextInFocusChain() is bar._minimize_button,
    ],
})

# The dedicated header toggle changes Master Mute without opening Sounds.
set_audio_muted(False)
bar.refresh_state()
focus_header_control(bar.master_mute_button)
QTest.keyClick(bar.master_mute_button, Qt.Key.Key_Space)
header_mute = {
    'on': {
        'checked': bar.master_mute_button.isChecked(),
        'state': bar.master_mute_button.property('State'),
        'dot': bar._master_mute_dot.property('State'),
        'name': bar.master_mute_button.accessibleName(),
        'audio_muted': audio_muted(),
        'sounds_open': bool(
            getattr(app, '_feature_settings_instances', {}).get('Sounds') and
            app._feature_settings_instances['Sounds'].isVisible()),
    },
}
QTest.keyClick(bar.master_mute_button, Qt.Key.Key_Space)
header_mute['off'] = {
    'checked': bar.master_mute_button.isChecked(),
    'state': bar.master_mute_button.property('State'),
    'dot': bar._master_mute_dot.property('State'),
    'name': bar.master_mute_button.accessibleName(),
    'audio_muted': audio_muted(),
}

app._log_status = 'ONLINE'
bar.refresh_state()
online_log = {
    'status': bar._buttons['log_status'].property('Status'),
    'online': bar._buttons['log_status'].property('LogOnline'),
    'green_icon': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-online-rest').cacheKey(),
    'tooltip': bar._buttons['log_status'].toolTip(),
    'description': bar._buttons['log_status'].accessibleDescription(),
}
app._log_status = 'QUIET'
bar.refresh_state()
quiet_log = {
    'status': bar._buttons['log_status'].property('Status'),
    'online': bar._buttons['log_status'].property('LogOnline'),
    'yellow_icon': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-quiet').cacheKey(),
}
app._log_status = 'NO LOGS'
bar.refresh_state()
disconnected_log = {
    'status': bar._buttons['log_status'].property('Status'),
    'online': bar._buttons['log_status'].property('LogOnline'),
    'red_icon': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-disconnected').cacheKey(),
    'name': bar._buttons['log_status'].accessibleName(),
}

app.available_update_products = lambda: {
    'Vantage': '9.9.9', 'VantageUI': '8.8.8'}
bar.refresh_state()
update_ready = {
    'badge': bar._update_badge.isVisible(),
    'badge_text': bar._update_badge.text(),
    'text': bar._buttons['updates'].text(),
    'width': bar._buttons['updates'].width(),
    'ui_badge': bar._vantage_ui_badge.isVisible(),
    'name': bar._buttons['updates'].accessibleName(),
    'description': bar._buttons['updates'].accessibleDescription(),
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
app.reset_ui_layout = lambda **_kwargs: reload_calls.append('reset') or True
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
    'volume_visible': bar.volume_rocker.isVisible(),
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
bar._trigger('maps')
app.processEvents()
toggled_closed = {
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
    'update_text': bar._buttons['updates'].text(),
    'update_width': bar._buttons['updates'].width(),
    'volume_visible': bar.volume_rocker.isVisible(),
}

settings = app.show_feature_settings('Quick Bar', owner=bar)
settings_page = {
    'selected': settings._list_widget.currentItem().text(),
    'dedicated': settings._scoped_section == 'Quick Bar',
    'navigation_hidden': not settings._list_widget.isVisible(),
    'orientation_control': settings._widget_stack.findChild(
        type(settings._section_combo), 'quickbar:orientation') is not None,
    'header_control': settings._widget_stack.findChild(
        __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
        'quickbar:show_header') is not None,
    'tick_control': settings._widget_stack.findChild(
        __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
        'quickbar:show_server_tick') is not None,
    'ticker_control': settings._widget_stack.findChild(
        __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
        'quickbar:show_notification_ticker') is not None,
    'all_item_controls': all(
        settings._widget_stack.findChild(
            __import__('PySide6.QtWidgets', fromlist=['QCheckBox']).QCheckBox,
            f'quickbar:show_{key}') is not None
        for key in QUICKBAR_ITEM_KEYS),
}
global_settings = app._settings
bar._trigger('settings')
app.processEvents()
settings_open = {
    'visible': global_settings.isVisible(),
    'checked': bar._buttons['settings'].isChecked(),
    'dot': bar._enabled_dots['settings'].isVisible(),
}
bar._trigger('settings')
app.processEvents()
settings_closed = {
    'visible': global_settings.isVisible(),
    'checked': bar._buttons['settings'].isChecked(),
    'dot': bar._enabled_dots['settings'].isVisible(),
}
muted_before_sound_center = audio_muted()
bar._trigger('mute')
app.processEvents()
sound_center = app._feature_settings_instances['Sounds']
sound_center_state = {
    'visible': sound_center.isVisible(),
    'section': sound_center._list_widget.currentItem().text(),
    'sections': sound_center._list_widget.count(),
    'navigation_hidden': not sound_center._list_widget.isVisible(),
    'button_name': bar._buttons['mute'].accessibleName(),
    'button_checked': bar._buttons['mute'].isChecked(),
    'dot': bar._enabled_dots['mute'].isVisible(),
    'mute_unchanged': audio_muted() == muted_before_sound_center,
}
sound_center.reject()
QTest.qWait(20)
app.processEvents()
sound_center_state['focus_restored'] = (
    bar._surface.focusWidget() is bar._buttons['mute'])

print(json.dumps({
    'initial': initial,
    'tick_readout': tick_readout,
    'buttons_only': buttons_only,
    'header_height': header_height,
    'toggled': toggled,
    'toggled_closed': toggled_closed,
    'vertical': vertical,
    'settings': settings_page,
    'settings_open': settings_open,
    'settings_closed': settings_closed,
    'sound_center': sound_center_state,
    'support_calls': support_calls,
    'reload_calls': reload_calls,
    'online_log': online_log,
    'quiet_log': quiet_log,
    'disconnected_log': disconnected_log,
    'update_ready': update_ready,
    'volume_from_settings': volume_from_settings,
    'pointer_during_drag': pointer_during_drag,
    'volume_after_pointer': volume_after_pointer,
    'volume_after_keyboard': volume_after_keyboard,
    'wheel_guard': wheel_guard,
    'volume_resynced': volume_resynced,
    'overflow_focus': overflow_focus,
    'header_mute': header_mute,
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
    'settings_visible': bar._settings_button.isVisible(),
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


MOTION_LIFECYCLE_SCRIPT = r"""
import json
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.helpers.icons import game_icon

config.data['general']['startup_window_state'] = 'normal'
config.data['general']['reduce_motion'] = False
config.data['quickbar']['show_support'] = True
config.data['quickbar']['show_log_status'] = True
app = VantageApp([])
bar = app._parsers_dict['quickbar']
bar.show()
app.processEvents()

geometry_before = [bar.width(), bar.height(),
                   bar._design_size.width(), bar._design_size.height()]
support = bar._buttons['support']
support_first = {
    'icon': support.icon().cacheKey(),
    'icon_size': [support.iconSize().width(), support.iconSize().height()],
    'timer': bar._support_pulse_timer.isActive(),
    'spark': bar._support_motion_marker.isVisible(),
}
bar._advance_support_pulse()
support_second = {
    'icon': support.icon().cacheKey(),
    'icon_size': [support.iconSize().width(), support.iconSize().height()],
    'timer': bar._support_pulse_timer.isActive(),
    'spark': bar._support_motion_marker.isVisible(),
}

app._log_status = 'ONLINE'
bar.refresh_state()
app.processEvents()
online_immediate = {
    'debouncing': bar._log_online_debounce.isActive(),
    'animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
    'static_green': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-online-rest').cacheKey(),
    'tooltip': bar._buttons['log_status'].toolTip(),
    'description': bar._buttons['log_status'].accessibleDescription(),
}
QTest.qWait(bar._LOG_ONLINE_DEBOUNCE_MS + 250)
app.processEvents()
online_stable = {
    'debouncing': bar._log_online_debounce.isActive(),
    'animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
    'bright_icon': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-online-bright').cacheKey(),
    'spark': bar._log_motion_marker.isVisible(),
}
stable_icon = bar._buttons['log_status'].icon().cacheKey()
bar._advance_log_pulse()
online_variant_changed = (
    bar._buttons['log_status'].icon().cacheKey() != stable_icon)

app._log_status = 'QUIET'
bar.refresh_state()
app.processEvents()
quiet = {
    'debouncing': bar._log_online_debounce.isActive(),
    'animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
    'yellow_icon': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-quiet').cacheKey(),
}

app._log_status = 'ONLINE'
bar.refresh_state()
config.data['quickbar']['show_log_status'] = False
app._signals['settings'].config_updated.emit()
app.processEvents()
button_hidden = {
    'button': bar._buttons['log_status'].isVisible(),
    'debouncing': bar._log_online_debounce.isActive(),
    'animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
}

config.data['quickbar']['show_log_status'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
bar.hide()
app.processEvents()
window_hidden = {
    'debouncing': bar._log_online_debounce.isActive(),
    'animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
}

bar.show()
config.data['general']['reduce_motion'] = True
app._signals['settings'].config_updated.emit()
app.processEvents()
reduced_motion = {
    'support_timer': bar._support_pulse_timer.isActive(),
    'support_pulse': bool(support.property('Pulse')),
    'log_debouncing': bar._log_online_debounce.isActive(),
    'log_animating': bar._log_pulse_timer.isActive(),
    'live_pulse': bool(bar._buttons['log_status'].property('LivePulse')),
    'static_green': bar._buttons['log_status'].icon().cacheKey() ==
        game_icon('ph-pulse-online-rest').cacheKey(),
}
geometry_after = [bar.width(), bar.height(),
                  bar._design_size.width(), bar._design_size.height()]

print(json.dumps({
    'geometry_before': geometry_before,
    'geometry_after': geometry_after,
    'support_first': support_first,
    'support_second': support_second,
    'support_expected': [
        game_icon('ph-coffee-bright').cacheKey(),
        game_icon('ph-coffee-rest').cacheKey(),
    ],
    'online_immediate': online_immediate,
    'online_stable': online_stable,
    'online_variant_changed': online_variant_changed,
    'quiet': quiet,
    'button_hidden': button_hidden,
    'window_hidden': window_hidden,
    'reduced_motion': reduced_motion,
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
        assert quickbar['show_notification_ticker'] is True
        assert all(quickbar[f'show_{key}'] for key in QUICKBAR_ITEM_KEYS)
        assert quickbar['support_visibility_version'] == 1
    finally:
        config.data = original


def test_quickbar_uses_one_distinct_icon_per_action():
    from vantage.helpers.quickbar_items import QUICKBAR_ITEMS

    icons = [icon for _key, _label, icon, _group in QUICKBAR_ITEMS]
    catalog = {key: icon for key, _label, icon, _group in QUICKBAR_ITEMS}
    assert len(icons) == len(set(icons))
    assert all(icon.startswith("ph-") for icon in icons)
    assert catalog["mute"] == "ph-speaker"
    assert (ROOT / "data" / "ui" / "icons" / "ph-speaker.svg").is_file()
    assert QUICKBAR_ITEMS[-1][0] == "support"


def test_quickbar_keeps_timers_beside_spells_and_recovery_beside_quit():
    keys = [key for key, _label, _icon, _group in QUICKBAR_ITEMS]
    assert keys.index("timers") == keys.index("spells") + 1
    assert keys.index("device_sync") == keys.index("mobile") + 1
    assert keys[keys.index("quit") - 4:keys.index("quit")] == [
        "log_status", "reload_ui", "updates", "settings"]
    assert keys.index("settings") == keys.index("quit") - 1


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
    assert initial['support_tooltip'] == \
        'Like this project? Support it — Buy Me a Coffee'
    assert initial['support_icon_visible'] is True
    assert initial['sharp_surface'] is True
    assert initial['full_font_hinting'] is True
    assert initial['support_is_last'] is True
    assert initial['dialog_actions_checkable'] is True
    assert initial['volume_visible'] is True
    assert initial['volume_priority'] == 100
    assert initial['volume_compact'] is True
    assert initial['volume_control_size'][0] <= 130
    assert initial['volume_control_size'][1] == 24
    assert 44 <= initial['volume_slider_size'][0] <= 64
    assert initial['volume_slider_size'][1] == 24
    assert initial['mute_semantics'] == {
        'native': True,
        'checkable': True,
        'checked': False,
        'name': 'Master Mute: OFF',
        'description': (
            'Toggle all Vantage sound and speech. Notification audio is '
            'active.'),
        'size': [24, 24],
        'dot_state': 'off',
        'dot_visible': True,
        'icon_visible': True,
        'focus_style': True,
    }
    assert initial['large_font_layout']['label_width'] >= \
        initial['large_font_layout']['label_required']
    assert 44 <= initial['large_font_layout']['slider_width'] <= 64
    assert initial['large_font_layout']['composite_width'] <= 130
    semantics = initial['volume_semantics']
    assert semantics['label_width'] >= semantics['label_required']
    assert all(ratio >= 3.0 for ratio in semantics['contrast'])
    assert semantics['visual_palette'] == {
        'rail': '#182127',
        'rail_outline': '#687A86',
        'fill': '#9A7541',
        'thumb_ring': '#C6A15A',
        'thumb_core': '#362916',
        'focus': '#D0A45B',
    }
    assert {
        key: value for key, value in semantics.items()
        if key not in {
            'label_width', 'label_required', 'contrast', 'visual_palette'}
    } == {
        'native': True,
        'horizontal': True,
        'range': [0, 100],
        'steps': [1, 10],
        'name': 'Notification volume',
        'description': (
            'Scales every WAV and text to speech notification. Master Mute '
            'is a separate control.'),
        'role_slider': True,
        'focusable': True,
        'label_focusable': False,
        'custom_paint': True,
        'platform_parts_removed': True,
        'style_has_white': False,
        'palette_has_near_white': False,
    }
    assert initial['header_tab_order'] == [True] * 5
    assert result['volume_from_settings'] == {
        'value': 50,
        'text': '50%',
        'name': 'Notification volume',
        'description': (
            'Scales every WAV and text to speech notification. Master Mute '
            'is a separate control.'),
    }
    assert result['pointer_during_drag']['value'] > 50
    assert result['pointer_during_drag']['writes'] == []
    pointer = result['volume_after_pointer']
    assert pointer['live_value'] == pointer['saved_value']
    assert pointer['live_value'] == result['pointer_during_drag']['value']
    assert pointer['text'] == f"{pointer['live_value']}%"
    assert pointer['muted'] is True
    assert pointer['writes'] == [pointer['live_value']]
    assert result['volume_after_keyboard'] == {
        'home': 0,
        'page_up': 10,
        'page_down': 0,
        'right': 11,
        'end': 100,
        'text': '100%',
        'writes_before_debounce': [],
        'writes_after_debounce': [100],
        'focused': True,
        'enabled_at_boundary': True,
    }
    assert result['wheel_guard'] == {
        'unfocused': 50,
        'focused_changed': True,
    }
    assert result['volume_resynced'] == {
        'value': 65,
        'text': '65%',
        'label_name': '65 percent',
        'writes': [],
        'muted': False,
    }
    assert result['overflow_focus'] == {
        'rocker_hidden': True,
        'overflow_visible': True,
        'saved_child': True,
        'overflow_slider': True,
        'overflow_mute': True,
        'live_value': {
            'master': 72,
            'header': 72,
            'overflow': 72,
            'label': '72%',
        },
        'menu_action_count': 2,
        'volume_widget_actions': 1,
        'empty_actions': 0,
        'tab_order': [True] * 4,
        'keyboard_menu': {
            'menu_visible': True,
            'focus_proxy': True,
            'initial_focus': False,
            'mute_on': {
                'checked': True,
                'state': 'on',
                'dot': 'on',
                'audio_muted': True,
                'menu_open': True,
            },
            'mute_off': {
                'checked': False,
                'state': 'off',
                'dot': 'off',
                'audio_muted': False,
            },
            'tab_focus_requested': True,
            'values': [0, 10, 11, 100, 90],
            'menu_stayed_open': True,
            'saved': 90,
        },
        'saved_child_unchanged': True,
        'overflow_value': 100,
        'overflow_kept_focus': True,
        'rocker_restored': True,
        'focus_restored': True,
        'restored_tab_order': [True] * 5,
    }
    assert result['header_mute'] == {
        'on': {
            'checked': True,
            'state': 'on',
            'dot': 'on',
            'name': 'Master Mute: ON',
            'audio_muted': True,
            'sounds_open': False,
        },
        'off': {
            'checked': False,
            'state': 'off',
            'dot': 'off',
            'name': 'Master Mute: OFF',
            'audio_muted': False,
        },
    }
    assert result['online_log']['status'] == 'online'
    assert result['online_log']['online'] is True
    assert result['online_log']['green_icon'] is True
    assert 'ONLINE' in result['online_log']['tooltip']
    assert 'live log activity' in result['online_log']['tooltip']
    assert 'activity detected' in result['online_log']['description']
    assert result['quiet_log'] == {
        'status': 'quiet',
        'online': False,
        'yellow_icon': True,
    }
    assert result['disconnected_log'] == {
        'status': 'no_logs',
        'online': False,
        'red_icon': True,
        'name': 'Log Status: DISCONNECTED',
    }
    assert result['update_ready']['badge'] is True
    assert result['update_ready']['badge_text'] == '2'
    assert result['update_ready']['text'] == 'Vantage + UI'
    assert result['update_ready']['width'] > 24
    assert result['update_ready']['ui_badge'] is True
    assert 'Update ready' in result['update_ready']['name']
    assert 'Vantage 9.9.9 and VantageUI 8.8.8' in \
        result['update_ready']['description']
    assert result['support_calls'] == ['opened']
    assert result['reload_calls'] == ['reset']

    assert result['tick_readout']['text'] == 'TICK'
    assert result['tick_readout']['progress'] == 1000
    assert 'click to toggle' in result['tick_readout']['tooltip']
    assert result['buttons_only']['header_visible'] is False
    assert result['buttons_only']['volume_visible'] is False
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
    assert result['toggled_closed'] == {
        'maps_checked': False,
        'maps_dot': False,
        'maps_visible': False,
    }
    vertical = result['vertical']
    assert vertical['orientation'] == 'vertical'
    assert vertical['design'][1] > vertical['design'][0]
    assert vertical['market_visible'] is False
    assert 'horizontal' in vertical['switch_tooltip']
    assert vertical['support_pulsing'] is False
    assert vertical['support_pulse'] is False
    assert vertical['update_text'] == '2'
    assert vertical['update_width'] == 30
    assert vertical['volume_visible'] is False
    assert result['settings'] == {
        'selected': 'Quick Bar',
        'dedicated': True,
        'navigation_hidden': True,
        'orientation_control': True,
        'header_control': True,
        'tick_control': True,
        'ticker_control': True,
        'all_item_controls': True,
    }
    assert result['settings_open'] == {
        'visible': True,
        'checked': True,
        'dot': True,
    }
    assert result['settings_closed'] == {
        'visible': False,
        'checked': False,
        'dot': False,
    }
    assert result['sound_center'] == {
        'visible': True,
        'section': 'Sounds',
        'sections': 1,
        'navigation_hidden': True,
        'button_name': 'Sounds',
        'button_checked': True,
        'dot': True,
        'mute_unchanged': True,
        'focus_restored': True,
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
    assert vertical['settings_visible'] is False

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


def test_quickbar_animation_variants_debounce_visibility_and_reduced_motion(
        tmp_path):
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['VANTAGE_DATA_DIR'] = str(tmp_path / 'profile')
    completed = subprocess.run(
        [sys.executable, '-c', MOTION_LIFECYCLE_SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result['geometry_after'] == result['geometry_before']
    assert result['support_first']['timer'] is True
    assert result['support_second']['timer'] is True
    assert result['support_first']['spark'] is True
    assert result['support_second']['spark'] is False
    assert result['support_first']['icon_size'] == [16, 16]
    assert result['support_second']['icon_size'] == [16, 16]
    assert [result['support_first']['icon'], result['support_second']['icon']] == \
        result['support_expected']

    assert result['online_immediate']['debouncing'] is True
    assert result['online_immediate']['animating'] is False
    assert result['online_immediate']['live_pulse'] is False
    assert result['online_immediate']['static_green'] is True
    assert 'verifying stability' in \
        result['online_immediate']['tooltip']
    assert 'Live log activity' in \
        result['online_immediate']['description']
    assert result['online_stable'] == {
        'debouncing': False,
        'animating': True,
        'live_pulse': True,
        'bright_icon': True,
        'spark': True,
    }
    assert result['online_variant_changed'] is True
    assert result['quiet'] == {
        'debouncing': False,
        'animating': False,
        'live_pulse': False,
        'yellow_icon': True,
    }
    assert result['button_hidden'] == {
        'button': False,
        'debouncing': False,
        'animating': False,
        'live_pulse': False,
    }
    assert result['window_hidden'] == {
        'debouncing': False,
        'animating': False,
        'live_pulse': False,
    }
    assert result['reduced_motion'] == {
        'support_timer': False,
        'support_pulse': False,
        'log_debouncing': False,
        'log_animating': False,
        'live_pulse': False,
        'static_green': True,
    }
