# Companion 1.44.141 — maps and preserved preferences

## Map behavior

- Pointer coordinates refresh without a held mouse button, recover on movement,
  toggle immediately on live and preview maps, and stay within viewport edges.
  The dark coordinate card does not intercept map clicks. Press **L** with map
  focus to read center coordinates; **Home** still fits the complete map.
- Existing hover and click-through preferences are respected. Click-through
  intentionally sends input to the game instead of the map.
- The red travel arrow is compact, with an outlined dot at the exact reported
  position. Its pointed shape remains visible at overview zoom. A screen-sized
  marker can still overlap a very narrow corridor; coordinates are never shifted
  to force the graphic inside walls.
- The first location does not invent a direction. Repeated XY or Z-only fixes
  retain known travel direction. Large jumps, implausibly fast movement and stale
  moving samples clear it until another plausible movement is observed. A log
  `/loc` is position, not character facing.
- Small authoring differences at Z-band boundaries no longer put the bundled
  Skyshrine maze labels on the previous floor. Nearby, almost-level geometry
  refines the player's floor when it supplies stronger local evidence. This
  affects layer emphasis, not the original map coordinates.
- Character/server identity accompanies map locations. A different character's
  coordinates cannot be drawn on the previous character's zone. Unknown zones
  wait for an identifiable zone; another character camping does not clear the
  current marker. Same-zone zoning clears stale location and heading.

## Settings preservation

- Restarting in the saved zone retains map zoom instead of replacing it with
  an automatic overview. Explicit Home and changing zones can still fit a map.
- Update checkpoint reopens the saved configuration and compares the entire
  settings snapshot, in addition to active buffs and Smart Timers. A mismatch
  stops update handoff and resumes live spell tracking.
- An explicitly selected 30-second spell-warning stop stays at 30 seconds.
- Quick Bar startup uses its existing exact saved-rectangle restoration so
  content rounding does not repeatedly shrink a customized bar.

No real user profile, EQ character INI, installed executable or VantageUI skin
is modified during development/release verification. Tests use disposable
profiles, including shutdown and separate-process restart. Existing on-screen
recovery can still bring an off-screen window onto an available monitor.

## Verification scope

Focused regressions cover Nektulos logged positions, Skyshrine bundled maze
geometry and a known ground location, hover edges/toggles/keyboard access,
multiple characters, zoning, saved zoom and complete preference checkpointing.
The app must still be checked in-game in the upper Skyshrine maze: no confirmed
live upper-maze `/loc` sample was available during diagnosis. No EverQuest input,
memory inspection or game-process changes are used.
