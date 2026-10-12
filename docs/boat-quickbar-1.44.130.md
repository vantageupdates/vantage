# Companion 1.44.130: Boat Schedules in the Quick Bar

## Usage

The Quick Bar now has a **Boat Schedules** boat icon immediately after Maps,
in either orientation. Click it to open its independent window; click it
again to hide it. Buffs does not open or reserve space for boat rows.

Choose **Green** or **Blue** above the estimates. Use **Refresh** to check
immediately. **Live schedules** checks once per minute even while the panel
is hidden; switch it off to pause. An intentional reopening from the Quick
Bar resumes it, while presentation changes such as frame or Always on Top
respect Off. Window placement, size, opacity, roll-up, and replica presets
use the same persisted controls as the other tools. Its Quick Bar visibility
can be configured alongside the other buttons.

At the actual dock arrival, choose **Sync arrival...**, select the arrival
point and public name, check the publication consent, and press
**Boat arrived · Sync**. The active character's server controls reporting;
viewing another server does not publish to it. Names remain self-reported.

## Implementation and boundaries

The new panel transfers the original BoatScheduleGroup and its live ETA
clock. Spells retains the one existing community client, local log parsing,
cache, and labelled PigParse fallback. Opening the panel does not enroll an
account or publish anything. Its parser entry is a no-op so every live log
line still reaches all later tools without duplicate spell or boat parsing.
The original Buffs boat control is a second launcher for the same panel.

No VPS code/configuration, installed Companion executable, running game,
VantageUI skin, updater, or character INI is changed by this release.
Reset UI Layout resets only the new panel's presentation, retaining existing
boat source data and preferences. All application labels remain English.

## Verification

Focused verification: **241 passed**, exit 0, in **47.58 seconds**. The new
window tests include actual Quick Bar use in both orientations, complete log
dispatch to downstream tools, independent geometry, every replica preset,
keyboard actions, consent, Green/Blue isolation, and Off remaining Off during
technical re-shows. Catalog and configuration tests cover default visibility,
reset scope, malformed settings, bundled artwork, and hidden startup.
The three vertical Quick Bar viewport cases also pass at 100%, 125%, and
150% display scale (**3 passed**, **25.46 seconds**). Their exact authored
height and scroll range now include the additional 24px Boat Schedules action;
the saved physical viewport, keyboard access, and original control sizes stay
unchanged. An earlier full run exposed these outdated expectations and was
stopped; it is not counted as the final release gate.
Additional scaled-interaction verification passed (**1 passed**, **9.09
seconds**). Header verification passed at all three display scales (**3
passed**, **27.54 seconds**), checking the exact 17-window set and retaining
all geometry, inset, elision, roll-up, keyboard, and no-overlap assertions.

Complete suite: **2,260 passed, 2 skipped**, **zero failures and errors**.
Four disjoint isolated shards cover all **196 modules** and exactly **2,262
unique collected test IDs**, verified against the original full collection:
640 cases (477.852s), 823 (316.646s), 400 (236.080s), and 399 (298.395s).
Every accepted shard exited 0. The skips are unavailable Windows symlink
privilege and POSIX permission bits that do not model Windows DACLs.
Earlier stopped/failed runs and corrected expectation checks are not substituted
for these completed passing full-suite shards. All **27** changed production,
version, artwork, stylesheet, and test files remained hash-frozen for the
accepted gates; no production change followed the final portable build.

The final portable build completed using `vantage.spec` in **116.346 seconds**.
Its isolated hidden `--portable-self-test` exited **0** and recorded **1.44.130**;
Windows file/product versions also match. Candidate **Vantage.exe** is
**75,978,458 bytes**, SHA-256
`5c5564c93207968c75b07b0065a4e4839c83b52464784d50b6007ba5705b1d93`.
The archive includes `vantage.parsers.boats` and `data/ui/icons/ph-boat.svg`.
Public release verification is recorded below.

Native previews use an isolated profile with external network, game capture,
audio, log discovery, and background services disabled; they do not replace
in-game verification. Normal and 150%-text previews show a dark scroll body;
large text uses vertical scrolling without clipping the controls.

## Public release verification

[Companion 1.44.130](https://github.com/vantageupdates/vantage/releases/tag/v1.44.130)
was published at **2026-10-12 23:21:39 UTC**. Anonymous HTTPS reads confirm
stable, non-draft, non-prerelease status and **Companion Latest**. Its sole
asset is **Vantage.exe**, **75,978,458 bytes**, GitHub digest
`sha256:5c5564c93207968c75b07b0065a4e4839c83b52464784d50b6007ba5705b1d93`,
exactly matching the frozen-source, built, and self-tested candidate.

The new annotated tag dereferences to verified source
`da568c51ac3347c0a7f8c3ab61867e64b35b73ff`; source and tag were pushed atomically,
without force or reuse. Publication used the already-saved Vantage credential
only in the publishing process; the machine's global GitHub account was not
changed. No installed executable was replaced, and no game, skin, or character
INI was modified. VantageUI retained its independent authority and channel.
