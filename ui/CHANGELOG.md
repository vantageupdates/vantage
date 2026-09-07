# VantageUI releases

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
