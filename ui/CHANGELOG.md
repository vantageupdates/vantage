# VantageUI releases

## 1.44.71

Install folder: `VantageUI-v1.44.71`.

- Polish Group Invite/Disband and their Follow/Decline aliases with rounded
  70x16 native-size faces, a fine neutral-gray rim and distinct hover, pressed
  and disabled states. Keep corners transparent, without shared-art stretching.
- Separate the two buttons by five pixels, align them with the stats panel,
  and use the smaller native Font 2 for centered, unclipped captions.
- Preserve all native IDs, visibility/enable logic, group members, personal
  stats, gauges, window dimensions, and other controls/artwork.

Load manually with `/loadskin VantageUI-v1.44.71 1`. Native game rendering
still requires review in EverQuest; automated checks verify layout and assets.

## 1.44.70

Install folder: `VantageUI-v1.44.70`.

- Give the gold Vantage UI identity a faceted diamond/V emblem to the left
  of the wordmark. Preserve the separate native version frame and the header,
  hotbar and inventory slot dimensions. No version digits are baked into art.

- Give the inventory stat/resistance icon rail a ten-pixel gap from the actual
  equipment edge and sixteen from bags. The prior rail overlapped the wider
  equipment column by two pixels, although it cleared bags by four.
- Extend only the right-hand inventory statistics area by 34 pixels (389x355
  window). Keep equipment, bags, money, weight, bottom buttons and height fixed.
- Give HP/MANA and other resource values 72-pixel boxes, attributes/resists
  38-pixel boxes, and a shared right edge with 17 pixels of outer-frame clearance.
  Budget for `1,000/1,000` and `1,000` without changing the client's number format.
- Align the character heading and XP gauge with the expanded stat area while
  preserving the native labels, values, fonts, animations and XP binding.
- Add matching, native-size 10px stat icons to Actions and the group stats panel.
  Align labels and right-aligned values into separate columns. Actions keeps
  its 144x182 window, tabs and Camp/Sit/Walk buttons; resistance abbreviations
  MR/FR/CR/DR/PR have full-name tooltips. Group gains 28px of width for the
  personal stats and HP/MANA totals; member rows and native bindings stay fixed.

Load manually with `/loadskin VantageUI-v1.44.70 1`. Automated layout/asset checks
are not a substitute for reviewing the new dimensions inside EverQuest.

## 1.44.69

Install folder: `VantageUI-v1.44.69`.

- Add thirteen original, transparent 12-pixel fantasy stat icons alongside HP,
  MANA, AC, ATK, EXP, WEIGHT and the seven attributes in the main inventory. Align with
  the existing resistance icons, keep the abbreviations and live native values.
- Separate each unchanged coin icon from its amount. Amounts remain native
  money buttons, in small rounded neutral boxes with a restrained gold edge
  and distinct hover/pressed states. Click or drop on the amount to move money.
- Preserve inventory size, equipment/bag slots, resistance artwork, XP bindings,
  Actions, Options and the compact hotbar layout. Bag fullness is not simulated:
  the legacy XML has no verified per-bag free-slot counter binding.

Load manually with `/loadskin VantageUI-v1.44.69 1`. Artwork/geometry and automated
tests are checked; native game rendering and money interaction need manual review.

## 1.44.68

Install folder: `VantageUI-v1.44.68`.

- Replace the plain inventory-header name with the approved fantasy-style
  "Vantage UI" wordmark in satin gold. Keep the release version as a native
  readable label in its own fine rounded frame. The 215x237 window, 202x20
  header, ten buttons, 21 equipment slots and eight bag slots are unchanged.
- Polish Options with native-size rounded button states and two-pixel gaps in
  stacked rows. Keep persistent checked-state feedback, use muted gold selected
  tabs and thinner field/list outlines. Preserve all settings, bindings, page
  membership, window size, sliders and keyboard-assignment behavior.
- The separate UI updater now includes the retention policy already shipped in
  Companion 1.44.66: active plus two older fallbacks, with active/previous safety
  guarantees. Cleanup never runs while EQ is open; modified or unmanaged folders
  remain protected. This release does not change or rebuild Companion.

Load manually with `/loadskin VantageUI-v1.44.68 1`. Texture/geometry and automated
tests are verified; actual in-game rendering and interaction require manual review.

## 1.44.67

