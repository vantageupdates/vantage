# Vantage Companion 1.44.98 design QA

final result: passed

## Brand reference

- Selected source: `data/assets/vantage-companion-logo-source.png`
- Runtime master: `data/ui/icon-master.png`
- The same circular charcoal, antique-gold, teal-ring, faceted-diamond identity is used for the Windows executable, native splash/about surfaces, public site, favicon, and Companion PWA.
- Transparent corners and the 16, 20, 24, 32, 40, 48, 64, 128, and 256 px Windows icon frames were verified.

## Visual checks

- Blank spell runtime keys now fall back to the spell name before widget,
  persistence, recast, or update-handoff identity comparisons. Multiple real
  P99 buffs such as Grim Aura, Focus of Spirit, Enlightenment, and Riotous
  Health coexist after update restore; a same-name recast replaces only itself.
- Numeric Vitals OCR now includes the complete compact EverQuest 0–9 alphabet
  and optional `%` glyph at their native 3–5 px widths. Component bands isolate
  same-color HP/mana fills and whole-token ranking prevents a digit inside
  `100` from winning as a false zero. All 101 values from 0 through 100 passed
  with and without the percent form, at 1x/2x scale, and beside green, blue,
  gold, or white bars; missing pixels are tolerated while two plausible labels
  still remain **NO READING** instead of guessing. The bounded 384-candidate
  search measured 20.627 ms per compact fixture across the complete 0–100 set,
  safely within the 500 ms poll interval.
- Vitals calibration no longer persists the previous two-pixel tight crop,
  which could validate on the frozen frame and then lose a shifted live glyph.
  Its fitted ROI now keeps bounded minimum margins of 5 px horizontally and
  4 px vertically. An end-to-end save/reload test retains the same reading
  after a two-pixel shift, one missing capture pixel, and an adjacent
  same-color bar, then verifies recalibration remains stable.
- Text-to-speech now defaults centrally to the legal local **Vantage Command**
  preset: Microsoft Mark, then David, another suitable installed voice, or the
  startup Windows voice. Explicit trigger/profile voices remain authoritative;
  unavailable saved voices remain visible and saved while the fallback is
  active. Notification routes, custom triggers, Smart Timers, and Vitals passed
  focused keyboard, status, and accessible-state review with no findings.
- Text-to-speech now silently prewarms Qt/SAPI on the Qt application thread,
  without speaking or taking focus. The measured Windows cold path was
  291–311 ms and cached access was approximately 0.005 ms. Automatic routes,
  Smart Timers, Vitals, tests, and replay replace stale queued announcements
  at Qt's immediate boundary; an allowed background alert does not require
  Vantage focus. Master Mute, master volume, per-window hidden-audio policy,
  saved voices/profiles, and each custom trigger's explicit interrupt choice
  remain authoritative.
- Sounds adds one explicit app-wide **Starting notification style** selector
  for **Beeps** or **Text to speech**, followed by **Apply to defaults**. It is
  a preview, not a bulk overwrite: custom/portable WAVs, non-default gallery
  sounds, explicit voices, and Off routes are preserved, while untouched routes
  receive their semantic default beep or Vantage Command speech. The visible
  result reports changed and preserved counts; per-route editors still win,
  Save persists the preview, and Cancel or close restores the prior state.
- Vitals Monitor now keeps the title bar compact, places **Add monitor** in
  the content area, and presents setup as three short steps. Each responsive
  card prioritizes the current percentage, textual state, confidence, and next
  action without a scrollbar-like progress bar. Calibration accepts a loosely
  placed rectangle, finds one unambiguous percentage within it, and saves a
  fitted ROI; padded, framed, ambiguous, 240 px, large-font, keyboard, focus,
  and screen-reader states passed focused and accessibility review.
- Existing Vitals overlays can now be renamed from the card's clearly labelled
  **Edit overlay** action. The same dialog keeps alert-stop editing while
  preserving the overlay ID, calibrated rectangle, thresholds, type, and
  enabled state; saving immediately rebuilds the card and persists the new
  name. Empty names remain in the dialog with a visible and announced error.
- Every Vitals overlay now exposes **Mute sound and speech at 100%**. It
  defaults On for Target/Mob HP so changing targets cannot repeatedly announce
  full health, while the visible Quick Bar notice and every lower alert stop
  remain active. The value is explicit after migration and persists through
  editing, type changes, save/reload, and an intentional user opt-out.
- Vitals now follows the shared parser replica contract: **Mini** produces the
  true 35% scaled replica instead of reflowing into a forced 240 px surface.
  Roll-up reduces the window to its header only, updates the accessible action
  to **Expand panel**, and restores the exact prior expanded or Mini geometry.
