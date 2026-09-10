# Vantage Companion 1.44.75 design QA

final result: passed

## Brand reference

- Selected source: `data/assets/vantage-companion-logo-source.png`
- Runtime master: `data/ui/icon-master.png`
- The same circular charcoal, antique-gold, teal-ring, faceted-diamond identity is used for the Windows executable, native splash/about surfaces, public site, favicon, and Companion PWA.
- Transparent corners and the 16, 20, 24, 32, 40, 48, 64, 128, and 256 px Windows icon frames were verified.

## Visual checks

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
- Exact 25%, 35%, 50%, and 75% panel presets were measured across every main window. Headers and controls remain in their authored lanes with no responsive reflow or overlap.
- Roll-up uses a compact 1:1 header, and expanding or restoring from the tray returns to the exact previous replica size.

## Accessibility checks

- Every table exposes Shift+F10 column controls for the focused column:
  wider, narrower, auto-fit, and reset. Width changes are announced and focus
  returns to the table after the menu closes.
- Items & Notes controls have descriptive accessible names, descriptions, and
  tooltips; item rows open by keyboard or double-click, and internal note links
  remain keyboard-selectable.
- Sticky Notes use native keyboard focus order, visible focus borders and
  explicit accessible names. Escape hides without deleting; Open returns focus
  to the same note, while Unpin removes only the floating presentation.
- Market effect links expose only the effect name as the action while casting
  requirements remain readable plain text.
- Decorative logos use empty alternative text where adjacent Vantage text already names the product; the README logo has a meaningful alternative.
- The Companion item/spell dialog now has a valid `aria-labelledby` target.
- External P99 Wiki actions identify that they open a new tab.
- Context-menu presets expose descriptive action names, tooltips, a checked current state, and remain keyboard-selectable through the native Qt menu.
- No information is communicated by logo color alone.
