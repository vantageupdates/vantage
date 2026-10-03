# Compact desktop polish — Vantage Companion 1.44.123

## Scope and use

This is conservative Companion polish for compact/laptop layouts, not a native
EverQuest skin redesign. Quick Bar actions, volume control, notification queues,
saved preferences and window presets retain their existing behavior. VantageUI
has an independent version and publisher; its skin, release metadata and updater
core are unchanged. The running game, WinEQ and installed Companion are untouched.

Quick Bar notices now use the intended 12px logical font instead of a stylesheet
override of 9px. The category, text and History button occupy distinct lanes.
Marquee text is clipped to its message viewport, retains its full natural width
and completes one pass. Reduced-motion text is elided to the current available
width and expands again when space returns. Full text remains in the tooltip,
accessibility description and Notification History. Rail height stays 19px.

Window restoration fits the actual native frame to the available desktop,
including taskbar space, and does not undo that fit after showing the window.
Windows already fully inside a screen retain their exact geometry. Monitor,
available-area and scaling events queue a recovery; ordinary movement does not.
Recovery waits for an active drag/resize to finish. Secondary monitors with
negative coordinates and partial overlap are supported. No preferences reset.

Notification overlay titles/details wrap, use plain text and retain user font
settings. A long name cannot force the saved window wider. Header menu buttons
use quiet dark chrome with distinct focus/hover states; local fixed-size controls
remain authoritative. Market reserves its refresh button's longest styled
caption, removing an independently confirmed 27px search-field jump when async
refresh finishes. Its data/request behavior is unchanged.

## Verification

- Final combined focused suite: **45 passed**, exit **0**, **105.30 seconds**.
  Covers rail queue/marquee/reduced-motion/history behavior, native accessibility
  names, overlay fonts/wrapping, window reload/presets/resize/headers, monitor
  recovery and unchanged keyboard/pointer/scaled-interaction contracts.
- New screen-recovery tests cover a simulated 1920×1040 work area, off-screen
  and oversized windows, native frame margins, negative secondary-monitor
  origins, overlap selection, coalescing and drag deferral. They preserve exact
  in-bounds geometry and do not substitute for physical monitor testing.
- New Market tests cover font size, style padding, minimum width and controlled
  offline async completion. Both captions retain the same search/tab geometry;
  the existing scaled-interaction test was not weakened.
- The initial whole-suite run found two geometry regressions and 55 failures in
  Windows updater fixtures. The mute-height rule was removed and Market's busy
  caption was made stable. The updater fixtures failed under restricted ancestor
  handle access; a normal-permission isolated test passed. No updater protection
  was changed or bypassed.
- A normal-permission diagnostic run then exposed unrelated live network work
  in the Quests accessibility fixture: **1,758 passed, 1 failed, 2 skipped**.
  The fixture now settles controlled offline catalog replies before testing
  focus/debounce/checklist behavior. Every existing assertion remains intact.
  Accessibility and adjacent network-recovery checks passed: **2 passed**,
  **16.03 seconds**. Production code and the frozen candidate did not change.
- Complete final suite: **1,759 passed, 2 skipped**, exit **0**, **970.34 seconds**.
  No tests were deselected. The two optional/platform skips remain explicit in
  the isolated JUnit report. Whitespace validation passed.
- Themed isolated captures were reviewed for Quick Bar at **779×72** and
  **600×55**, Map at **520×400**, Vitals at **420×360**, and notification overlay
  at **320×150**, plus separate **1.25×/1.5×** scale probes. Geometry stayed fixed;
  effective rail text height increased from 13 to 17px at 779px and from about
  10 to 13px at 600px. These are synthetic Qt renders, not in-game screenshots.
- A read-only Qt screen probe reported logical 1920×1200, available 1920×1170,
  logical DPI 96 and device ratio 1.5. This does not establish the cause of the
  user's screenshot or claim a physical 1080p mode. OS scale was not changed.
- Independent read-only review found no actionable regression in the final
  header style, fixed mute control or styled Market caption sizing.
- The Qt UI design and frontend UI standards skills informed shared metrics,
  explicit keyboard focus/state, native controls and conservative preserved
  geometry. The web-only accessibility orchestrator was inspected but not used
  to claim native Qt compliance. Physical screen-reader, OS-large-font, in-game
  reload and real monitor-disconnection testing are not claimed.
- Final single-file Windows portable built with **vantage.spec**. Its isolated
  **--portable-self-test** exited **0** and reported **1.44.123**. Windows file and
  product versions match. Frozen archive inspection confirmed the final monitor
  watcher, notification viewport/theme and stable Market refresh component.
- Tested candidate: **75,879,674 bytes**, SHA-256
  **44f8ab17adf192fd6043251de67372754cdae150f4614452579108dfc8759b93**.

All tests/captures use isolated profiles and synthetic game directories. No
real character INIs, game binaries or installed executable were replaced.

## Release verification

The final complete suite and portable candidate are verified above. Public
release metadata is pending; publication confirmation will be recorded here.
