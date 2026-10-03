# Character UI copy and temporary map browsing — Vantage 1.44.122

## Use

Open **Quick Bar → VantageUI → Copy character UI…**. The Copy layout tab opens
first. Pick the source (searchable dropdown), search and check destinations,
choose all window/chat settings or specific UI sections, then **Copy to N
characters…**. Confirm the source, destinations, scope and backup in one dialog.
The source is never overwritten or included as a destination.

**Select shown** and **Clear shown** affect only search results. Other checked
characters stay selected, with a written hidden-selection count. **Clear all**
removes every destination. Typed source text must resolve to an actual dropdown
choice; an unmatched search cannot accidentally copy the previous character.
The last valid source is remembered; targets are not automatically selected on
a new dialog. The active logged character is used when no saved source matches.

For a partial copy, search the source UI sections (e.g. ChatWindow, BuffWindow,
GroupWindow, HotButtonWnd), check the sections and apply. Unselected target
sections remain byte-for-byte intact. Positions and sizes for saved screen
resolutions are included; this does not invent settings for a new resolution.
**Also use the installed VantageUI** is independent from layout scope. With it
off, every destination keeps its skin and Main settings. Layout copy can work
without installing VantageUI. With it on, only the verified installed skin can
be assigned; release discovery alone cannot assign an uninstalled version.

Version auditing and restoring backups have separate tabs, keeping the basic
copy screen compact. The main copy action stays visible when the form scrolls.
The progress bar is shown only when an operation begins. Existing permission
handling, rollback, backup digest validation and game-exit queue are retained.

## The two INI files

Read-only inspection of the user's Mindflux files confirmed that
`UI_Mindflux_P1999Green.ini` contains window sections and XPos/YPos/Width/Height
settings for 1280×720, 1280×960, 1920×1080 and 1920×1200. The regular
`Mindflux_P1999Green.ini` contains Friends, Ignored, HotButtons, abilities,
combat settings and Socials, with no position keys. Only section/key names
were inspected; macro or personal list content was not collected.

The requested window-layout copy therefore targets only supported
`UI_<character>_<server>.ini` files. It does not overwrite character/class
hotkeys, macros, friends, ignored players, eqclient.ini, game binaries or any
skin files. Copying both character INIs is not required for the window layout.
Changed targets receive a backup before writing. Identical targets are skipped;
restore first backs up the current files and can itself be undone.

EverQuest saves these INIs itself. When it is running, the confirmed operation
waits until it closes, rereads the saved source and then applies automatically.
Vantage never closes EverQuest/WinEQ or changes game-directory permissions.
Program Files protection uses the ordinary Windows elevation prompt. The same
selected sections and skin option are forwarded through that path.

## Verification

- Focused helper/UI integration suite: **87 passed**. Includes UI/regular-file
  separation, resolution-specific positions, selective merge, target Main
  preservation, absent-section insertion, idempotency, backup/restore, invalid
  section rejection and elevated scope forwarding.
- Search filters, cross-filter selection, source exclusion, unmatched source
  text, selectable scope, no-install layout copy and remembered source covered.
- Existing audit sorting, accessible status, keyboard navigation, action-focus
  restoration, version controls and permission paths retained and tested.
- Themed synthetic captures checked at 760×640 and 620×500, plus specific-window
  selection, version and restore tabs. Qt design guidance informed the three-step
  copy flow, progressive disclosure and persistent primary action. Physical
  screen-reader, in-game reload and OS-wide large-font testing are not claimed.
- Single-file Windows portable build completed with `vantage.spec`. Its isolated
  `--portable-self-test` exited **0** and reported **1.44.122**; embedded Windows
  file/product versions both match. The frozen archive contains the selective
  copy helpers, searchable/specific-window UI and temporary map browser.
- Candidate: **75,875,804 bytes**, SHA-256
  `45437ef38ce06d70e52d38793dfe58d1801eccbb22130eb1744ec1a35426517b`.
- Final combined focused checks: **115 passed**. Three outdated test assumptions
  found by the first complete run were repaired without changing production
  code: the keyword live-window fixture now uses a current timestamp (no days
  of accidental expiry backfill), update messages use `CURRENT_VERSION`, and
  geometry checks cover both the initially hidden and visible progress row.
- The VantageUI chat confirmed its independent **1.44.99** release is published,
  with no pending main changes or concurrent publication. Skin authority stays
  there; Companion 1.44.122 has one publisher and does not modify UI assets.
- Complete final suite: **1,746 passed, 2 skipped**, exit **0**, **943.95 s**.
  No tests were deselected; the two platform/optional skips remain explicit in
  the JUnit report. Public-release verification will be recorded after upload.

All writes during tests/captures use synthetic EverQuest installs and isolated
profiles. The user's installed executable and real character INIs are not
replaced. Companion patch version is independent; VantageUI skin/release
metadata is unchanged.

## Temporary map browser

Use the map icon in the Map window header (or **Browse maps…** in the canvas
context menu). Search/choose a bundled zone and press **View map**. Its title
and location HUD explicitly say **Preview**. The same button returns to the
current zone while previewing; the browser also offers **Back to current zone**.

Browsing keeps the original live canvas hidden, preserving its players,
waypoints, map timers and recording. The preview has a separate, owned scene;
it never emits `new_zone` or saves its zone/zoom as the character's last zone.
Existing location sharing continues to update the live canvas, not the preview.
POI selection/loot details use the displayed preview's labels and cache.
Opening a map from Zones or the Market zone view uses the same temporary path.

A validated new `/loc` returns to the live canvas **before** placing the arrow
and recording coordinates. A real zone change also exits preview. Unrelated
chat, invalid `/loc` and `/who` reporting the same zone leave it open. Movement
cannot be inferred when the game emits no location log line; no memory reader
or movement polling was added.

- Map/zone focused suite: **33 passed**, including seven new preview/search
  tests. Marker/timer identity, live-zone signal isolation, unchanged preferences,
  preview POIs, classic maps, repeated previews, invalid names, valid new `/loc`,
  actual zoning, search completion, Escape and manual return were exercised.
- Themed offscreen captures of the 400-pixel browser and 520×400 live/preview
  windows were visually reviewed. The Qt guide informed compact disclosure,
  explicit Preview state, native keyboard search and a direct return action.
