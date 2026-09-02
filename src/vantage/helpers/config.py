"""
General global settings setup to provide settings.data
"""
import os
from glob import glob
import json

from vantage.helpers.trigger_groups import normalize_trigger_groups
from vantage.helpers.quickbar_items import QUICKBAR_ITEM_KEYS

data = {}
_filename = ''
APP_EXIT = False


def _bounded_int(value, default, lower, upper):
    try:
        return max(lower, min(upper, int(value)))
    except (TypeError, ValueError):
        return default

BASIC_ALERTS_VERSION = 2
BASIC_ALERTS = (
    ["Invisibility Fading", "You feel yourself starting to appear*", "00:00:00", "",
     "builtin:danger-double", "INVISIBILITY FADING", True, False, "Vantage · Basics"],
    ["Charm Break", "Your charm spell has worn off.", "00:00:00", "",
     "builtin:danger-double", "CHARM BROKEN", True, False, "Vantage · Basics"],
    ["Root Break", "Your root spell has worn off.", "00:00:00", "",
     "builtin:danger-double", "ROOT BROKEN", True, False, "Vantage · Basics"],
    ["Fear Break", "Your fear spell has worn off.", "00:00:00", "",
     "builtin:danger-double", "FEAR BROKEN", True, False, "Vantage · Basics"],
    ["Fizzle", "Your spell fizzles!", "00:00:00", "",
     "builtin:soft-tick", "FIZZLE", True, False, "Vantage · Basics"],
    ["Spell Resist", "Your target resisted*", "00:00:00", "",
     "builtin:rune-pulse", "SPELL RESISTED", True, False, "Vantage · Basics"],
    ["Mez Resist", "Your target has resisted your attempt to mesmerize it.",
     "00:00:00", "", "builtin:rune-pulse", "MEZ RESISTED", True, False,
     "Vantage · Basics"],
    ["Spell Did Not Hold", "Your spell did not take hold.", "00:00:00", "",
     "builtin:rune-pulse", "SPELL DID NOT HOLD", True, False, "Vantage · Basics"],
    ["Cast Interrupted", "Your spell is interrupted.", "00:00:00", "",
     "builtin:soft-tick", "CAST INTERRUPTED", True, False, "Vantage · Basics"],
    ["Missed Note", "You miss a note, bringing your song to a close!", "00:00:00", "",
     "builtin:soft-tick", "MISSED NOTE", True, False, "Vantage · Basics"],
    ["Mob Enraged", "* has become ENRAGED.", "00:00:00", "",
     "builtin:danger-double", "MOB ENRAGED", True, False, "Vantage · Basics"],
    ["Critical hit", "{c} scores a critical hit!", "00:00:00", "",
     "builtin:warden-bell", "CRITICAL HIT", False, False, "Vantage · Basics"],
)


DEFAULT_NOTIFICATION_OVERLAYS = {
    "alerts": {
        "label": "Alerts",
        "type": "text",
        "enabled": True,
        "default_position": "top_center",
        "sort": "newest",
        "group_titles": False,
        "group_by_character": False,
        "max_entries": 5,
        "font_name": "Noto Sans",
        "font_size": 10,
        "font_weight": "medium",
        "font_color": "#F2EAD8",
        "shadow_color": "#000000",
        "shadow_depth": 1,
        "background_color": "#0B0D10",
        "background_opacity": 92,
        "faded_background_color": "#0B0D10",
        "faded_background_opacity": 35,
        "text_fade_seconds": 8,
        "show_timer_bar": False,
        "standardize_timer_bars": False,
        "empty_bar_color": "#171B20",
        "timer_bar_color": "#B5782F",
    },
    "timers": {
        "label": "Timer alerts",
        "type": "timer",
        "enabled": True,
        "default_position": "middle_right",
        "sort": "time_remaining",
        "group_titles": False,
        "group_by_character": False,
        "max_entries": 5,
        "font_name": "Noto Sans",
        "font_size": 10,
        "font_weight": "medium",
        "font_color": "#F2EAD8",
        "shadow_color": "#000000",
        "shadow_depth": 1,
        "background_color": "#0B0D10",
        "background_opacity": 92,
        "faded_background_color": "#0B0D10",
        "faded_background_opacity": 35,
        "text_fade_seconds": 8,
        "show_timer_bar": True,
        "standardize_timer_bars": False,
        "empty_bar_color": "#171B20",
        "timer_bar_color": "#B5782F",
    },
}


def notification_overlay_defaults(overlay_id, overlay_type="text"):
    """Return an independent normalized overlay definition."""
    overlay_type = "timer" if overlay_type == "timer" else "text"
    template_id = "timers" if overlay_type == "timer" else "alerts"
    defaults = dict(DEFAULT_NOTIFICATION_OVERLAYS[template_id])
    if overlay_id not in DEFAULT_NOTIFICATION_OVERLAYS:
        defaults["label"] = (
            "Timer overlay" if overlay_type == "timer" else "Text overlay")
    return defaults