- Vitals Monitor now reads only the visible 0–100 HP/mana number, with an
  optional percent sign and no external OCR executable. The removed fill/color
  reader, direction, tolerance, and mode controls have no runtime or persisted
  path. A 1.44.92 numeric ROI migrates intact; an older bar-fill ROI is cleared
  so it requests safe recalibration instead of being misread as digits.
  Unreadable pixels remain **NO READING**, never a false zero.
- The single calibration flow is overlay over the number → announced valid
  preview → Save → alert stops with Sound/WAV, Text to speech, or Off. Save
  revalidates the number and ROI changes invalidate its preview. Keyboard focus
  order, calibration replacement/cancel focus restoration, dynamic state, form
  labels, and narrow layout passed final WCAG 2.4.3 and 4.1.2 review.
- Vitals Monitor is a first-class Quick Bar window and reads only the compact
  number pixels selected in EverQuest. My HP, My Mana, Target/Mob HP, Group
  HP, and additional custom bars run simultaneously. Direct window capture
  continues while Vantage or calibration has focus; only the safe screen
  fallback requires foreground EQ. Minimized, unavailable, unreadable, or
  low-confidence captures never become false zero values and never fire alerts.
- Every vital bar supports multiple directional thresholds, quarter/every-10%
  presets, hysteresis, cooldown, and independent Sound/WAV, Windows TTS, or Off
  delivery. Calibration supports pointer, keyboard, and exact numeric geometry;
  its temporary overlay closes safely and never controls EverQuest.
- The built-in **Mob is casting** trigger recognizes the classic P99
  `<actor> begins to cast a spell.` line conservatively, excludes the player's
  own cast form, rate-limits each actor, and exposes the same Sound/WAV, TTS,
  voice, volume, pitch, and Test controls as other Basic triggers.
- Smart Timers now choose Sound/WAV, Text to speech, or Off per timer. Speech
  templates support timer, state, zone, and remaining-time tokens; saved and
  synced legacy timers retain their previous inherited sound behavior. The
  editor uses scrolling/reflow rather than allowing death-detection and audio
  controls to overlap.
- Smart Timer zone views now isolate timers by their exact saved zone;
  unassigned rows remain in **All saved timers** instead of leaking into every
  zone. Each timer window adds a searchable **Watch timers** checklist for
  explicitly showing selected timers from other zones without copying or
  moving their shared state. External rows identify their origin zone, and
  each primary or extra timer window persists its own selection through
  restart and Device Sync. Keyboard, focus, accessible state, minimum-scale
  layout, mobile snapshots, and visible-timer sharing were verified.