Install folder: `VantageUI-v1.44.67`.

- Rebuild Camp, Sit/Stand and Run/Walk button faces at their native 128x18 size,
  with symmetrical 7px rounded ends, smooth neutral relief and a fine gold rim.
  Preserve the 144x182 window, native actions, text, and four-pixel row gaps.
- Remove the nearly opaque dark corner backing from spell gem holder/background
  layers and all Spells header states. Use an antialiased rounded alpha mask;
  preserve central artwork, icon sockets, school tints and the grey outline.
- Make these controls' native background transparent and disable their extra
  border, so the image's rounded corners reveal the existing parent surface.
  Do not change parent window opacity, tint, positions, or character INIs.
- Remove pointed dark corners from all 18 equipment slot hints and the shared
  empty-slot background; smooth the thin gold frame across all 435 drawable
  inventory slots. Preserve slot sizes, item artwork and native bindings.
- Raise the chat input 6px above the bottom frame, retain its 21px height and
  use a thin gold outline with even side margins and a gap below the output.
- Separate Pet commands by 4px in both directions, using native-size rounded
  button faces. Preserve the 144x135 window, pet health/buffs and native commands.
- Clear dark tips around Close and Minimize in every button state without
  changing their symbols, positions or titlebar behavior.
- Preserve the original spellbar, casting footer and all health bars.
  The inventory tab now reads "VantageUI  v1.44.67".

Load manually with `/loadskin VantageUI-v1.44.67 1`. Asset coverage and native
bindings are checked automatically; final appearance still needs an EQ reload.

## 1.44.66

Install folder: `VantageUI-v1.44.66`.

- Add a 15px rounded casting tab below the last spell gem, with a 116x9
  inset progress bar. The spell window grows only 20px, from 130x280 to 130x300.
- Read the real native casting gauge (EQType 7), including interrupted casts;
  no simulated timers, per-gem progress imitation, or runtime hooks.
- Reuse the existing 23-color red-to-yellow-to-green casting ramp. The
  remaining-time fill counts down, reaches green near completion, and is empty
  while idle. Preserve the existing casting bar in the Target window.
- Keep every spell gem, icon, outline, and text rectangle unchanged. The
  footer is separated from the last label and remains inside the native frame.
- Retain the gold inventory identity tab, now showing "VantageUI  v1.44.66".

Load manually with `/loadskin VantageUI-v1.44.66 1`. Automated tests cover both
bar widths, live-fill boundaries, empty state, palette order, atlas gutters,
and unchanged spell controls. Native casting and interruption rendering still
need verification in EverQuest.

## 1.44.65

Install folder: `VantageUI-v1.44.65`.

- Add a compact, rounded identity tab above the inventory/hotbutton grid,
  with centered gold text reading "VantageUI  v1.44.65" on a dark neutral surface.
- Reserve 22px above the existing grid. The window remains 215px wide and
  becomes 237px high; all buttons, equipment, and bags keep their sizes,
  native bindings, columns, and spacing.
- Retain opaque window backgrounds and keep the tab inside the native client
  bounds. Its soft gold rim does not extend into the item slots.
- Packaging now rejects a missing, duplicate, or stale visible version label.
  Future releases must update the tab text alongside their release metadata.
- Preserve the separated Actions buttons and all health/casting/spell changes.

Load manually with `/loadskin VantageUI-v1.44.65 1`. Layout, asset bounds, and
version consistency are checked automatically. Native appearance needs an
EverQuest reload; no character positions or INIs are edited.

## 1.44.64

Install folder: `VantageUI-v1.44.64`.

- Reduce Camp, Sit/Stand, and Walk/Run buttons from 134x20 to 128x18,
  retaining their centers and leaving four clear pixels between rows.
- Give all five visual states dedicated, exactly sized rounded artwork.
  Each state is cropped before resampling so neighboring sprites cannot
  bleed into the gap. Keep the existing soft relief and restrained gold rim.
- Keep the Actions window at 144x182 and preserve native labels, aliases,
  stats, resist icons, tabs, and every other window's shared button artwork.
- Preserve the health/casting gradients, spell gems, inventory, and attack rim.

Load manually with `/loadskin VantageUI-v1.44.64 1`. Geometry, texture bounds,
transparent gutters, and native control references are tested automatically;
the final appearance still needs checking in EverQuest after a manual reload.

