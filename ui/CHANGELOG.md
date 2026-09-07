# VantageUI releases

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
