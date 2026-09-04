"""Stable Quick Bar action catalog shared by config, settings, and UI."""


QUICKBAR_ITEMS = (
    # key, label, icon, group
    ("maps", "Maps", "ph-map", "windows"),
    ("spells", "Buffs & Triggers", "ph-wand", "windows"),
    ("timers", "Smart Timers", "ph-countdown", "windows"),
    ("tick", "Server Tick", "ph-gauge", "windows"),
    ("combat", "Combat Parser", "ph-sword", "windows"),
    ("heals", "Heal Chain", "ph-heal", "windows"),
    ("market", "Market", "ph-storefront", "windows"),
    ("spell_library", "Spells & Skills", "ph-spellbook", "tools"),
    ("mobile", "Vantage on Your Phone", "ph-mobile", "tools"),
    ("link_logs", "Select Logs Folder", "ph-folder-open", "logs"),
    ("log_help", "How to Link Logs", "ph-file-search", "logs"),
    ("log_profiles", "Log Profiles", "ph-stack", "logs"),
    ("mute", "Mute All Sounds", "ph-mute", "audio"),
    ("about", "About & Licenses", "ph-info", "system"),
    # Frequently checked status/recovery controls stay beside shutdown.
    ("log_status", "Log Status", "ph-pulse", "logs"),
    ("reload_ui", "Reload Vantage UI", "ph-reload", "tools"),
    ("updates", "Check for Updates", "ph-download", "tools"),
    ("settings", "Settings", "ph-settings", "system"),
    ("quit", "Quit Vantage", "ph-power", "system"),
    # Support is deliberately last in both horizontal and vertical layouts.
    ("support", "Buy me a coffee", "ph-coffee", "tools"),
)

QUICKBAR_ITEM_KEYS = tuple(item[0] for item in QUICKBAR_ITEMS)
QUICKBAR_ITEM_LABELS = {item[0]: item[1] for item in QUICKBAR_ITEMS}
