# Source and data notice

Vantage contains extensively modified GPL-3.0 code derived from
https://github.com/nomns/nparse. The original copyright and license notices are
preserved here and in the repository history. Vantage modifications made in
2026 are distributed under the same GNU GPL version 3 license.

Market values are attributed in-app to PigParse Green. Project 1999 Wiki is a separately labeled secondary reference for item icons, statistics, drop NPCs, zones, and the shipped item-to-click-effect index. Robust estimates are local calculations and never alter upstream records.

Class, race and equipment-slot metadata is loaded from the P99 Planner community snapshot of Project 1999 Wiki data. It is not used as a price source. Optional mobile Internet sharing uses Cloudflare Quick Tunnels and downloads the official signed `cloudflared` Windows binary only with the user's approval.

The Windows release is a single-file executable. Runtime configuration and downloaded/cache data are stored under `%LOCALAPPDATA%\Vantage`, never beside the executable, unless a developer explicitly sets the test-only `VANTAGE_DATA_DIR` override.

The included Brewall 2024 map archive was supplied by the user for this build.
EverQuest, Project 1999, PigParse and Brewall are not affiliated with this
project. Their names and trademarks remain the property of their respective
owners.

Vantage is distributed free of charge. Donations are voluntary support for
development and never purchase the executable, access, updates, or features.
Gameplay parsing, timers, alerts, and map state are derived from user-enabled
EverQuest text logs or user-requested `/outputfile` exports. Vantage does not
read EverQuest process memory, inject into the client, automate input, or act
on a character. Optional read-only screen sharing mirrors user-selected window
pixels and is isolated from parsing and game control.

Public Project 1999 rulings state that programs which parse log files are
allowed provided they do not automatically control, respond for, manipulate,
or macro a character. Rules can change; users remain responsible for reviewing
the current server rules. Vantage is not endorsed by Project 1999.
https://wiki.project1999.com/Rulings#Log_Parsing_Programs

The classic spell sheets in `data/spells/classic_icons` and the current `spells_us.txt` index were supplied by the user from their local game client. They are used only to reproduce that client's buff icon mapping.

Zone respawn facts are normalized from a
[community-maintained respawn table](https://github.com/perotan/respawntimer)
and mapped to Vantage's 121 bundled P99 zone identifiers. The source is labeled
in the timer UI; unknown values remain unknown rather than receiving an inferred
timer.
