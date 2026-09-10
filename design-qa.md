# Vantage Companion 1.44.70 design QA

final result: passed

## Brand reference

- Selected source: `data/assets/vantage-companion-logo-source.png`
- Runtime master: `data/ui/icon-master.png`
- The same circular charcoal, antique-gold, teal-ring, faceted-diamond identity is used for the Windows executable, native splash/about surfaces, public site, favicon, and Companion PWA.
- Transparent corners and the 16, 20, 24, 32, 40, 48, 64, 128, and 256 px Windows icon frames were verified.

## Visual checks

- Items & Notes was checked at its 900x570 design size in both tabs. The item
  filters, inventory table, action row, note list, editor, and linked preview
  stay inside the window without clipping or overlapping.
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

- Items & Notes controls have descriptive accessible names, descriptions, and
  tooltips; item rows open by keyboard or double-click, and internal note links
  remain keyboard-selectable.
- Market effect links expose only the effect name as the action while casting
  requirements remain readable plain text.
- Decorative logos use empty alternative text where adjacent Vantage text already names the product; the README logo has a meaningful alternative.
- The Companion item/spell dialog now has a valid `aria-labelledby` target.
- External P99 Wiki actions identify that they open a new tab.
- Context-menu presets expose descriptive action names, tooltips, a checked current state, and remain keyboard-selectable through the native Qt menu.
- No information is communicated by logo color alone.
