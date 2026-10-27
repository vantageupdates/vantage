# Companion 1.44.150 — release verification

Verified on 2026-10-27. Product commit:
`9406539d4f47dff31e3d6a537a88cdeda6c1d081`.

Stable release:
https://github.com/vantageupdates/vantage/releases/tag/v1.44.150

## Diagnosis and scope

The user confirmed that repeating `/who` made the map react. Observed Holyflux
system records lacked some zone transitions that were present in the same
installation's `Logs/dbg.txt`. The Loc social also contained `/log`, which toggles
logging. No game commands, character INIs or social buttons were changed.

The two-second map heartbeat now accepts confirmed client zone context from
that selected directory, subject to character/server matching, timestamp
priority and pending normal-log reads. This supplies map context only; live
buffs, auctions and other parsers still require normal EverQuest logging.

## Tests and isolated replay

- Final complete collection: **2,928 cases in 245 modules; 2,926 passed**, two
  expected platform skips, no failures, errors, omissions or duplicate results.
- Expected skips: Windows-unavailable symlink creation and POSIX private-mode
  verification in the independent UI installer tests.
- Focused reader, map and monitor coverage: 97 passed. New coverage includes
  readiness, partial/aligned tails, file replacement, duplicate confirmations,
  ambiguous servers, stale normal/client records, sharing violations, pending
  bytes before character changes and disappearing active files.
- All **768 frozen source/test/data inputs** matched the complete-suite and
  clean candidate build snapshots. No source edits followed the freeze.
- An offscreen full VantageApp replay changed East Freeport to North Ro without
  repeated `/who` commands or replay through `new_line`. Repeated checks retained
  state, and input hashes were unchanged.
- That replay combined filtered original Holyflux system records with an
  explicitly labeled transcription of previously observed DBG records. The
  original DBG session had been overwritten. This is an isolated replay, not
  a claim of live game validation or desktop interaction.

## Portable and public release

- Clean single-file `vantage.spec` build: passed.
- Portable self-test with a fresh isolated profile: exit 0, version 1.44.150.
- File/product versions: 1.44.150.
- Size: **76,217,031 bytes**.
- SHA-256:
  `e600e4231ce127a7b4562c4a769d0a44a950880ef95c03b49e5914616c6651e0`.
- Packaged bytecode matched 21 source modules, including `client_zone`, the
  reader, map reconciliation and log monitor. Four phone assets and the source
  notice matched bytes.
- Anonymous verification matched the stable tag to the product commit and
  matched public asset size, GitHub SHA-256 digest and downloaded executable
  hash against the exact tested candidate.

## Public phone assets

- Refresh Vantage Companion run **40592405732**: successful.
- Pages deployment run **40592428969**: successful.
- Nine public phone files matched the tested commit after deployment, including
  the versioned service worker.

Evidence is retained under
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/client-zone-150`:
`verified/complete-suite-proof.json`, `release-chain-proof.json`,
`candidate-proof.json`, `packaged-assets-proof.json`, `public-proof.json`,
`pages-proof.json`, and `real-zone-probe-final.json` / `.py`.

Publication preserved the user's running applications and installed executable.
The independent VantageUI skin, updater and release were not modified.
