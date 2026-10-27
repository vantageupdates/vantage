# Companion 1.44.149 — release verification

Verified on 2026-10-27. Product commit:
`195d8811be9b2063bd48e5ae0142f9f95c9c3ba5`.

Stable release:
https://github.com/vantageupdates/vantage/releases/tag/v1.44.149

## Tests and native recovery

- Final complete collection: 2,893 cases in 243 modules; **2,891 passed**,
  two expected platform skips, no failures, omissions or duplicate results.
- Expected skips: Windows-unavailable symlink creation and POSIX private-mode
  verification in the independent UI installer tests.
- All 765 frozen source/test/data inputs matched the final candidate's build
  and complete-suite snapshot. Final hardening was followed by a fresh complete
  suite, clean build and self-test; the earlier candidate was not published.
- Focused coverage includes unread bytes despite stopped watcher/polls,
  concurrent append during a drain, partial records, same-size rewrites without
  stale context, touch without event replay, rotation, historical split-page
  lookup, active-character selection, snapshot ordering and shutdown.
- Native Windows verification used a full VantageApp, its production Tool
  window flags, 150% DPI, an isolated profile and synthetic logs. It deliberately
  skipped two map events. Five real two-second heartbeat checks recovered the
  maps, retained subsequent player coordinates and preserved a manual preview.
- The second native recovery disabled the synthetic reader's native file
  watch and both faster polls. The zone heartbeat independently consumed the
  new zone and location records, showing Nektulos Forest with game coordinates
  `300, 400, 3` (map coordinates `-400, -300, 3`).

## Portable and public release

- Clean single-file build using `vantage.spec`: passed.
- Portable self-test in an isolated profile: exit 0, version 1.44.149.
- File/product versions: 1.44.149.
- Size: **76,208,897 bytes**.
- SHA-256:
  `5bb9889f6b1d3bf47e6e53be6c42dd040b0d6a8caf841d4771057468f860a303`.
- Packaged bytecode matched twenty source modules, including the reader and
  map reconciliation. Four phone assets and the source notice matched bytes.
- Anonymous verification matched the stable release tag to the product commit,
  and matched public asset size, GitHub SHA-256 digest and downloaded executable
  hash against the tested candidate.

## Public phone assets

- Refresh Vantage Companion run **40505476692**: successful.
- Pages deployment run **40505503505**: successful.
- Nine public phone files matched the tested commit after deployment, including
  the versioned service worker.

Final release evidence is retained under
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/zone-heartbeat-149-final`:
`verified/complete-suite-proof.json`, `release-chain-proof.json`,
`candidate-proof.json`, `packaged-assets-proof.json`, `public-proof.json`,
`pages-proof.json`, and `native-zone-heartbeat.json` / `.png`.

Publication did not replace the installed Companion, stop EverQuest, or modify
the independent VantageUI skin/release. Native diagnostic processes exited.
