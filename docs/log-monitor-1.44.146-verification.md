# Companion 1.44.146 — verified release

Published and verified on 2026-10-27.

- Stable release: [v1.44.146](https://github.com/vantageupdates/vantage/releases/tag/v1.44.146).
- Tested product commit: `5f8b0d2c56de5dfd78dacc502201c157d8bfcc94`.
- Public asset: `Vantage.exe`, **76,152,442 bytes**.
- Candidate, GitHub digest and independently downloaded public asset SHA-256:
  `c4c8a97cb2f5ec221a4f8d69a5d3a3a6f12a2dd91c39ef1ba61906a9c428c84c`.

## Complete test and build evidence

The frozen suite collected **2,795 cases across 235 modules**. All cases were
accounted for exactly once: **2,793 passed, 2 skipped, zero failures or errors**.
The two skips require POSIX permissions or Windows symbolic-link privileges.
The gate verified 753 frozen files before testing, before and after building,
and against the product commit.

The clean single-file portable build completed successfully. Its isolated
`--portable-self-test` exited zero and reported version 1.44.146. Packaged
bytecode was compared with source for 15 modules, including the reader,
application dispatch, health diagnostics, Log Profiles and Wiki access helper.
Four packaged phone assets also matched their source files exactly.

Focused coverage includes ordered once-only delivery of 4,480 events through
nested Qt loops, rotations and lost watches; independent consumer failures;
watchdog recovery; quiet/stopped state distinction; private-text exclusion;
native Qt response headers; and real file-watcher delivery to the application
with Bravery surviving a map-consumer exception and map processing recovering
on the next healthy event.

The new health panel was rendered in a disposable native Qt fixture at both
736×288 and 920×360. Status text and controls fit without clipping.

## Public verification

Anonymous release API and executable requests confirmed the stable latest
release, exact tested tag target, asset size and SHA-256 digest. The downloaded
executable matched the tested candidate.

The Refresh Vantage Companion workflow
[`40484670009`](https://github.com/vantageupdates/vantage/actions/runs/40484670009)
and Pages deployment
[`40484696313`](https://github.com/vantageupdates/vantage/actions/runs/40484696313)
both succeeded. Nine deployed phone-app files were compared with the tested
source, including the versioned service worker.

## Practical limits

These are verified fixes for reproduced reader and dispatch failures. The
installed session's exact intermittent failure was not conclusively reproduced;
current Holyflux chat activity was present during read-only investigation.
The new status and bounded diagnostics provide evidence if it recurs after
updating. This verification did not replace the user's installed executable,
close EverQuest or Vantage, edit user profiles, or modify the independent
VantageUI release.

Detailed local evidence is retained under
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/log-monitor-146`, including the
frozen plan, four test reports, build log, candidate/self-test proofs, packaged
code proof, release-chain proof and public/Pages verification results.
