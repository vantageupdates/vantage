# Update installs both native buff layouts

The matched presets are **1.44.109 (VBuff)** and **1.44.110 (HBuff)**.
The skin version below the group logo and the buff window identity use these
labels. The vertical preset retains the familiar column, while the horizontal
preset retains the 576×168 two-row layout from 108. Fonts, icon sizes, spell
bindings, artwork and all other windows are unchanged.

## Installation and switching

Use this pair's new **VantageUI-Updater.exe**, then **Check for updates** →
**Update UI**. Updating to 110 verifies and installs both 109 and 110 automatically;
there is no separate preparation step. Opt-in automatic updates use the same
pair operation. **Buff hotkeys…** remains available to prepare or check the pair.

The success dialog provides both labels and copyable commands:

| Option | Command |
| --- | --- |
| (VBuff) — vertical | `/loadskin VantageUI-v1.44.109 1` |
| (HBuff) — horizontal | `/loadskin VantageUI-v1.44.110 1` |

Create two socials manually, one command on the first line of each. Switching
reloads the whole skin with settings preserved; it is not an instant rotation.
Canonical folder names remain numeric so existing manifest/readers and P99 skin
loading keep their verified contract. The visible labels identify the choice.

## Safety and limits

Both exact stable releases must verify before installation begins. Both final
trees must pass revalidation before the updater claims they are ready. Pair
installation is sequential, not atomic: if interrupted, a completed skin remains
available and retry can finish the pair. Do not reload the UI during installation.

Existing modified, unmanaged and legacy skin folders are not overwritten or
adopted. Registered older buff presets are retained. Ordinary single-release
downgrade guards and the narrow verified current-horizontal-to-vertical exception
remain intact. An updater older than a selected future release refuses the pair
and requires its current updater; it never silently installs stale presets.
After a successful pair update the registry selection is HBuff, with VBuff as
the previous selection. **Restore previous** therefore selects VBuff, not the
pre-update skin. Clean managed nonpreset versions outside the existing retention
set may be pruned under the established cleanup policy; edited or unknown folders
stay protected. The pair confirmation makes this distinction explicit.

Character INIs and socials are never written, no skin is loaded automatically,
and no game process is stopped. Close P99 before standalone installation unless
using the existing explicit game-running mode. The new updater executable is
downloaded manually; older executables keep their older behavior. Companion's
installed executable, its release/version and main are outside this UI-only change.

Published 104/108 and other previous releases remain immutable. XML/package and
updater tests are not proof of native P99 rendering; badge readability, existing
font wrapping, saved geometry, tooltips and cancellation still need an in-game check.