## 1.44.63

Install folder: `VantageUI-v1.44.63`.

- Changes the integrated casting gauge from fixed gold to the same 23-color
  perceptual palette used by health: red at the start, orange and yellow in
  between, and regular green in the final fifth of casting.
- Reverses the color thresholds for native EQType 7, which measures remaining
  casting time and counts down from full to empty. Color changes track actual
  client progress, not a repeating animation or a guessed spell duration.
- Uses the existing paired-gauge clipping technique with the original thin
  casting texture, preserving its 240x11 geometry, depth, position, and name.
  All added layers precede the name and disappear at zero fill; no idle color
  stripe or new standalone casting window.
- Makes the four live health separators slightly easier to see: white alpha
  rises from 26 to 36 out of 255 (10% to 14%), retaining one-pixel widths,
  placement and transparency. Applies to player, target, party and pet HP.
  Empty health rows still show no permanent markers. All other atlas pixels,
  health colors and shading remain unchanged.
- No spell-gem, inventory, bag, Actions, character INI, or Companion changes.
  School-based coloring is superseded by this requested progress-based ramp.

Load manually with `/loadskin VantageUI-v1.44.63 1`. Palette and geometry tests
do not verify native rendering, frame timing, or text contrast in game.

## 1.44.62

Install folder: `VantageUI-v1.44.62`.

- Lowers all eight spell-name labels by 3px without changing font, wrapping,
  horizontal centering, gem dimensions, icon positions or the 4px row gaps.
- Retains the full 26px native text-layout height. Its transparent bottom tail
  extends 2px into the gap, stopping 2px before the next button; it is not a
  painted surface. Tests separately budget two lines of visible glyphs inside
  the gem using the 8-9px glyphs / 12px line pitch observed in user captures.
- This is a bounded downward alignment correction, not automatic vertical
  centering by name length. Titanium's Label schema has no such option; pushing
  every label to the ideal single-line position risks overflowing wrapped names.
- Preserves all health colors, artwork, inventory, bags and Actions. No changes
  to character INIs or Companion. Uses the same published update locally.

Load manually with `/loadskin VantageUI-v1.44.62 1`. Native visual confirmation
is still required for both single-line and wrapped spell names.

## 1.44.61

Install folder: `VantageUI-v1.44.61`.

- Refines player, group, pet and target HP from five to 23 colors. Uses
  perceptually interpolated RGB samples, retaining the exact red/orange/yellow
  anchors and normal green. Steps are 5% up to yellow and 2% towards green,
  where the previous color jump was strongest. No mint tint or palette change
  to mana, experience, casting or numeric labels.
- Uses the existing native paired-gauge clipping technique, with declarations
  before their consumers and the correct +2px texture origin for group/pet.
  Keeps all HP geometry, bindings, background, dividers and relief unchanged.
  This is finer health-dependent stepping, not an invented time animation;
  native reveal behavior and performance must still be checked in game.
- Makes spell gems 28px tall again (from 32px), with matching rounded grey
  outlines and a 2px vertical inset for native 24px icons. Retains 4px row gaps,
  compact width and the full 26px wrapped-name box with a 1px vertical inset.
  The spell window is 32px shorter. Does not restore the clipped 20px labels.
- Preserves inventory, bags, Actions and attack artwork. No character INIs or
  Companion changes; the same verified release is used for local installation.

Load manually with `/loadskin VantageUI-v1.44.61 1`. Package, palette and
geometry checks are not verification of the native client's rendering.

## 1.44.60

Install folder: `VantageUI-v1.44.60`.

- Reserves 26px for each wrapped spell name instead of the clipped 20px box.
  Keeps three pixels above and below that text region inside each gem.
- Increases gem height only from 28px to 32px, with separate 4px row gaps.
  Keeps the compact 120px gem / 130px window widths, existing font, horizontal
  centering, colors and art. The native 24px icon is centered with a 4px inset.
- Adds a thin, antialiased grey rounded outline to each spell button. The edge
  is an independent non-interactive decoration, not part of the school-tinted
  surface, with a transparent center that cannot cover the icon or text.
- Increases the spell window height to contain all eight rows. No changes to
  inventory, bags, Actions, health, attack or any other window.
- Adds a regression check that rejects the previous clipped label geometry.
  This reserves two lines; Titanium labels do not support dynamic font fitting
  or conditional vertical centering. It is not a promise for arbitrary-length
  names or a substitute for checking the native client after reload.

