"""Hierarchical trigger group helpers shared by the editor and runtime."""

from __future__ import annotations

import re


_HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
_STYLE_KEYS = {'font_color'}


def normalize_trigger_color(value):
    """Return one safe RGB color or an empty value meaning inherit."""
    value = str(value or '').strip()
    if not value or value.casefold() in {'inherit', 'default', 'blank'}:
        return ''
    named = {
        'white': '#F2EAD8', 'yellow': '#E5C267', 'gold': '#D5A14B',
        'orange': '#D9894C', 'red': '#DF706A', 'green': '#82B98D',
        'lime': '#A3C979', 'blue': '#7EA7CE', 'cyan': '#76B7B2',
        'purple': '#A98BC7', 'violet': '#A98BC7', 'pink': '#D58BA6',
        'gray': '#A7A7A7', 'grey': '#A7A7A7', 'black': '#17191D',
    }
    value = named.get(value.casefold(), value)
    return value.upper() if _HEX_COLOR.fullmatch(value) else ''


def _style(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in _STYLE_KEYS:
        normalized = normalize_trigger_color(value.get(key))
        if normalized:
            result[key] = normalized
    return result


def normalize_group_path(value):
    """Return a stable slash-separated path, never an empty group name."""
    parts = [
        part.strip() for part in str(value or '').replace('\\', '/').split('/')
        if part.strip()
    ]
    return '/'.join(parts) or 'Default'


def group_ancestors(value):
    """Return every parent path from the root through ``value``."""
    parts = normalize_group_path(value).split('/')
    return ['/'.join(parts[:index]) for index in range(1, len(parts) + 1)]


def _definition(value, order=0):
    if isinstance(value, bool):
        return {
            'enabled': value, 'profiles': {}, 'style': {},
            'profile_styles': {}, 'order': order}
    if not isinstance(value, dict):
        value = {}
    profiles = value.get('profiles', {})
    if not isinstance(profiles, dict):
        profiles = {}
    profile_styles = value.get('profile_styles', {})
    if not isinstance(profile_styles, dict):
        profile_styles = {}
    try:
        saved_order = int(value.get('order', order))
    except (TypeError, ValueError):
        saved_order = order
    return {
        'enabled': bool(value.get('enabled', True)),
        'profiles': {
            str(name).strip(): bool(enabled)
            for name, enabled in profiles.items() if str(name).strip()
        },
        'style': _style(value.get('style', {})),
        'profile_styles': {
            str(name).strip(): _style(style)
            for name, style in profile_styles.items()
            if str(name).strip() and _style(style)
        },
        'order': max(0, saved_order),
    }


def normalize_trigger_groups(spells):
    """Migrate legacy categories and return a complete group registry."""
    raw = spells.get('trigger_groups', {})
    if not isinstance(raw, dict):
        raw = {}
    legacy = spells.get('trigger_categories', {})
    if not isinstance(legacy, dict):
        legacy = {}

    paths = []
    for path in list(raw) + list(legacy):
        paths.extend(group_ancestors(path))
    for item in spells.get('custom_timers', []):
        if isinstance(item, (list, tuple)):
            category = item[9] if len(item) > 9 else 'Default'
            paths.extend(group_ancestors(category))
    if not paths:
        paths = ['Default']

    groups = {}
    for order, path in enumerate(dict.fromkeys(paths)):
        source = raw.get(path, legacy.get(path, True))
        groups[path] = _definition(source, order)
    spells['trigger_groups'] = groups
    spells['trigger_categories'] = {
        path: definition['enabled'] for path, definition in groups.items()
    }
    return groups


def group_enabled(spells, category, profile=''):
    """Check the group and every ancestor, applying character overrides."""
    groups = normalize_trigger_groups(spells)
    profile = str(profile or '').strip().casefold()
    for path in group_ancestors(category):
        definition = groups.get(path, _definition(True))
        enabled = definition['enabled']
        if profile:
            override = next((
                value for name, value in definition['profiles'].items()
                if name.casefold() == profile), None)
            if override is not None:
                enabled = override
        if not enabled:
            return False
    return True


def set_group_enabled(spells, category, enabled, profile=''):
    """Set a global group state or an exact per-character override."""
    groups = normalize_trigger_groups(spells)
    path = normalize_group_path(category)
    for ancestor in group_ancestors(path):
        groups.setdefault(ancestor, _definition(True, len(groups)))
    definition = groups[path]
    profile = str(profile or '').strip()
    if profile:
        # Keep the most recently typed casing while replacing a prior match.
        for name in list(definition['profiles']):
            if name.casefold() == profile.casefold():
                definition['profiles'].pop(name)
        definition['profiles'][profile] = bool(enabled)
    else:
        definition['enabled'] = bool(enabled)
        spells.setdefault('trigger_categories', {})[path] = bool(enabled)
    spells['trigger_groups'] = groups
    return definition


def group_state(spells, category, profile=''):
    """Return the state configured directly on one group (not ancestors)."""
    groups = normalize_trigger_groups(spells)
    definition = groups.get(normalize_group_path(category), _definition(True))
    profile = str(profile or '').strip().casefold()
    if profile:
        for name, enabled in definition['profiles'].items():
            if name.casefold() == profile:
                return enabled
    return definition['enabled']


def group_style(spells, category, profile='', inherited=False):
    """Return a group's direct or inherited style for one character."""
    groups = normalize_trigger_groups(spells)
    paths = group_ancestors(category) if inherited else [normalize_group_path(category)]
    profile = str(profile or '').strip().casefold()
    result = {}
    for path in paths:
        definition = groups.get(path, _definition(True))
        result.update(_style(definition.get('style', {})))
        if profile:
            for name, style in definition.get('profile_styles', {}).items():
                if name.casefold() == profile:
                    result.update(_style(style))
                    break
    return result


def set_group_style(spells, category, style, profile=''):
    """Set a direct group style globally or for one exact character."""
    groups = normalize_trigger_groups(spells)
    path = normalize_group_path(category)
    for ancestor in group_ancestors(path):
        groups.setdefault(ancestor, _definition(True, len(groups)))
    definition = groups[path]
    normalized = _style(style)
    profile = str(profile or '').strip()
    if profile:
        profile_styles = definition.setdefault('profile_styles', {})
        for name in list(profile_styles):
            if name.casefold() == profile.casefold():
                profile_styles.pop(name)
        if normalized:
            profile_styles[profile] = normalized
    else:
        definition['style'] = normalized
    spells['trigger_groups'] = groups
    return definition


def effective_trigger_style(spells, category, trigger_style=None, profile=''):
    """Resolve overlay defaults <- ancestor groups <- trigger override."""
    result = group_style(spells, category, profile, inherited=True)
    result.update(_style(trigger_style or {}))
    return result
