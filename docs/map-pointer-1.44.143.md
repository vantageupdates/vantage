# Map pointer coordinates — Companion 1.44.143

The LOC beside the mouse describes the map point underneath the pointer, not
the player's position. It updates even while the character stands still and
no game log entries arrive. The player arrow is unchanged from 1.44.142.

## Correction

The previous outer-viewport fallback still depended on delivery of Qt mouse
movement events. The map now samples the desktop cursor every 40 ms while its
window is visible and interactive. Normal movement events still update the
readout immediately. Neither path depends on application focus or player data.

A pointer-transparent, no-focus label belongs to the physical window viewport,
outside the nested graphics scenes. It remains legible at miniature sizes,
follows the pointer, and stays inside the map edges. Coordinates are mapped
through the panel transform and active canvas, including zoom, pan and map
previews. Unchanged text and position do not trigger repeated label layout.

Sampling stops when hidden, minimized, rolled up, click-through or Pointer LOC
is switched off. The label hides over the header, outside the map, or during
native popups/dialogs. Keyboard L still shows the focused map coordinates and
retains their accessible description without changing the saved preference.

## Regression coverage

Isolated Qt tests substitute a cursor position without moving the user's
desktop cursor or sending any MouseMove events. They check independent cursor
movement without player data, inactive windows, miniature widths, 150% DPI,
preview/live transitions, stationary-pointer pan/zoom, window lifecycle,
keyboard access, popup dismissal and unchanged-position update suppression.
Existing event-delivery, map context, geometry and interaction tests remain.

These automated tests do not claim a live EverQuest session was reproduced.
The release preserves installed executables, game processes and user settings.
