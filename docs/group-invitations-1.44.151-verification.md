# Companion 1.44.151 — release verification

Verified on 2026-10-29. Product commit:
`b485b228800e6e474fdd730f1518edd831bd96dd`.

Stable release:
https://github.com/vantageupdates/vantage/releases/tag/v1.44.151

## Group invitation behavior

- Received and sent group invitations are built-in triggers under
  `Vantage · Basics`, using the existing Quickbar, overlay and audio routes.
- The installed client's `eqstr_us.txt` confirmed exact strings 12280 and 12273:
  `%1 invites you to join a group.` and
  `You invite %1 to join your group.`. Only these system lines are matched.
- The other player's name resolves in both the written and configurable spoken
  message. Quoted chat does not match. Repeated lines are guarded for one second.
- Sound, text to speech, audio Off and individual mute use the common controls.
  Individual mute retains the written notice; disabling the trigger stops it.
- Catalog version 6 adds missing names without overwriting customized, disabled
  or muted same-name triggers. No separate notification engine was introduced.

## Tests

- Focused final run: **13 passed in 14.08 seconds**, including six new group
  invitation cases and existing migration/control tests.
- A full offscreen VantageApp replay verified both resolved Quickbar messages,
  one notice per matching event, repeat suppression, disabled state, muted
  visual delivery and absence of running countdown timers.
- Final complete collection: **2,934 cases in 246 modules; 2,932 passed**, two
  expected platform skips, no failures, errors, omissions or duplicate results.
- Expected skips concern Windows symlink availability and POSIX private-mode
  verification in the independent UI installer tests.
- All **769 frozen source/test/data inputs** matched the complete-suite and
  clean candidate build snapshots. No source edits followed the freeze.

## Portable and public release

- Clean single-file `vantage.spec` build: passed.
- Portable self-test with a fresh isolated profile: exit 0, version 1.44.151.
- File/product versions: 1.44.151.
- Size: **76,218,546 bytes**.
- SHA-256:
  `a0a6537f270c92554c6e29791e6d4fc4ab76a3b1f79a95eee030c99f21cad8ce`.
- Packaged bytecode matched 21 source modules, including the changed config and
  shared trigger runtime. Four phone assets and the source notice matched bytes.
- Anonymous verification matched the stable tag to the product commit and
  matched public asset size, GitHub SHA-256 digest and downloaded executable
  hash against the exact tested candidate.

## Public phone assets

- Refresh Vantage Companion run **40967446049**: successful.
- Pages deployment run **40967469468**: successful.
- Nine public phone files matched the tested commit after deployment, including
  the versioned service worker.

Evidence is retained under
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/group-invite-151`:
`group-invite-focused.xml`, `client-message-proof.json`,
`verified/complete-suite-proof.json`, `release-chain-proof.json`,
`candidate-proof.json`, `packaged-assets-proof.json`, `public-proof.json`,
and `pages-proof.json`.

No live game or desktop interaction was used. The installed Companion, character
INIs and independent VantageUI skin, updater and release were preserved.
