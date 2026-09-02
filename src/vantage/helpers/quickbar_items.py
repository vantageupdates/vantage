"""Stable Quick Bar action catalog shared by config, settings, and UI."""


QUICKBAR_ITEMS = (
    # key, label, icon, group
    ("maps", "Maps", "ph-map", "windows"),
    ("spells", "Buffs & Triggers", "ph-wand", "windows"),
    ("tick", "Server Tick", "ph-gauge", "windows"),
    ("timers", "Smart Timers", "ph-countdown", "windows"),
    ("combat", "Combat Parser", "ph-sword", "windows"),
    ("heals", "Heal Chain", "ph-heal", "windows"),
    ("market", "Green Market", "ph-storefront", "windows"),
    ("spell_library", "Spell Library", "ph-spellbook", "tools"),
    ("mobile", "Vantage on Your Phone", "ph-mobile", "tools"),
    ("reload_ui", "Reload Vantage UI", "ph-reload", "tools"),
    ("updates", "Check for Updates", "ph-download", "tools"),
    ("log_status", "Log Status", "ph-pulse", "logs"),
    ("link_logs", "Select Logs Folder", "ph-folder-open", "logs"),
    ("log_help", "How to Link Logs", "ph-file-search", "logs"),
    ("log_profiles", "Log Profiles", "ph-stack", "logs"),
    ("mute", "Mute All Sounds", "ph-mute", "audio"),
    ("settings", "Settings", "ph-settings", "system"),
    ("about", "About & Licenses", "ph-info", "system"),
    ("quit", "Quit Vantage", "ph-power", "system"),
    # Support is deliberately last in both horizontal and vertical layouts.
    ("support", "Buy me a coffee", "ph-coffee", "tools"),
)

QUICKBAR_ITEM_KEYS = tuple(item[0] for item in QUICKBAR_ITEMS)
QUICKBAR_ITEM_LABELS = {item[0]: item[1] for item in QUICKBAR_ITEMS}
