# Companion 1.44.139 release verification

Published stable release: [Vantage Companion 1.44.139](https://github.com/vantageupdates/vantage/releases/tag/v1.44.139).

Tested and tagged source commit: `a759a9077b77153a187393d330f08a00592ebcb7`.
Release published at 2026-10-23 01:32:46 UTC; public executable verified at
01:33:09 UTC. This documentation commit does not change the tested runtime or tag.

## Tests and frozen candidate

- Full suite: 2,568 exact collected cases across 221 modules; 2,566 passed,
  two platform-specific skips, zero failures, errors, omissions or duplicates.
- Skips: `test_real_posix_stage_keeps_private_mode_after_publication` and
  `test_symlink_collision_never_changes_outside_target` on Windows.
- The release gate verified 736 frozen source files before/after building and
  when binding the successful suite, self-test and candidate to the commit.
- Fresh single-file `vantage.spec` portable build; file/product version 1.44.139.
- Portable self-test exited 0 in an isolated profile and emitted version 1.44.139.
- Extracted `storage.js`, `dkp.js`, `guild-dkp.js` and `guild-dkp.css` from the
  candidate and verified exact byte equality with frozen sources.
- A second reviewer independently recomputed source, suite, candidate and
  packaged-asset checks. No remaining stop-ship finding.

Candidate and public `Vantage.exe`: **76,091,769 bytes**.

SHA-256: `971d3426fda7a596b9c23e42fe61c5d86fd1f967f972f67cced7e1523bd0367a`.

The stable latest release and tag resolve to the tested commit. GitHub's asset
size and SHA-256 digest match the tested candidate. An independent anonymous
download matches both. Latest/tag/asset identity was rechecked at completion.

## Functional evidence

Anonymous read-only source replay preserved all 18 Mindflux purchases through
items, raids, DKP transactions and adjustments. Canonical item titles, unique
purchase identities, selection, enabled item action and emitted item name all
passed. Actual guild records and browser screenshots are not committed.

The 122 focused tests include Python/JavaScript parity and bounded-work checks
for three 2,000-purchase scenarios. Independent matching replay covered 600 seeded
mixed cases. After indexed matching, a 2,000-purchase fixture completed in
0.1183s Python / 0.0518s JavaScript on the review machine; these are fixture
measurements, not a promise about network latency or every device.

The scoped [audit](dkp-history-1.44.139-audit.md) records selection, focus,
provenance, performance findings and verification limits. The rejected initial
all-pairs candidate and interrupted suite are not release evidence.

## Mobile publication

- [Refresh Vantage Companion](https://github.com/vantageupdates/vantage/actions/runs/39884535178): success at the tested source commit.
- [Pages deployment](https://github.com/vantageupdates/vantage/actions/runs/39884552323): success at generated Pages commit `be5d5c8c4a0dee3c8288670b370e90d2fba97878`.
- All eight public application files matched the tested commit, allowing only
  CRLF/end-newline normalization: `index.html`, `app.js`, `storage.js`, `dkp.js`,
  `guild-dkp.js`, `guild-dkp.css`, `sw.js`, `manifest.webmanifest`.
- Public service-worker cache version is 1.44.139. The first check, while Pages
  was still deploying, correctly rejected old content; only the complete
  post-deployment comparison is counted as verification.

## Preservation and use

No installed executable, running user application, game files, guild data or
VantageUI assets were changed. Existing local untracked output was preserved.

Install through Vantage's updater, then open **Guild DKP & More → My DKP History
→ Refresh history**. Choose **Loot** for purchases. Reopen the phone companion
online to receive the updated application files.