def normalize_notification_overlays(value, seed_defaults=True):
    """Normalize overlays, optionally preserving an explicitly empty registry."""
    if not isinstance(value, dict):
        value = {}
    if not value and seed_defaults:
        value = {
            key: dict(settings)
            for key, settings in DEFAULT_NOTIFICATION_OVERLAYS.items()
        }

    normalized = {}
    for raw_id, raw_settings in value.items():
        overlay_id = str(raw_id or "").strip()
        if (not overlay_id or overlay_id == "none"
                or not isinstance(raw_settings, dict)):
            continue
        inferred_type = raw_settings.get(
            "type", "timer" if overlay_id == "timers" else "text")
        overlay_type = "timer" if inferred_type == "timer" else "text"
        settings = notification_overlay_defaults(overlay_id, overlay_type)
        settings.update(raw_settings)
        settings["label"] = str(
            settings.get("label") or
            overlay_id.replace("_", " ").title())[:80]
        settings["type"] = overlay_type
        settings["enabled"] = bool(settings.get("enabled", True))
        if settings.get("default_position") not in {
                "top_left", "top_center", "top_right",
                "middle_left", "middle_center", "middle_right",
                "bottom_left", "bottom_center", "bottom_right"}:
            settings["default_position"] = (
                "middle_right" if overlay_type == "timer" else "top_center")
        if settings.get("sort") not in {
                "newest", "oldest", "time_remaining", "triggered"}:
            settings["sort"] = (
                "time_remaining" if overlay_type == "timer" else "newest")
        # Keep compatibility with the first Vantage overlay implementation.
        if "newest_first" in raw_settings and "sort" not in raw_settings:
            settings["sort"] = (
                "newest" if raw_settings.get("newest_first") else "oldest")
        settings["newest_first"] = settings["sort"] == "newest"
        if settings.get("font_weight") not in {"normal", "medium", "bold"}:
            settings["font_weight"] = "medium"
        for key, lower, upper, fallback in (
                ("max_entries", 1, 20, 5),
                ("font_size", 7, 32, 10),
                ("shadow_depth", 0, 5, 1),
                ("background_opacity", 0, 100, 92),
                ("faded_background_opacity", 0, 100, 35),
                ("text_fade_seconds", 0, 300, 8)):
            try:
                settings[key] = max(
                    lower, min(upper, int(settings.get(key, fallback))))
            except (TypeError, ValueError):
                settings[key] = fallback
        for key in (
                "group_titles", "group_by_character", "show_timer_bar",
                "standardize_timer_bars"):
            settings[key] = bool(settings.get(key, False))
        normalized[overlay_id] = settings

    if not normalized and seed_defaults:
        normalized["alerts"] = dict(DEFAULT_NOTIFICATION_OVERLAYS["alerts"])
    return normalized


def load(filename):
    """
    Load json from file.

    If resulting json has 'location' declared, 'data' dict will be wiped and
    populated with the yaml at file location 'location'.
    """
    global data
    global _filename
    _filename = filename

    try:
        with open(_filename, 'r+') as f:
            data = json.loads(f.read())
    except:
        # vantage.config.json does not exist, create blank data
        data = {}


def save():
    """
    Saves json to previously opened location.
    """
    with open(_filename, mode='w') as f:
        f.write(json.dumps(data, indent=4, sort_keys=True))