- Death detection now accepts either a full NPC name or a distinctive partial
  phrase of two or more contiguous words, so **Kennel Master** safely matches
  **Kennel Master Al`ele** while a generic one-word entry such as **Master**
  does not. The bundled named list now includes the missing Chardok hunter,
  named, and raid NPCs, including the verified 20-minute Kennel Master entry.
- Smart Timer death detection exposes a compact match list for each
  spawn timer. Users can add or remove multiple named mobs and placeholders;
  the field autocompletes from all 882 bundled P99 nameds while accepting
  custom PH names. Device Sync, persistence, and Share Timers preserve the
  list, and legacy regular-expression timers continue unchanged until edited.
- Companion updates preserve the exact live buff set through a separate,
  bounded atomic handoff. After the old process and its final config save have
  completed, the verified executable swap atomically stamps that handoff. A
  replacement process can therefore recover even if Windows drops its update
  environment marker, while any later normal/user save remains authoritative.
  Restoration is verified before the one-shot handoff is consumed, and a
  failed updater launch resumes ordinary spell persistence.
- Mobile item cards reuse the desktop P99 item cache and now expose complete
  weapon DMG/DLY values as plain numbers alongside the existing stats, effects,
  drops, quests, restrictions, and safe internal links.
- Home Screen pairing keeps its token in the client-only URL fragment, retains
  the last Companion host and offline cache, and automatically retries after
  Companion closes or restarts. A new QR is requested only for a missing or
  explicitly revoked link; the token is never placed in HTTP, manifests, or logs.
- Maps adds one native POI selector containing every current map label. Any
  selection centers the exact point; diamond entries and pointer-activated named
  labels open a native cached-loot list whose item buttons reuse Market's full
  card. Plain and uncached points retain clear states without parallel scraping.
- Device Sync checkpoints the active PC's latest log-backed authority before
  an update closes Vantage. Stale peers cannot erase the restored rows during
  startup, while a genuinely newer authoritative removal still wins.
- Spell timer persistence now follows landing-driven nParse semantics: a
  partial refresh, profile switch, camp, or cross-device rebuild cannot be
  mistaken for a worn-off event. Only confirmed expiry, worn-off, death, or
  explicit removal retires a synced row; defective 1.44.83 removal clocks are
  discarded while still-valid saved rows are retained.
- Active buffs now follow the paired PC with the latest real EverQuest log
  activity for each character. Its complete character-specific list replaces
  older copies, including recasts and ended timers, without changing another
  character's rows; stale PCs cannot merge or delete the current owner's data.
- Buffs/Spells and Device Sync expose the same independent active-buff sync
  opt-out. Turning it off prevents that PC from sending or receiving active
  buffs while Smart Timers, zones, settings, notes, and buttons keep syncing.
- Yellow and amber buff bars again use the same light label as every other
  normal spell bar. Their fills remain icon-derived and saturated, but are
  value-limited so the complete label stays readable without a black repaint.
- Zones adds a separate **Any Mob** workflow that searches the complete P99
  Wiki instead of the selected zone. Results keep a compact sortable table;
  selecting a mob exposes every parsed drop and related quest as a labeled,
  keyboard-accessible in-app link without replacing the selected-zone tabs.
- Lavastorm and Nektulos now load the complete classic P99/nParse map sets
  instead of mixing in revamped Live geometry. Source matching is
  case-insensitive and deterministic, and known classic zone-line positions
  validate that the live `/loc` marker stays inside both loaded maps.
- External Regeneration-family landings no longer inherit the receiving
  character's level. When another tailed character log names the cast, the
  same row resolves to the exact spell and preserves the caster's level.
  When EQ exposes only the shared recipient message, Vantage labels the rank
  unknown, uses a safe P99 level-cap upper bound, and lets the authoritative
  worn-off line end it. A short replacement guard prevents an older rank's
  delayed worn-off line from immediately removing the new timer.
- Mobile Guild exposes the saved-guild selector before its DKP views; Zones
  keeps its selector stable across polling and provides an explicit reload.
  Save to Home gives short platform-specific instructions and states the
  session-link limitation before the user creates a shortcut.
- Zones and Quests render their bundled local references before starting live
  Wiki work. All 122 selectable zone aliases and 906 quest titles were
  cross-checked against the packaged catalogs; a network failure preserves a
  useful card instead of replacing it with an empty/not-found screen.
- The Quick Bar exposes Sync My PCs as a first-class action. Notification
  messages retain their semantic text and add a compact channel label for
  Buffs/Spells, Combat/Timers, Market, Guild DKP, Chat, or System.
- New Combat tables fit the nine primary metrics to the visible viewport so
  the right edge ends on a complete heading; additional detail columns remain
  full-width behind horizontal scrolling. Every section remains manually
  resizable and any saved user widths continue to win.
- Device Sync uses the same scaled-dialog surface as the rest of Vantage, so
  resize presets and compact scaling manage every control instead of leaving a
  second unmanaged layout. Pairing, approval, online/offline state and install
  progress remain explicit at narrow and full sizes.
- Device connection checks and Connect/Approve/Remove operations run outside
  the visual thread. Peer-list selection and scroll position survive each
  status refresh; changed status and new approval requests are announced only
  while the dialog is visible.
- Right-click on line edits, multiline editors, editable combos and spin boxes
  now reaches the native Undo/Cut/Copy/Paste/Delete/Select All menu even inside
  scaled parser windows. Existing map, buff and table context menus remain
  routed to their owning controls.
- Items & Notes uses a single Find dumps action which lists valid inventory
  exports found recursively under the configured EverQuest root.
- Every Vantage data table now keeps authored initial widths while exposing
  each horizontal divider for direct resizing. Stretch, fixed, and automatic
  modes no longer trap clipped text such as long auction seller names.
- Column widths persist per surface and exact ordered header schema, so
  dynamic comparison and guild spreadsheet tables never restore widths onto
  unrelated data.
- Items & Notes was checked at its 900x570 design size in both tabs. The item
  filters, inventory table, action row, note list, editor, and linked preview
  stay inside the window without clipping or overlapping.
- A saved note can be converted in place to a 320x250 always-on-top Sticky
  Note. Its title, editor, save state, Open and Unpin actions remain usable at
  the 240x160 minimum; moving, resizing, closing, reopening and restarting do
  not lose content or geometry. Device Sync replacement refreshes the open
  editor and floating view as one record.
- Borderless Sticky Notes use a real rounded translucent surface, a distinct
  full-width move affordance and a visible resize grip anchored two pixels
  from the lower-right corner. The grip does not overlap Open or Unpin at the
  minimum size, and pointer plus keyboard geometry controls remain equivalent.
- Connect Logs checks common Program Files and AppData locations immediately,
  selects the folder with the newest EQ activity, and offers a bounded wider
  scan plus an always-available manual folder picker without blocking the UI.
- Log Searcher exposes one labelled filter row, an incremental-cache status,
  adjustable result columns and multi-row copy without modifying EQ logs.
- VantageUI account synchronization reports its pending state while EverQuest
  is open and exposes normal Windows-permission recovery without changing ACLs.
- The new Quick Bar backpack action uses the existing 24 px control lane and
  the reset geometry was widened to include it without compressing neighbors.
- Market's Discord copy actions use the established compact button treatment;
  linked item effects use the same internal-link color and interaction as other
  Market item links.
- Size comparison: `work/v14469-brand-sizes.png`
- Native splash: `work/v14469-brand-splash.png`
- Native About window: `work/v14469-brand-about.png`
- Mini replica captures: `work/v14469-spells-mini.png`, `work/v14469-timers-mini.png`, `work/v14469-market-mini.png`, and `work/v14469-combat-mini.png`
- The selected logo remains identifiable from 16 through 256 px on dark and light backgrounds.
- Exact 25%, 35%, 50%, and 75% panel presets were measured across every main
  window. Standard overlays, including Vitals, preserve their authored replica
  geometry instead of substituting a reflowed layout for a requested scale.
- Roll-up uses a compact 1:1 header, and expanding or restoring from the tray returns to the exact previous replica size.
- Self-buff rows are owned by the exact character and server that produced
  them. Selecting a character hides unowned legacy rows, while a new verified
  cast may safely claim its own legacy row without touching another profile.
- Unanchored log text can create a self buff only when it explicitly addresses
  the player. Short Bard twists from nearby players are ignored; locally cast
  twists remain visible but transient, silent, and excluded from persistence
  and device sync so normal song rotation cannot flood notifications.

## Accessibility checks

- Sounds Starting style passed focused WCAG 2.4.3, 2.4.6, 3.3.2, and 4.1.2
  review. The native selector has a visible buddy label and a deterministic
  keyboard path to Apply; its changed/preserved result is visible and announced
  politely without moving focus. Save/Cancel semantics are stated before the
  control, and protected custom choices remain exposed in their original route.
- Vitals overlay editing passed focused WCAG 2.4.3, 2.4.6, 3.3.1, 3.3.2,
  and 4.1.2 review. **Overlay name** is a visible buddy label and accessible
  name; empty-name validation is visible, announced, and returns focus to the
  field. **Edit overlay**, **Save overlay**, roll-up, and expand expose clear
  accessible names, and card rebuilding restores keyboard focus.
- The final accessibility-lead review passed WCAG 2.4.3 and 4.1.2 for Maps:
  the graphic label is a non-focusable pointer shortcut, while the native POI
  button/menu provides the complete named keyboard and screen-reader path.
  Loot dialogs restore focus to that stable selector after Escape or Close.
- One `#F7F8F8` label is used across every normal spell fill and its empty
  track. All 216 icon palettes meet 4.5:1; the measured yellow-family minimum
  is 4.5039:1, with no clipped black-text layer or focus/name changes.