Load manually with `/loadskin VantageUI-v1.44.60 1`. Character INIs and
Companion remain unchanged. In-game rendering still needs confirmation.

## 1.44.59

Install folder: `VantageUI-v1.44.59`.

- Makes the equipment section exactly three equal columns of seven square
  29px slots. Ammo joins the top of the third column; no equipment sits above
  the bags. Ranged remains directly below the right ring.
- Restores square bag proportions: eight 25px slots in a separate column,
  aligned with the equipment section at both top and bottom. No texture, icon,
  color or border-art processing; only slot rectangles and positions change.
- Preserves the 215px outer inventory frame, both five-button columns and every
  item binding. Does not change Camp/Sit, health, attack, spells or other windows.
- Adds a strict 7/7/7 geometry check that rejects the previous detached Ammo slot.

Load manually with `/loadskin VantageUI-v1.44.59 1`. Package/geometry checks are
not an in-game render; confirm the compact inventory after reloading.

## 1.44.58

Install folder: `VantageUI-v1.44.58`.

- Reverts only the Actions/Camp/Sit window height from 215px to its previous
  182px. Removes the extra bottom space introduced in 1.44.57 without changing
  its width, buttons, icons, colors or positions.
- Moves Ranged into the lower-right equipment cell below Ring2. Widens the bag
  column from 22px to 31px and aligns it with Ammo above, retaining the existing
  eight-row height and compact outer frame. Every native binding is preserved.
- Replaces the attack dot with a thin, rounded perimeter around the whole player
  window's client area. Native attack control retains red tint and blink timing;
  the center is fully transparent and no separate name rectangle is drawn.
- Adds low-alpha HP dividers and soft highlight/shadow relief to live health
  fills. Unlike the removed static tick overlays, these follow HP values and
  are not permanently painted across empty group positions. Keeps HP colors.
- Lowers spell-name padding for improved single-line centering, retaining the
  narrow gems and two-line wrapping. Titanium has no conditional vertical-center
  label field; this is a fixed inset, not automatic per-name layout.
- Keeps unrelated skin assets unchanged.
- Adds a regression limit on the spare space below the Actions buttons. Actions
  sizing is independent of inventory sizing; do not enlarge it to match.

Load manually with `/loadskin VantageUI-v1.44.58 1`. Saved character INIs,
other skins and Companion are not changed. This restores the prior XML size;
actual rendering after reload has not been independently verified.

## 1.44.57

Install folder: `VantageUI-v1.44.57`.

- Follows the user's final compact inventory screenshot: the original two-by-five
  hotbuttons, equipment grid and eight small bag cells, all visible in a 215px
  high window. No extra pages or scrollbars. Removes the old one-pixel cell
  overlaps; preserves every equipment, bag and hotbutton binding.
- Matches the Actions/Camp/Sit window height to the compact inventory so their
  frames can form a level bottom row. Does not change saved window positions,
  other skins or character INIs. Keeps Actions width unchanged.
- Restores 120px spell gems with 24px icons, two-pixel row gaps and smaller
  centered labels that wrap to two lines instead of widening the spell bar.
- Removes the player-name rectangle from the attack artwork itself, retaining
  only a tiny rounded indicator under native client attack-state control.
  AutoDraw alone did not remove the white rim in 1.44.56.
- Removes the floating HP tick overlays, including markers in empty group slots,
  and reverts the extra 5-percent color layers to the previous native palette.
  Retains HP/mana separation, fine gold borders and the 1.44.55 XML/resist fixes.

Static geometry and package tests do not prove Titanium's item rendering inside
the compact cells. Reload in game and check small bag/item icons, wrapped names,
both attack states and the bottom-row frames. School-dependent cast-bar color
remains pending a supported client/Companion integration; it is not implemented.

## 1.44.56

Install folder: `VantageUI-v1.44.56`.

- Widens the eight spell gems from 120 to 192px, with 140px centered name
  labels, native-sized icons inset inside their wells and 2px between rows.
  Keeps the original textures, spell bindings, font and school colors.
- Separates player HP and mana by 3px instead of overlapping them by 3px.
  Keeps the name clear of HP, and declares the HP separators before the window.
