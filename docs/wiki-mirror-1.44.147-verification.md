# Companion 1.44.147 — release verification

Verified on 2026-10-27. Product commit:
`b9cfe31277b9162532cb5de29d23ce754599ee6d`.

Stable release:
https://github.com/vantageupdates/vantage/releases/tag/v1.44.147

## Test evidence

- Complete collection: 2,833 cases in 238 modules; final results are 2,831
  passing and two expected platform skips. No omissions or duplicate results.
- Initial complete-suite execution found three obsolete original-domain URL
  assertions in two test modules. Only those URL expectations changed; all
  application source remained byte-for-byte identical. Both complete affected
  modules were rerun (33 cases passing). Original logs/XML and the test-only
  correction proof were retained before consolidating the final results.
- The remaining serial Quick Bar/reset checks passed (8 cases).
- Expected skips: the POSIX private-mode check and Windows-unavailable
  symlink collision check in the independent UI installer tests.
- Frozen release inputs: 760 source/test/data files. The candidate was built
  after validation and checked against that source freeze.

Explicit live requests through Qt's native network manager loaded Boneshear
with DMG 9 / DLY 20 and its effect/drop, Chardok with 152 mobs / 68 unique items,
and Bravery acquisition information. Other bounded parser samples covered
Enchanter skills, an NPC profile and Druid Epic Quest. These are representative
checks, not a claim of complete or current coverage across the mirror.

## Portable candidate

- Clean PyInstaller build from `vantage.spec`: passed.
- Portable self-test in an isolated profile: exit 0, version 1.44.147.
- File and product versions: 1.44.147.
- Size: **76,198,248 bytes**.
- SHA-256:
  `847b8c384866b1b3dd93498236c572e625f77dba8127890669d1be21ff6f8eab`.
- Packaged bytecode matched 19 checked source modules, including both new
  mirror helpers and mobile adapters. Four phone assets and the source notice
  matched their packaged bytes.

Anonymous public verification confirmed the stable tag's exact product commit,
asset size, GitHub digest and downloaded executable hash against this candidate.

## Public mobile deployment

- Refresh Vantage Companion run **40490299761**: successful.
- Pages deployment run **40490338160**: successful.
- Nine public phone files matched the tested commit after deployment, including
  `app.js`, `offline.js`, `guild-dkp.js` and the versioned service worker.

Evidence directory on the release workstation:
`C:/Users/lmerc/OneDrive/Documents/SideKick/work/wiki-mirror-147`.
Key files: `verified/complete-suite-proof.json`,
`test-expectation-correction-proof.json`, `native-mirror-smoke.json`,
`release-chain-proof.json`, `candidate-proof.json`, `packaged-assets-proof.json`,
`public-proof.json` and `pages-proof.json`.

Publication did not replace the installed Companion, stop EverQuest, create a
new Wiki database service or modify the independent VantageUI skin/release.
