# Vantage 1.44.135 release evidence

Published on 2026-10-15. Anonymous public verification completed successfully
at 08:26:41 UTC, with every required verification group passing.

- Stable release: [v1.44.135](https://github.com/vantageupdates/vantage/releases/tag/v1.44.135)
- Tested source and exact release-tag target:
  `37b8f8a5f0f0704ebac3e54723843e8fa7c1c8b6`
- Permanent [phone companion](https://vantageupdates.github.io/vantage/companion/)
- [Companion publication workflow 38705570941](https://github.com/vantageupdates/vantage/actions/runs/38705570941): successful.
- Published Pages commit: `bcc13da4373140e304428327bcf9d045a8d27467`.

## Tested executable

| Check | Result |
| --- | --- |
| Final candidate | `final2/dist-candidate/Vantage.exe` |
| File version / product version | `1.44.135` / `1.44.135` |
| Packaged application self-test | Passed |
| Candidate and public asset size | 76,012,585 bytes |
| Candidate and anonymously downloaded public SHA256 | `92eccf9bee7558f3cdf05ac661097c75a42cf83539c10677b8dafe6b265ca35e` |
| GitHub asset digest, initial and final checks | `sha256:92eccf9bee7558f3cdf05ac661097c75a42cf83539c10677b8dafe6b265ca35e` |
| Release / executable asset IDs | `413573373` / `643212727` |

The public executable was downloaded separately from the candidate. Its size
and raw SHA256 matched the tested binary; GitHub's reported digest was also
checked independently. Latest-release, tag, asset, and candidate identity were
rechecked before marking the public proof complete.

## Tests and source freeze

The final complete-suite gate collected 2,413 cases across 210 modules:
**2,411 passed, 2 skipped, 0 failures, and 0 errors**, with no omissions or
duplicate executions. It verified all 720 frozen source files.

The two skipped cases were:

- `tests/test_ui_skin_versioned.py::test_symlink_collision_never_changes_outside_target`
- `tests/test_ui_skin_windows_permissions.py::test_real_posix_stage_keeps_private_mode_after_publication`

The near-8-MiB backup fix passed seven focused tests before the final full-suite
run and rebuild. Phone backups now retain compact JSON, avoiding formatting
overhead that could make a valid imported copy too large to import again.

## Public phone app

All 11 public URL byte/hash checks matched the exact tested-commit Git blobs:
the companion root and `index.html`, `app.js`, `storage.js`, `offline.js`,
`app.css`, `manifest.webmanifest`, `sw.js`, `share.html`, `icon-256.png`, and
`icon-1254.png`. These comparisons used committed bytes, not Windows working-tree
line endings. The public service worker declared
`vantage-companion-shell-v1.44.135`.

| Public catalog | Verified records |
| --- | ---: |
| Market items | 12,121 |
| Spells | 1,151 |
| Zone names | 122 |
| Quest names | 906 |

Catalog counts agreed with the published metadata, and all four publication
timestamps agreed. These are the counts observed during release verification;
the network-sourced Market catalog can change during later refreshes. Zone and
quest indexes contain names and Wiki links, not complete offline Wiki articles.

## Deployed Chrome cold-restart check

The permanent public URL was tested in desktop Chrome with a synthetic guild
fixture. An existing cached v2 shell appeared on the first navigation; after
the v1.44.135 service worker activated, reopening/reloading displayed the new
six-tab interface.

After explicit fixture-import confirmation, the browser was fully closed.
Its persistent profile was reopened at `about:blank`, and networking was
disabled **before** navigating to the permanent public URL. The app recovered
the synthetic Aster record with 125.0 DKP and reported
`Ready offline: PC copy, Market, Spells, Zones, Quests.` Clarity remained
searchable among 1,151 saved spells. The public 390 px viewport check showed
no horizontal overflow. These results concern desktop Chrome, not a physical
iPhone installation.

## Evidence and limits

Detailed release-machine evidence is retained in the
`work/mobile-offline-135/final2` bundle:

- `public-proof.json`: complete public release, executable, web, and catalog proof.
- `verified/complete-suite-proof.json`: complete-suite and 720-file freeze proof.
- `public-download/`: independently downloaded public verification artifacts.

Physical iPhone installation was not performed. Desktop Chrome/WebKit checks
are not a claim of device-specific iOS installation or storage behavior.
Safari and an installed Home Screen app can keep separate saved copies; the
private-file import fallback remains necessary. See the
[installation and limitations guide](mobile-offline-1.44.135.md) and
[scoped accessibility audit](mobile-offline-1.44.135-audit.md).

This post-publication evidence document was added after the tested source
freeze; it does not alter the tagged executable or frozen application sources.
