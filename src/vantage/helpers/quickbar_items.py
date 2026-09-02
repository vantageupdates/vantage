"""Stable Quick Bar action catalog shared by config, settings, and UI."""


QUICKBAR_ITEMS = (
    # key, label, icon, group
    ("maps", "Maps", "map", "windows"),
    ("spells", "Buffs & Triggers", "spells", "windows"),
    ("tick", "Server Tick", "timer", "windows"),
    ("timers", "Smart Timers", "spawn", "windows"),
    ("combat", "Combat Parser", "combat", "windows"),
    ("heals", "Heal Chain", "heal", "windows"),
    ("market", "Green Market", "market", "windows"),
    ("spell_library", "Spell Library", "search", "tools"),
    ("mobile", "Vantage on Your Phone", "mobile", "tools"),
    ("support", "Buy me a coffee", "support", "tools"),
    ("updates", "Check for Updates", "refresh", "tools"),
    ("log_status", "Log Status", "check", "logs"),
    ("link_logs", "Select Logs Folder", "add", "logs"),
    ("log_help", "How to Link Logs", "search", "logs"),
    ("log_profiles", "Log Profiles", "layers", "logs"),
    ("last_sound", "Replay Last Sound", "play", "audio"),
    ("mute", "Mute All Sounds", "stop", "audio"),
    ("settings", "Settings", "settings", "system"),
    ("about", "About & Licenses", "compact", "system"),
    ("quit", "Quit Vantage", "delete", "system"),
)

QUICKBAR_ITEM_KEYS = tuple(item[0] for item in QUICKBAR_ITEMS)
QUICKBAR_ITEM_LABELS = {item[0]: item[1] for item in QUICKBAR_ITEMS}
