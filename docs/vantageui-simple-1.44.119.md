# Companion 1.44.119: simpler VantageUI updates

## User flow

1. Open **VantageUI**, or choose **Install / Update VantageUI** in Updates.
2. Select the EverQuest folder once if the saved folder is not the right one.
3. Press the highlighted **Install VantageUI / Update VantageUI** action.
   Discovery, verification, and installation continue without a second modal
   confirmation. That explicit action is the user's consent to the existing
   verified installation and configured character synchronization policy.
4. Wait for progress to finish. Do not reload the skin during installation.
5. Use **Copy /loadskin**, then paste the displayed command into EverQuest.

Automatic future skin updates remain an explicit opt-in. **More options**
contains Restore, character layouts, the existing all-character version option,
exact versioned paths, and operation details. The main screen keeps the game
path and installed/available versions visible. Native keyboard operation,
accessible labels, dark backgrounds, and the existing gold primary action are
preserved. Options scroll rather than forcing a wider window.

## Reliability fixes

- The Updates action is no longer dropped when opening the panel starts its
  local recovery check. One explicit request continues after a successful local
  read. A recovery failure clears it; concurrent installs are not queued.
- Release discovery carries the original confirmation mode to the install.
  A one-click request can finish while the user works in another window without
  opening an unsolicited dialog or moving keyboard focus. Callers that explicitly
  request confirmation retain the previous review/cancel behavior.
- Leaving an unchanged folder field no longer clears a known release. Changing
  the folder saves and resets discovery without launching an extra worker that
  would consume the first install click.
- Old-version reload instructions no longer compete with a known available
  update. The completion card shows the exact selected version's command.

## Ownership and safety

The publicly ready VantageUI release inspected for this integration was
**1.44.94**, tag commit `2072d8525d11dd4dbf5dd40b86416b38d85fd53e`.
The Vantage UI chat was notified of this Companion-only integration and the
reserved Companion patch. Discovery remains dynamic, not pinned to that version.

No `ui/skin`, `ui/release.json`, standalone UI updater, updater core, or character
profile helper code was changed. Existing release-origin/SHA-256 validation,
path validation, transactional recovery, locks, live-game install policy,
version retention, character INI backup/deferred switching, and normal Windows
permission handling are reused. A protected folder can still require the existing
Windows UAC/dedicated-updater path; this change does not alter permissions or
silently elevate. No live game process or user installation is replaced.

## Verification

Focused integration, Updates, and heartbeat tests: **63 passed**. Earlier focused
updater/profile coverage: **199 passed, 1 platform skip**. Added coverage includes
the collapsed/expanded panel, one-click discovery and direct installs, external
focus, failed checks, reload-card states, folder editing, the closed-panel Updates
race, failed recovery, and duplicate-install prevention.

Isolated Qt captures (install, update, completed, and expanded options at normal
and narrow widths) are under `work/vantageui-simple-1.44.119/`. They were visually
reviewed for background, hierarchy, path visibility, readable labels, and overflow.
These are native offscreen fixtures, not a live in-game installation or physical
screen-reader test.

The final single-file candidate reports FileVersion/ProductVersion **1.44.119**
and passed isolated portable self-test with exit **0**. Frozen inspection confirms
the one-click action, queued local-read continuation, reused installer, collapsed
options, packaged dark theme, and all 20 WAVs. It is **75,841,487 bytes**, SHA-256
`06FD737B4BE804DE318B477CED8A3DEB984B79057EC29E827556A18D31BF766A`.

The protected installed `D:\Vantage.exe` retained SHA-256
`4252139FFD85DE604FCFED2FA8D03A59B42D091C7BA225A045748076B617CE3F`;
the live profile retained SHA-256
`C418D49888A0E4B38FE0A34C9CA1075D57FD98F50E00981F2CF1C97B476BC0A5`.
Neither was changed by this work.

The final complete suite passed **1,697 tests**, with **2 platform skips**, in
**839.24 seconds**. Final draft metadata is recorded after upload.

Publication of the prior Companion draft
was blocked by the execution tool; no alternate publication method is used here
to bypass that restriction. This document does not claim a public 1.44.119 update.
