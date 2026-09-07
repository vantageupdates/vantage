# VantageUI releases

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
