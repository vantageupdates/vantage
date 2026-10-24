# Companion 1.44.142 — previous arrow and reliable pointer LOC

## Changes

- Restores the pre-1.44.141 red arrow shape, size, original player icon and
  purple You label. Keeps the improved travel-heading and character attribution
  logic; this does not revert saved-preference protection or Skyshrine fixes.
- Corrects width-only native-window resizing: the actual map drawing/input
  surface now expands with the window even when its height stays unchanged.
  Previously a 400-to-640-pixel expansion could leave a 400-pixel inner viewport,
  making the right side an input dead region without a pointer LOC.
- Adds an event-driven pointer-LOC bridge from the physical panel viewport to
  the current map. Updates are coalesced after nested-proxy dispatch, without
  polling or consuming mouse input. Hidden/collapsed views do not show LOC.
- Right-click the map and select **Show pointer coordinates (/loc)** to enable
  or disable the readout. The header button's tooltip explicitly says On/Off,
  and both controls stay synchronized for live and preview maps.

## Verification scope

New tests exercise the outer panel viewport rather than sending events directly
to MapCanvas. They cover width-only expansion/contraction, compact sizes, preview
replacement, physical header-button activation, a simulated lost inner move,
leave/header behavior and keyboard selection in the real embedded context menu.

The width-only failure was reproduced before its fix. General hover worked in
other isolated configurations; these tests do not claim to reproduce every
native Windows/game configuration behind the user's report. The extra delivery
bridge is defensive against lost nested-view move events.

Existing hover-Off and click-through preferences are preserved, not silently
reset. Explicit click-through intentionally gives mouse input to the game.
No installed executable, real profile, EverQuest INI or VantageUI skin is changed
by release testing. All 1.44.141 update-preservation protections remain in place.