- Disables automatic drawing of the native attack indicator so it no longer
  paints a permanent white outline. The client still controls attack blinking;
  no artificial animation loop or attack-state binding is added.
- Adds geometry, spacing and native attack-draw regression coverage.
- Reorganizes the compact hotbar into two columns of five buttons, two vertical
  columns of seven equipment slots, and one column of eight bag slots. The seven
  remaining equipment slots sit beneath the buttons. The window is narrower
  (226px instead of 306px), but taller (386px); native 40px item art is retained
  rather than cropped to simulate smaller bags. No equipment binding is removed.
- Uses fine, softened gold slot borders and light, opaque 1px HP separators.
  Keeps game item/spell artwork and atlas coordinates intact.
- Adds interpolated native health-color steps every 5% rather than 20%, retaining
  normal green at high HP and yellow/orange/red at lower HP. This smooths the
  palette but is not a time-animated continuous transition, which XML cannot bind.
- School-dependent casting-bar color remains a separate Companion integration
  decision: the native gauge has no current-spell-school color binding.

The 1.44.55 client log confirms its fatal XML load error is gone. This new
version still needs manual `/loadskin VantageUI-v1.44.56 1` verification for
spell fitting and both attack states; static tests are not an in-game render.

## 1.44.55

Install folder: `VantageUI-v1.44.55`.

- Declares the target health-bar components before their parent window, fixing
  the four unresolved ScreenPiece references reported by the actual EQ client.
- Moves all five inventory resistance icons clear of the bag slots: a four-pixel
  overlap is replaced by a four-pixel gap. Keeps their native 12px artwork intact
  and aligns resistance labels and values without changing the window size.
- Adds regression checks for declaration order and icon/slot separation,
  including fixtures reproducing both defects from 1.44.54.
- Retains the 1.44.54 Windows-permissions fix, prior versions and character INIs.

Load manually with `/loadskin VantageUI-v1.44.55 1`. Actual in-game loading and
visual confirmation must follow reload; package/static checks alone do not
prove client compatibility. Existing visual/client limits below still apply.

## 1.44.54

Install folder: `VantageUI-v1.44.54`. Supersedes 1.44.53 without overwriting it.

- Includes the same reviewed visual polish and all 176 skin assets from 1.44.53.
- Fixes new Windows installation folders inheriting a private administrator-only
  staging ACL. New publish folders inherit the normal parent permissions, so
  EverQuest and Companion can read the installed skin from a normal session.
- Does not change the parent `uifiles` permissions or any existing skin folder.
  Private download staging, path guards, locks and hash verification stay intact.
- Preserves the previous managed version, the legacy source and character INIs.

After installation, load the new version manually:

```text
/loadskin VantageUI-v1.44.54 1
```

The visual/client limits documented under 1.44.53 still apply. This is an
independent UI release; it does not build or publish `Vantage.exe`.

## 1.44.53

Install folder: `VantageUI-v1.44.53`.

- Dark opaque surfaces, fine gold borders and softly raised buttons/spell gems.
- Consistent native slot borders across inventory, bags, bank, trade and loot.
- Compact 306x302 equipment/hotbutton panel: native40px icons, aligned equipment
  and bag columns; no resizing that could clip the controls.
- Camp, Sit/Stand and Run/Walk no longer overlap, with room below the final row.
- Segmented health bars with more depth and LED-green high-health tint,
  transitioning through yellow, amber/orange and red at the native thresholds.
- Target health uses the same native threshold/clipping design as player health.
- Attack-indicator geometry stays within the title strip, with a transparent,
  antialiased rounded rim instead of a jagged opaque rectangle.
- Existing spell/buff/equipment artwork, mana bindings and dark backgrounds
  remain intact; no global theme tint was added.
- UI-only build automation now builds only `VantageUI-Updater.exe`, with focused
  and complete tests and a fresh version-checked executable self-test report.

After updating, load it manually in EverQuest:

```text
/loadskin VantageUI-v1.44.53 1
```

The updater installs the new version folder; it never changes character INIs or
the skin currently loaded by the game. This release does not update Companion.

Client limits: native code controls the attack indicator's red color; the green
request is not implemented by this texture-only fix. Casting-bar color cannot
inherit the active spell's school through the verified Titanium XML interface.
The known pre-existing `IW_Stats` reference remains unchanged. Static asset,
binding and layout checks do not replace an actual in-game visual test.
