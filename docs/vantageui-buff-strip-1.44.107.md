# VantageUI 1.44.107 (H): compact horizontal buff strip

UI-only change based on the user's icon-above/name-below reference. Companion,
its release channel, the main branch, character INIs and socials are not changed.

## Layout

- One visible row for the 15 P99 buff slots, rather than the previous 3 × 5 grid.
- Native 24 × 24 buttons and 20 × 20 decals; existing artwork is unchanged.
- 70 px column pitch. Native Font 1 names occupy 66 × 40 px below the icon,
  center aligned with wrapping enabled. Shadows retain the 1 px offset.
- 1066 × 100 px outer frame, with a small titlebar retained for dragging.
  Conservative client bounds are 1058 × 76 px. The strip fits a 1920 px screen;
  its size does not shrink dynamically to the active buff count.
- Explicit top/left anchors are retained for native buff buttons, whose engine
  placement may differ from plain XML Location values.
- All 25 native IDs, EQTypes, cancellation bindings and Piece order remain.
  Ten extra definitions stay beyond the visible pane; no extra buff capacity
  is claimed. Short-duration song effects are unchanged.

The spell-name presentation allowlist contains only NoWrap, AlignCenter and
AlignRight for the existing buff-name foreground/shadow labels. Number labels
and other native fields are not normalized away by the contract tests.

## Two immutable options

After closing EverQuest, run this release's VantageUI-Updater.exe and choose
**Buff hotkeys…**. It verifies both folders before showing commands.
Create two socials manually; the updater does not write hotkeys or game INIs.

| Option | Identification | First line of social |
| --- | --- | --- |
| Vertical | 1.44.104 (V) | `/loadskin VantageUI-v1.44.104 1` |
| Horizontal | 1.44.107 (H) | `/loadskin VantageUI-v1.44.107 1` |

These commands reload the whole UI with settings preserved; they are not an
instant rotation button. The Group badge identifies the loaded version.
Vertical 104 and old horizontal 105/106 releases are never overwritten.
Preparation from 105/106 installs verified 107 first, prepares 104 through
the narrow verified-107 exception, then selects 107 again. Ordinary downgrades
remain refused. Personal edits and unknown folders are protected, and a failed
or interrupted preparation does not claim that both layouts are ready.

## Verification limits

Geometry, conservative native insets, anchors, all control contracts, original
vertical normalization, generator idempotence and updater migration are covered
by automated tests. An independent image-only reviewer found no visible
clipping, overlap or misalignment in the private offline preview and 3× crops.

The preview uses original assets and XML dimensions but an approximate Windows
font, not a P99 screenshot. Its sample spell/icon mapping is not verified.
Actual Font 1 wrapping, native saved-size reload behavior, hover, dragging,
tooltip and right-click cancellation still require checking inside P99. Long
names have finite space and may differ from the preview. No running game or
installed live skin was changed by this release work.