- Every table exposes Shift+F10 column controls for the focused column:
  wider, narrower, auto-fit, and reset. Width changes are announced and focus
  returns to the table after the menu closes.
- Items & Notes controls have descriptive accessible names, descriptions, and
  tooltips; item rows open by keyboard or double-click, and internal note links
  remain keyboard-selectable.
- Sticky Notes use native keyboard focus order, visible focus borders and
  explicit accessible names. Escape hides without deleting; Open returns focus
  to the same note, while Unpin removes only the floating presentation.
- Log Searcher labels every filter and action, announces completed searches,
  and supports keyboard row selection and copying.
- Market effect links expose only the effect name as the action while casting
  requirements remain readable plain text.
- Decorative logos use empty alternative text where adjacent Vantage text already names the product; the README logo has a meaningful alternative.
- The Companion item/spell dialog now has a valid `aria-labelledby` target.
- External P99 Wiki actions identify that they open a new tab.
- Context-menu presets expose descriptive action names, tooltips, a checked current state, and remain keyboard-selectable through the native Qt menu.
- No information is communicated by logo color alone.
- Suppressing repetitive Bard-twist warnings does not suppress ordinary spell
  fading notices; those retain their visible semantic message and configured
  audio route. Transient Bard rows use the normal readable timer before clean
  removal and never flash a misleading Warning, Critical, or FADED state.