def verify_settings():
    # verify vantage.config.json contains what it should and
    # set defaults if appropriate

    # general
    data['general'] = data.get('general', {})
    data['general']['eq_log_dir'] = get_setting(
        data['general'].get('eq_log_dir', ''),
        ''
        )
    data['general']['window_flush'] = get_setting(
        data['general'].get('window_flush', True),
        True
    )
    data['general']['startup_window_state'] = get_setting(
        data['general'].get('startup_window_state', 'rolled'),
        'rolled',
        lambda value: value in ('rolled', 'minimized', 'normal')
    )
    if data['general'].get('update_system_version', 0) < 1:
        data['general']['update_check'] = True
        data['general']['update_system_version'] = 1
    data['general']['update_check'] = get_setting(
        data['general'].get('update_check', True), True)
    try:
        data['general']['last_update_check'] = max(
            0.0, float(data['general'].get('last_update_check', 0.0)))
    except (TypeError, ValueError):
        data['general']['last_update_check'] = 0.0
    data['general']['audio_muted'] = get_setting(
        data['general'].get('audio_muted', False),
        False
    )
    data['general']['reduce_motion'] = get_setting(
        data['general'].get('reduce_motion', False),
        False
    )
    data['general']['log_archive_enabled'] = get_setting(
        data['general'].get('log_archive_enabled', False),
        False
    )
    data['general']['log_archive_size_mb'] = _bounded_int(
        data['general'].get('log_archive_size_mb', 100),
        100, 1, 2048
    )
    data['general']['notification_position'] = get_setting(
        data['general'].get('notification_position', 'top_right'),
        'top_right',
        lambda value: value in (
            'top_left', 'top_center', 'top_right',
            'bottom_left', 'bottom_center', 'bottom_right')
    )

    # Floating, configurable launch surface for every tray command. It stays
    # interactive and never creates another normal Windows taskbar entry.
    data['quickbar'] = data.get('quickbar', {})
    data['quickbar']['geometry'] = get_setting(
        data['quickbar'].get('geometry', [10, 10, 590, 62]),
        [10, 10, 590, 62],
        lambda value: isinstance(value, list) and len(value) == 4)
    for key, default in (
            ('toggled', True), ('auto_hide_menu', False),
            ('always_on_top', True), ('frameless', True)):
        data['quickbar'][key] = get_setting(
            data['quickbar'].get(key, default), default)
    # A command surface must always accept mouse and keyboard input.
    data['quickbar']['clickthrough'] = False
    data['quickbar']['opacity'] = get_setting(
        data['quickbar'].get('opacity', 92), 92,
        lambda value: 25 <= value <= 100)
    data['quickbar']['orientation'] = get_setting(
        data['quickbar'].get('orientation', 'horizontal'), 'horizontal',
        lambda value: value in ('horizontal', 'vertical'))
    data['quickbar']['show_header'] = get_setting(
        data['quickbar'].get('show_header', True), True)
    data['quickbar']['show_server_tick'] = get_setting(
        data['quickbar'].get('show_server_tick', True), True)
    for item_key in QUICKBAR_ITEM_KEYS:
        setting_key = f'show_{item_key}'
        data['quickbar'][setting_key] = get_setting(
            data['quickbar'].get(setting_key, True), True)
    # One-time repair for profiles created while the animated support icon
    # could render as an empty control inside the scaled Quick Bar. Preserve
    # later user choices after making the repaired button discoverable once.
    support_visibility_version = _bounded_int(
        data['quickbar'].get('support_visibility_version', 0), 0, 0, 1)
    if support_visibility_version < 1:
        data['quickbar']['show_support'] = True
    data['quickbar']['support_visibility_version'] = 1
    if 'notification_overlays' in data['general']:
        data['general']['notification_overlays'] = \
            normalize_notification_overlays(
                data['general'].get('notification_overlays'),
                seed_defaults=False)
    else:
        data['general']['notification_overlays'] = \
            normalize_notification_overlays({})
    data['general']['character_profiles'] = get_setting(
        data['general'].get('character_profiles', {}), {},
        lambda value: isinstance(value, dict))

    # sharing
    data['sharing'] = data.get('sharing', {})
    data['sharing']['player_name'] = get_setting(
        data['sharing'].get('player_name', "ConfigureMe"),
        "ConfigureMe"
    )
    data['sharing']['player_name_override'] = get_setting(
        data['sharing'].get('player_name_override', False),
        False
    )
    data['sharing']['url'] = get_setting(
        data['sharing'].get('url', "ws://sheeplauncher.net:8424"),
        "ws://sheeplauncher.net:8424",
        lambda x: x.startswith('ws://')
    )
    data['sharing']['reconnect_delay'] = get_setting(
        data['sharing'].get('reconnect_delay', 5),
        5,
        lambda x: (isinstance(x, int) and x >= 1)
    )
    data['sharing']['enabled'] = get_setting(
        data['sharing'].get('enabled', False),
        False
    )
    data['sharing']['group_key'] = get_setting(
        data['sharing'].get('group_key', "public"),
        "public"
    )
    # maps
    data['maps'] = data.get('maps', {})
    data['maps']['auto_follow'] = get_setting(
        data['maps'].get('auto_follow', True),
        True
        )
    data['maps']['closest_z_alpha'] = get_setting(
        data['maps'].get('closest_z_alpha', 20),
        20,
        lambda x: (1 <= x <= 100)
        )
    data['maps']['current_z_alpha'] = get_setting(
        data['maps'].get('current_z_alpha', 100),
        100,
        lambda x: (1 <= x <= 100)
        )
    data['maps']['geometry'] = get_setting(
        data['maps'].get('geometry', [0, 0, 400, 400]),
        [0, 0, 400, 400],
        lambda x: (
            len(x) == 4 and
            isinstance(x[0], int) and
            isinstance(x[1], int) and
            isinstance(x[2], int) and
            isinstance(x[3], int)
            )
        )
    data['maps']['grid_line_width'] = get_setting(
        data['maps'].get('grid_line_width', 1),
        1,
        lambda x: (1 <= x <= 10)
        )
    data['maps']['last_zone'] = get_setting(
        data['maps'].get('last_zone', ''),
        ''
        )
    data['maps']['line_width'] = get_setting(
        data['maps'].get('line_width', 1),
        1,
        lambda x: (1 <= x <= 10)
        )
    data['maps']['other_z_alpha'] = get_setting(
        data['maps'].get('other_z_alpha', 10),
        10,
        lambda x: (1 <= x <= 100)
        )
    data['maps']['scale'] = get_setting(
        data['maps'].get('scale', 0.07),
        0.07
        )
    data['maps']['show_grid'] = get_setting(
        data['maps'].get('show_grid', True),
        True
        )
    data['maps']['show_mouse_location'] = get_setting(
        data['maps'].get('show_mouse_location', True),
        True
        )
    data['maps']['show_poi'] = get_setting(
        data['maps'].get('show_poi', True),
        True
        )
    data['maps']['toggled'] = get_setting(
        data['maps'].get('toggled', True),
        True
        )
    data['maps']['use_z_layers'] = get_setting(
        data['maps'].get('use_z_layers', False),
        False
        )
    data['maps']['opacity'] = get_setting(
        data['maps'].get('opacity', 80),
        80,
        lambda x: (25 <= x <= 100)
        )
    data['maps']['color'] = data['maps'].get('color', '#000000')
    data['maps']['clickthrough'] = get_setting(
        data['maps'].get('clickthrough', False),
        False
    )
    data['maps']['auto_hide_menu'] = get_setting(
        data['maps'].get('auto_hide_menu', True),
        True
        )
    data['maps']['always_on_top'] = get_setting(
        data['maps'].get('always_on_top', True),
        True
        )
    data['maps']['frameless'] = get_setting(
        data['maps'].get('frameless', True),
        True
        )

    # spells
    data['spells'] = data.get('spells', {})
    data['spells']['casting_window_buffer'] = get_setting(
        data['spells'].get('casting_window_buffer', 1000),
        1000,
        lambda x: (1 <= x <= 4000)
        )
    custom_timers = data['spells'].get('custom_timers', [])
    if not isinstance(custom_timers, list) or not all(
            isinstance(item, list) and len(item) >= 3 and
            all(isinstance(value, str) for value in item[:3])
            for item in custom_timers):
        custom_timers = []
    for item in custom_timers:
        if len(item) > 8 and item[8] in (
                "Vantage · Básicos", "Vantage · Basics"):
            translated = next(
                (basic for basic in BASIC_ALERTS if basic[1] == item[1]),
                None)
            if translated:
                item[0] = translated[0]
                item[5] = translated[5]
                item[8] = translated[8]
    data['spells']['custom_timers'] = custom_timers
    data['spells']['trigger_categories'] = get_setting(
        data['spells'].get('trigger_categories', {}), {},
        lambda value: isinstance(value, dict))
    for item in custom_timers:
        category = (
            str(item[9]).strip() if len(item) > 9 and item[9] else 'Default')
        data['spells']['trigger_categories'].setdefault(category, True)
    basic_version = data['spells'].get('basic_alerts_version', 0)
    if not isinstance(basic_version, int) or basic_version < BASIC_ALERTS_VERSION:
        existing = {item[0].casefold() for item in custom_timers if item}
        custom_timers.extend(
            list(item) for item in BASIC_ALERTS
            if item[0].casefold() not in existing)
        data['spells']['basic_alerts_version'] = BASIC_ALERTS_VERSION
    normalize_trigger_groups(data['spells'])
    data['spells']['delay_self_buffs_on_zone'] = get_setting(
        data['spells'].get('delay_self_buffs_on_zone', True),
        True
        )
    data['spells']['geometry'] = get_setting(
        data['spells'].get('geometry', [400, 0, 200, 400]),
        [400, 0, 200, 400],
        lambda x: (
            len(x) == 4 and
            isinstance(x[0], int) and
            isinstance(x[1], int) and
            isinstance(x[2], int) and
            isinstance(x[3], int)
            )
        )
    data['spells']['level'] = get_setting(
        data['spells'].get('level', 1),
        1,
        lambda x: (1 <= x <= 65)
        )
    data['spells']['toggled'] = get_setting(
        data['spells'].get('toggled', True),
        True
        )
    data['spells']['use_casting_window'] = get_setting(
        data['spells'].get('use_casting_window', True),
        True
        )
    if data['spells'].get('item_click_detection_version', 0) < 1:
        data['spells']['use_item_triggers'] = True
        data['spells']['item_click_detection_version'] = 1
    data['spells']['use_item_triggers'] = get_setting(
        data['spells'].get('use_item_triggers', True), True)
    data['spells']['use_custom_triggers'] = get_setting(
        data['spells'].get('use_custom_triggers', True),
        True
        )
    data['spells']['use_secondary'] = get_setting(
        data['spells'].get('use_secondary', ["levitate"]),
        ["levitate"],
        lambda x: isinstance(x, list)
        )
    data['spells']['use_secondary_all'] = get_setting(
        data['spells'].get('use_secondary_all', False),
        False
        )
    data['spells']['opacity'] = get_setting(
        data['spells'].get('opacity', 80),
        80,
        lambda x: (25 <= x <= 100)
        )
    data['spells']['color'] = data['spells'].get('color', '#000000')
    data['spells']['clickthrough'] = get_setting(
        data['spells'].get('clickthrough', False),
        False
    )
    data['spells']['auto_hide_menu'] = get_setting(
        data['spells'].get('auto_hide_menu', True),
        True
        )
    data['spells']['always_on_top'] = get_setting(
        data['spells'].get('always_on_top', True),
        True
        )
    data['spells']['frameless'] = get_setting(
        data['spells'].get('frameless', True),
        True
        )
    data['spells']['fade_sound_enabled'] = get_setting(
        data['spells'].get('fade_sound_enabled', True), True)
    warning_seconds = data['spells'].get('fade_warning_seconds', 40)
    if warning_seconds == 30:
        warning_seconds = 40  # migrate the former default
    data['spells']['fade_warning_seconds'] = get_setting(
        warning_seconds, 40,
        lambda x: 0 <= x <= 600)
    data['spells']['fade_sound_volume'] = get_setting(
        data['spells'].get('fade_sound_volume', 80), 80,
        lambda x: 0 <= x <= 100)
    data['spells']['fade_sound_path'] = get_setting(
        data['spells'].get('fade_sound_path', 'builtin:crystal-ping'),
        'builtin:crystal-ping')
    data['spells']['fade_sound_overrides'] = get_setting(
        data['spells'].get('fade_sound_overrides', {}), {},
        lambda x: isinstance(x, dict))
    data['spells']['fade_sound_muted'] = get_setting(
        data['spells'].get('fade_sound_muted', []), [],
        lambda x: isinstance(x, list))
    data['spells']['show_boat_schedules'] = get_setting(
        data['spells'].get('show_boat_schedules', False), False)
    data['spells']['bard_count_enabled'] = get_setting(
        data['spells'].get('bard_count_enabled', False), False)
    data['spells']['bard_count_overlay'] = get_setting(
        data['spells'].get('bard_count_overlay', True), True)
    data['spells']['bard_count_audio'] = get_setting(
        data['spells'].get('bard_count_audio', False), False)
    raw_audio_profiles = get_setting(
        data['spells'].get('audio_profiles', {}), {},
        lambda x: isinstance(x, dict))
    audio_profiles = {}
    for raw_key, raw_profile in raw_audio_profiles.items():
        if not isinstance(raw_profile, dict):
            continue
        legacy_parts = str(raw_key or '').split('@', 1)
        character = str(raw_profile.get(
            'character', legacy_parts[0] if legacy_parts else '')).strip()
        server = str(raw_profile.get(
            'server', legacy_parts[1] if len(legacy_parts) > 1 else '')).strip()
        if not character:
            continue
        profile_key = f'{character.casefold()}@{server.casefold()}'
        audio_profiles[profile_key] = {
            'character': character[:80],
            'server': server[:80],
            'voice_name': str(raw_profile.get('voice_name', '') or '')[:160],
            'voice_speed': _bounded_int(
                raw_profile.get('voice_speed', 0), 0, -10, 10),
            'volume': _bounded_int(
                raw_profile.get('volume', 100), 100, 0, 100),
        }
    data['spells']['audio_profiles'] = audio_profiles

    # Compact player or target server-tick overlay. Tick anchoring uses only
    # visible EQ log events or an explicit manual synchronization.
    data['tick'] = data.get('tick', {})
    data['tick']['geometry'] = get_setting(
        data['tick'].get('geometry', [420, 70, 260, 142]),
        [420, 70, 260, 142],
        lambda x: isinstance(x, list) and len(x) == 4)
    for key, default in (
            ('toggled', True), ('clickthrough', False),
            ('auto_hide_menu', False), ('always_on_top', True),
            ('frameless', True), ('auto_sync', True)):
        data['tick'][key] = get_setting(
            data['tick'].get(key, default), default)
    data['tick']['opacity'] = get_setting(
        data['tick'].get('opacity', 92), 92,
        lambda x: 25 <= x <= 100)
    data['tick']['mode'] = get_setting(
        data['tick'].get('mode', 'player'), 'player',
        lambda value: value in ('player', 'target'))

    # Smart spawn timers
    data['timers'] = data.get('timers', {})
    data['timers']['items'] = get_setting(
        data['timers'].get('items', []), [],
        lambda x: isinstance(x, list))
    data['timers']['geometry'] = get_setting(
        data['timers'].get('geometry', [620, 0, 520, 360]),
        [620, 0, 520, 360],
        lambda x: isinstance(x, list) and len(x) == 4)
    data['timers']['toggled'] = get_setting(
        data['timers'].get('toggled', True), True)
    data['timers']['opacity'] = get_setting(
        data['timers'].get('opacity', 92), 92,
        lambda x: 25 <= x <= 100)
    data['timers']['clickthrough'] = get_setting(
        data['timers'].get('clickthrough', False), False)
    data['timers']['auto_hide_menu'] = get_setting(
        data['timers'].get('auto_hide_menu', False), False)
    data['timers']['always_on_top'] = get_setting(
        data['timers'].get('always_on_top', True), True)
    data['timers']['frameless'] = get_setting(
        data['timers'].get('frameless', True), True)
    data['timers']['volume'] = get_setting(
        data['timers'].get('volume', 85), 85,
        lambda x: 0 <= x <= 100)
    data['timers']['compact'] = get_setting(
        data['timers'].get('compact', False), False)
    data['timers']['auto_from_log'] = get_setting(
        data['timers'].get('auto_from_log', True), True)
    data['timers']['clear_after_hours'] = _bounded_int(
        data['timers'].get('clear_after_hours', 4), 4, 1, 48)
    data['timers']['view_zone'] = get_setting(
        data['timers'].get('view_zone', ''), '',
        lambda value: isinstance(value, str))
    try:
        data['timers']['last_session_closed_at'] = max(
            0.0, float(data['timers'].get(
                'last_session_closed_at', 0.0)))
    except (TypeError, ValueError):
        data['timers']['last_session_closed_at'] = 0.0
    data['timers']['encounter_events_enabled'] = get_setting(
        data['timers'].get('encounter_events_enabled', True), True)
    data['timers']['encounter_sound_enabled'] = get_setting(
        data['timers'].get('encounter_sound_enabled', False), False)
    data['timers']['afk_attacked_enabled'] = get_setting(
        data['timers'].get('afk_attacked_enabled', True), True)
    data['timers']['death_loop_enabled'] = get_setting(
        data['timers'].get('death_loop_enabled', True), True)
    data['timers']['safety_sound_enabled'] = get_setting(
        data['timers'].get('safety_sound_enabled', False), False)
    data['timers']['death_loop_deaths'] = _bounded_int(
        data['timers'].get('death_loop_deaths', 4), 4, 2, 20)
    data['timers']['death_loop_seconds'] = _bounded_int(
        data['timers'].get('death_loop_seconds', 120), 120, 30, 600)

    # Multi-view combat parser workspace.
    data['combat'] = data.get('combat', {})
    data['combat']['geometry'] = get_setting(
        data['combat'].get('geometry', [620, 380, 520, 300]),
        [620, 380, 520, 300],
        lambda x: isinstance(x, list) and len(x) == 4)
    for key, default in (
        ('toggled', False), ('clickthrough', False),
        ('auto_hide_menu', False), ('always_on_top', True),
        ('frameless', True)):
        data['combat'][key] = get_setting(data['combat'].get(key, default), default)
    data['combat']['opacity'] = get_setting(
        data['combat'].get('opacity', 94), 94,
        lambda x: 25 <= x <= 100)
    data['combat']['encounter_timeout'] = get_setting(
        data['combat'].get('encounter_timeout', 12), 12,
        lambda x: 3 <= x <= 120)
    data['combat']['history_limit'] = get_setting(
        data['combat'].get('history_limit', 250), 250,
        lambda x: 25 <= x <= 1000)
    chat_time_filter = data['combat'].get('chat_time_filter', 'all')
    if isinstance(chat_time_filter, str) and chat_time_filter.isdigit():
        chat_time_filter = int(chat_time_filter)
    if chat_time_filter not in {
            'all', 'clear', 900, 1800, 3600, 7200, 14400, 28800, 86400}:
        chat_time_filter = 'all'
    data['combat']['chat_time_filter'] = chat_time_filter
    export_defaults = {
        'output_channel': '', 'separator': ' | ', 'top_players': 10,
        'show_opponent': True, 'show_damage': True,
        'show_percentage': True, 'show_dps': True, 'show_sdps': True,
        'append_dps_label': False, 'plain_show_type': False,
        'plain_show_crit': False, 'plain_show_accuracy': False,
        'html_truncate': False, 'html_font_size': 'small',
        'html_theme': 'dark',
    }
    raw_export = data['combat'].get('export_options', {})
    if not isinstance(raw_export, dict):
        raw_export = {}
    export_options = dict(export_defaults)
    export_options.update(raw_export)
    export_options['output_channel'] = str(
        export_options.get('output_channel', ''))[:40].strip()
    export_options['separator'] = str(
        export_options.get('separator', ' | ') or ' | ')[:20]
    export_options['top_players'] = _bounded_int(
        export_options.get('top_players', 10), 10, 0, 100)
    for key in (
            'show_opponent', 'show_damage', 'show_percentage', 'show_dps',
            'show_sdps', 'append_dps_label', 'plain_show_type',
            'plain_show_crit', 'plain_show_accuracy', 'html_truncate'):
        export_options[key] = bool(export_options.get(key, export_defaults[key]))
    if export_options.get('html_font_size') not in {'small', 'medium', 'large'}:
        export_options['html_font_size'] = 'small'
    if export_options.get('html_theme') not in {'dark', 'neutral', 'slate'}:
        export_options['html_theme'] = 'dark'
    data['combat']['export_options'] = export_options
    data['combat']['merge_pets'] = get_setting(
        data['combat'].get('merge_pets', True), True)
    data['combat']['parser_diagnostics_enabled'] = get_setting(
        data['combat'].get('parser_diagnostics_enabled', False), False)
    data['combat']['pet_links'] = get_setting(
        data['combat'].get('pet_links', {}), {},
        lambda x: isinstance(x, dict) and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in x.items()))
    data['combat']['live_overlay_enabled'] = get_setting(
        data['combat'].get('live_overlay_enabled', False), False)
    data['combat']['live_overlay_id'] = get_setting(
        data['combat'].get('live_overlay_id', 'alerts'), 'alerts')
    data['combat']['live_overlay_rows'] = get_setting(
        data['combat'].get('live_overlay_rows', 6), 6,
        lambda x: 1 <= x <= 12)
    data['combat']['secondary_overlay_enabled'] = get_setting(
        data['combat'].get('secondary_overlay_enabled', False), False)
    data['combat']['secondary_overlay_id'] = get_setting(
        data['combat'].get('secondary_overlay_id', 'alerts'), 'alerts')
    data['combat']['secondary_overlay_rows'] = get_setting(
        data['combat'].get('secondary_overlay_rows', 3), 3,
        lambda x: 1 <= x <= 12)
    data['combat']['tanking_overlay_enabled'] = get_setting(
        data['combat'].get('tanking_overlay_enabled', False), False)
    data['combat']['tanking_overlay_id'] = get_setting(
        data['combat'].get('tanking_overlay_id', 'alerts'), 'alerts')
    data['combat']['tanking_overlay_rows'] = get_setting(
        data['combat'].get('tanking_overlay_rows', 5), 5,
        lambda x: 1 <= x <= 12)
    saved_searches = data['combat'].get('saved_searches', [])
    if not isinstance(saved_searches, list):
        saved_searches = []
    data['combat']['saved_searches'] = [
        {
            'name': str(item.get('name', '')).strip()[:80],
            'query': str(item.get('query', '')).strip()[:500],
            'regex': bool(item.get('regex', False)),
            'reverse': bool(item.get('reverse', True)),
            'fight_only': bool(item.get('fight_only', False)),
            'hours': _bounded_int(item.get('hours', 0), 0, 0, 24 * 3650),
            'limit': _bounded_int(item.get('limit', 1500), 1500, 1, 20000),
        }
        for item in saved_searches if isinstance(item, dict)
        and str(item.get('name', '')).strip()
        and str(item.get('query', '')).strip()]
    data['combat']['threat'] = get_setting(
        data['combat'].get('threat', {}), {},
        lambda x: isinstance(x, dict))
    threat = data['combat']['threat']
    threat['enabled'] = get_setting(
        threat.get('enabled', True), True)
    threat['same_type_main_rate'] = get_setting(
        threat.get('same_type_main_rate', 55), 55,
        lambda x: 5 <= x <= 95)
    for hand, default_name in (
            ('main_hand', 'Main hand'), ('off_hand', 'Off hand')):
        weapon = get_setting(
            threat.get(hand, {}), {}, lambda x: isinstance(x, dict))
        weapon['name'] = get_setting(
            weapon.get('name', default_name), default_name)
        weapon['type'] = get_setting(
            weapon.get('type', 'none'), 'none',
            lambda x: x in (
                '1hs', '1hp', '1hb', '2hs', '2hp', '2hb',
                'h2h', 'shield', 'none'))
        for field in ('damage', 'delay', 'damage_bonus'):
            weapon[field] = get_setting(
                weapon.get(field, 0), 0,
                lambda x: 0 <= x <= 1000)
        weapon['proc_threat'] = get_setting(
            weapon.get('proc_threat', 0), 0,
            lambda x: -100000 <= x <= 100000)
        weapon['proc_landed'] = get_setting(
            weapon.get('proc_landed', ''), '')
        weapon['proc_resisted'] = get_setting(
            weapon.get('proc_resisted', ''), '')
        threat[hand] = weapon

    # Complete Heal rotation monitor.
    data['heals'] = data.get('heals', {})
    data['heals']['geometry'] = get_setting(
        data['heals'].get('geometry', [560, 700, 520, 220]),
        [560, 700, 520, 220],
        lambda x: isinstance(x, list) and len(x) == 4)
    for key, default in (
        ('toggled', False), ('clickthrough', False),
        ('auto_hide_menu', False), ('always_on_top', True),
        ('frameless', True), ('enabled', True), ('notify_turn', True)):
        data['heals'][key] = get_setting(
            data['heals'].get(key, default), default)
    data['heals']['opacity'] = get_setting(
        data['heals'].get('opacity', 94), 94,
        lambda x: 25 <= x <= 100)
    data['heals']['interval'] = get_setting(
        data['heals'].get('interval', 3), 3,
        lambda x: 1 <= x <= 9)
    data['heals']['cast_seconds'] = get_setting(
        data['heals'].get('cast_seconds', 10), 10,
        lambda x: 1 <= x <= 20)
    data['heals']['hotkey_format'] = get_setting(
        data['heals'].get('hotkey_format', '### - CH - tankname'),
        '### - CH - tankname',
        lambda x: '###' in x and 'tankname' in x.casefold())
    data['heals']['own_marker'] = get_setting(
        data['heals'].get('own_marker', ''), '')

    # Native view over PigParse's public Green market data.
    data['market'] = data.get('market', {})
    data['market']['geometry'] = get_setting(
        data['market'].get('geometry', [180, 100, 980, 620]),
        [180, 100, 980, 620],
        lambda x: isinstance(x, list) and len(x) == 4)
    for key, default in (
        ('toggled', False), ('clickthrough', False),
        ('auto_hide_menu', False), ('always_on_top', False),
        ('frameless', True)):
        data['market'][key] = get_setting(data['market'].get(key, default), default)
    # Search and filters must always receive pointer and keyboard input.
    data['market']['clickthrough'] = False
    data['market']['opacity'] = get_setting(
        data['market'].get('opacity', 100), 100,
        lambda x: 40 <= x <= 100)
    data['market']['refresh_minutes'] = get_setting(
        data['market'].get('refresh_minutes', 10), 10,
        lambda x: 10 <= x <= 120)
    data['market']['auto_consider_lookup'] = get_setting(
        data['market'].get('auto_consider_lookup', False), False)
    data['market']['inventory_file'] = get_setting(
        data['market'].get('inventory_file', ''), '',
        lambda x: isinstance(x, str))
    raw_market_widths = data['market'].get('gear_column_widths', {})
    if not isinstance(raw_market_widths, dict):
        raw_market_widths = {}
    market_column_keys = {
        'name', 'effects', 'price', 'selected', 'ac', 'hp', 'mana',
        'astr', 'asta', 'adex', 'aagi', 'aint', 'awis', 'acha'}
    data['market']['gear_column_widths'] = {
        key: _bounded_int(width, 60, 38, 640)
        for key, width in raw_market_widths.items()
        if key in market_column_keys}

    # Local, read-only EverQuest view. Enabling is intentionally per-session.
    data['mobile'] = data.get('mobile', {})
    data['mobile']['eq_executable'] = get_setting(
        data['mobile'].get('eq_executable', ''), '')
    data['mobile']['game_fps'] = get_setting(
        data['mobile'].get('game_fps', 5), 5,
        lambda x: x in (2, 5, 10))
    data['mobile']['game_image_quality'] = get_setting(
        data['mobile'].get('game_image_quality', 'hd'), 'hd',
        lambda x: x in ('efficient', 'hd', 'native'))

    # Do not keep obsolete integration configuration in new saves.
    data.pop('discord', None)

def get_setting(setting, default, func=None):
    try:
        assert(type(setting) == type(default))
        if func:
            if not func(setting):
                return default
        return setting
    except:
        return default


def verify_paths():
    # verify eq log directory exists
    try:
        assert(os.path.isdir(os.path.join(data['general']['eq_log_dir'])))
    except Exception as e:
        raise ValueError(
            'Vantage · NO LOGS',
            'No valid log folder is selected.'
        ) from e

    # verify eq log directory contains log files for reading.
    log_filter = os.path.join(data['general']['eq_log_dir'], 'eqlog*.*')
    if not glob(log_filter):
        raise ValueError(
            'Vantage · NO LOGS',
            'No EverQuest log files were found in that folder.'
        )
