# Companion 1.44.148 — release verification

Verified on 2026-10-27. Product commit:
`b75d864d647bebaa6a66d74473fe07e74b4e3e46`.

Stable release:
https://github.com/vantageupdates/vantage/releases/tag/v1.44.148

## Tests and native checks

- Complete collection: 2,861 cases in 241 modules; **2,859 passed**, two
  expected platform skips, no failures, omissions or duplicate results.
- Expected skips: POSIX private-mode verification and the unavailable Windows
  symlink collision check in the independent UI installer tests.
- All 763 frozen source/test/data inputs remained unchanged throughout the
  suite and portable build. The tested candidate is bound to the product commit.
- Pointer migration tests cover legacy Off becoming On, the checked context
  menu and active coordinate sampler, then a deliberate Off surviving restart.
- Native production-window and full-application probes painted pointer LOC
  while moving, in Mini mode and through log-driven zone changes. The user
  confirmed the actual missing label was caused by an unchecked setting.
- Native Qt requests loaded Chardok, Temple of Veeshan, Nektulos Forest and
  South Qeynos. Selection tests cover restored zones, title aliases and stale
  retries without requiring Reload.
- Native Rewards rendering showed all eighteen Bone Chips (Kaladim) item
  names, readable and unclipped at 150% Windows scaling. Tests also cover
  mixed item/XP/faction paragraphs, infoboxes and cached reward records.

These samples validate the changed paths, not completeness or freshness of
every article in the third-party P99 mirror.

## Portable and public release

- Clean single-file build using `vantage.spec`: passed.
- Isolated portable self-test: exit 0, version 1.44.148.
- File and product versions: 1.44.148.
- Size: **76,203,876 bytes**.
- SHA-256:
  `dfcb4762ad5e9cb64a0fce44deccaeb22676f6a3a387952ffd7663373a09dfe3`.
- Packaged bytecode matched twenty source modules, including config, maps,
  Zones, Quests and mirror helpers. Four phone assets and the source notice
  matched their packaged bytes.
- Anonymous verification matched the public stable tag to the product commit,
  and matched the asset size, GitHub SHA-256 digest and downloaded executable
  to the tested candidate.

## Public phone assets

- Refresh Vantage Companion run **40496669589**: successful.
- Pages deployment run **40496697829**: successful.
- Nine public phone files matched the tested commit after deployment, including
  the versioned service worker.

Evidence is retained under
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/map-zones-148`:
`verified/complete-suite-proof.json`, `release-chain-proof.json`,
`candidate-proof.json`, `packaged-assets-proof.json`, `public-proof.json`,
`pages-proof.json`, and `rewards-native.png` / `rewards-native.json`.
Map diagnostic captures and histories are retained in the neighboring
`map-loc-148` folder; native zone-load evidence is in
`output/zone-rewards-native-148.json` in the development checkout.

Publication did not replace the installed Companion, stop EverQuest, or
modify the independent VantageUI skin/release.
