# Vantage 1.44.138 release evidence

Published October 18, 2026 at 04:37:18 UTC. Anonymous public executable
verification completed at 04:37:40 UTC; public phone assets matched at 04:37:50 UTC.

- Stable release: [v1.44.138](https://github.com/vantageupdates/vantage/releases/tag/v1.44.138).
- Exact tested source/tag: `7db0e7a8b3752950f8b1e1eb6bf757d067425beb`.
- [Permanent phone Guild panel](https://vantageupdates.github.io/vantage/companion/#guild).
- [Companion publication workflow](https://github.com/vantageupdates/vantage/actions/runs/39097704614): success at the tested commit.
- [Pages deployment](https://github.com/vantageupdates/vantage/actions/runs/39097715598): success; Pages commit `e7f46739acfdf673f58dbc738a3f8d712d94f998`.

## Executable verification

| Check | Result |
| --- | --- |
| Candidate | `final3/dist-candidate/Vantage.exe` |
| File/product versions | `1.44.138` / `1.44.138` |
| Portable build and isolated self-test | Passed, exit 0 |
| Candidate/public asset size | 76,079,985 bytes |
| Candidate/public SHA-256 | `570c597f2dac708c8efa6dfc6bc0df232dc1d814797c3b9a7906e0c5685bf976` |
| GitHub initial/final digest | `sha256:570c597f2dac708c8efa6dfc6bc0df232dc1d814797c3b9a7906e0c5685bf976` |
| Release/asset IDs | `416233750` / `652483550` |

An independent anonymous download matched the candidate's raw bytes and size.
Latest stable release, exact tag target, asset identity/digest and candidate
hash were rechecked. The four packaged shared assets matched the frozen source
bytes. No installed executable, EverQuest process, game file or VantageUI skin
was replaced or modified.

## Complete coverage, including an isolated fixture rerun

Final coverage: **2,523 cases across 221 modules: 2,521 passed, 2 skipped,
zero unresolved failures/errors, no omissions or duplicate final coverage**.
This is a complete initial run with a whole-module hermetic rerun, not a claim
that the initial all-in-one run was green.

The original final3 run retained one 45-second timeout in
`test_reset_ui_layout_is_confirmed_presentation_only_and_transactional`.
Its other 2,520 cases passed, with two platform-specific skips. An isolated
unmodified retry also timed out. Diagnostics observed expensive Qt stylesheet
work while a fresh test profile automatically indexed the installed EQ logs.
The earlier final2 run had passed this same test in 37.213 seconds.

Only that presentation test's fixture was changed: both EQ/log paths now point
to a disposable empty `EverQuest/Logs` directory. All original assertions and
the 45-second timeout were retained; no product/runtime source changed. The
whole module passed in 44.05 seconds, an independent serial run in 43.16 seconds,
and the recorded final4 verification run in 43.09 seconds. The independent
review confirmed the resolved paths and an empty search cache (zero files and
entries). The residual timing margin remains narrow; this is test isolation,
not a claimed application performance fix or proof that indexing explained all
timing variation.

The final4 verifier checks all 736 frozen source files, permits exactly that
one test-file delta from final3, verifies unchanged runtime bytes and candidate
hash, preserves the original failure, and combines passing unchanged-module
results with the complete changed-module rerun. The candidate did not require
a rebuild for this test-only setup change.

The platform-specific skips were:

- `tests/test_ui_skin_windows_permissions.py::test_real_posix_stage_keeps_private_mode_after_publication`
- `tests/test_ui_skin_versioned.py::test_symlink_collision_never_changes_outside_target`

## Mobile and deployment checks

- 66 focused tests passed for desktop/mobile OpenDKP parity, cache lifecycle,
  cancellation, partial/restricted data, accessibility interactions and asset
  integration. Four late regressions cover clearing saved data during partial
  or failed roster refreshes and delayed selection restore without a broadcast.
- Chrome and WebKit passed synthetic 1,201-character/67-record searches,
  pagination, delayed-detail focus, 320/390/768px layouts and native keyboard
  details. Both engines were closed and reopened offline with saved profiles;
  cached balance/history remained available with a stale-data notice. The
  cached script was checked to include the final revision-inheritance fix.
- Eight public assets matched tested-commit content, normalizing only line
  endings and final line breaks: index, app, storage, DKP adapter, shared panel,
  shared CSS, service worker and manifest.
- A previously cached public version137 session served the old screen on its
  first reload. After the new worker activated, the next reload displayed
  Guild DKP with only `vantage-companion-shell-v1.44.138` active.
- The deployed public WebKit session loaded Castle's 1,736-character roster,
  selected Mindflux, and displayed the authoritative current balance and saved
  raid history at390px without horizontal overflow. The local QR panel was
  also tested against the public API without changing PC selections.
- Read-only guild checks used no OpenDKP credentials; real guild records and
  screenshots were not committed. Restricted guilds remain subject to their
  OpenDKP access rules. Public browsing needs internet but no live PC.

See the [guide](mobile-dkp-1.44.138.md) and [scoped audit](mobile-dkp-1.44.138-audit.md)
for cache limits, the existing shared-header enlarged-text issue and browser
warnings. Desktop engines do not certify physical iPhone Home Screen behavior
or screen-reader operation.

Detailed evidence is retained under `work/mobile-dkp-138/final3` (original
complete run, binary and public proofs) and `final4` (source freeze, hermetic
module rerun and transparent complete-coverage proof). Earlier candidates were
not published. This evidence-only document does not alter tagged runtime bytes.
