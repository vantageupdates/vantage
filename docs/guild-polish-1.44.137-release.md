# Vantage 1.44.137 release evidence

Published on 2026-10-18 at 00:31:52 UTC. Anonymous public verification completed
at 00:32:08 UTC with all three verification groups passing.

- Stable release: [v1.44.137](https://github.com/vantageupdates/vantage/releases/tag/v1.44.137)
- Tested source and exact tag target: `80ba6b44ffff81c81cf628beda208f4ea82e6fe8`
- Scope: [independent Market filters, personal DKP history, Heal Chain overlay, and polish](guild-polish-1.44.137.md).

## Executable

| Check | Result |
| --- | --- |
| Final candidate | `final4/dist-candidate/Vantage.exe` |
| File / product version | `1.44.137` / `1.44.137` |
| Portable build and self-test | Passed, exit 0 |
| Candidate and public asset size | 76,059,941 bytes |
| Candidate and downloaded public SHA-256 | `ac1aee6542ae84148a8b0de6342dcc2ef43f9530719370ab218348332717798a` |
| GitHub digest, initial and final | `sha256:ac1aee6542ae84148a8b0de6342dcc2ef43f9530719370ab218348332717798a` |
| Release / asset IDs | `416150693` / `652008360` |

The public executable was downloaded independently without authentication. Its
raw hash and size matched the tested candidate; the GitHub digest was checked
separately. Latest release, tag target, asset identity, and candidate hash were
rechecked at completion. The publication used the coordinated Companion channel;
no VantageUI assets or independent version were changed.

## Final complete suite

The final frozen run collected **2,497 cases in 219 modules**: **2,495 passed,
2 skipped, 0 failures, 0 errors**, with no omissions or duplicate executions.
All 731 frozen application, test, and harness files were verified before and
after the source commit. The three complete-module shards passed 707, 1,040,
and 748 tests respectively; the second shard also contained both skips.

The platform-specific skips were:

- `tests/test_ui_skin_windows_permissions.py::test_real_posix_stage_keeps_private_mode_after_publication`
- `tests/test_ui_skin_versioned.py::test_symlink_collision_never_changes_outside_target`

Earlier candidates were not published. Earlier full runs caught missing detail
help text, Heal Chain settings keyboard traversal, and a three-pixel Market
footer layout change after resize. The detail help and keyboard behavior were
corrected; the header fixture now accounts for the three added settings without
weakening its traversal assertions. Market status text now reserves two styled
lines while still expanding for longer messages. Its existing geometry test was
not weakened; additional deterministic wrapping and font/padding tests were added.
The entire suite and executable were rebuilt from the final frozen sources.

## Interaction and data checks

- Market: independent searches and equipment filters, scoped Clear actions,
  switching tabs without losing filters, sorting and selection, preserved shared
  server/watchlist/live-auction state, and stable footer geometry.
- Guild DKP: personal award provenance, attended ticks, alt identity, pool
  separation, unknown amounts, signed transactions, duplicates, stale-response
  rejection, retries, persistent selection, and verified item links.
- Heal Chain: shared tracker rails in an independent overlay, cast/interruption
  states, hide versus monitoring behavior, keyboard movement and settings order,
  saved position/opacity, screen bounds, and 100%/125%/150% DPI fixtures.
- Broader polish: readable diagnostics, rolling-day wording, and protection for
  unpushed Friends drafts during server changes, reload, restore, and close.

The Qt design review informed clearer grouping, readable layouts, and keyboard
access. The native inventory and interaction checks used disposable offscreen Qt
profiles; public OpenDKP schema checks were read-only and unauthenticated. These
checks do not assert physical in-game, hardware audio, or screen-reader coverage,
nor exact runtime parity with the original Chain Heal executable.

EverQuest, WinEQ, the installed Vantage executable, and VantageUI were not modified
or replaced. The user installs normally through the updater.

Detailed evidence is retained under `work/dkp-polish-137/final4`, including
`candidate-proof.json`, `verified/complete-suite-proof.json`, and
`public-proof.json`. This post-publication document does not modify the tagged
executable or frozen application sources.
