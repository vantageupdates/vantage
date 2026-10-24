# Companion 1.44.141 release evidence

Verified October 24, 2026. See [behavior and limitations](map-fixes-1.44.141.md).

## Published candidate

- [Stable release](https://github.com/vantageupdates/vantage/releases/tag/v1.44.141), confirmed Latest.
- Tested source and tag: `44856d2e469a3a58bfa5be454e85f7caa1278f6b`.
- Portable `Vantage.exe`: **76,117,471 bytes**; file/product version **1.44.141**.
- SHA-256: `067820d767e51e51110bc2979d87dd7e63b8f7defc34f59e27bdb560ff20358a`.
- GitHub asset digest, API size and an independently downloaded anonymous copy
  match the tested candidate. Latest, the tag target and asset were rechecked.
- [Companion refresh](https://github.com/vantageupdates/vantage/actions/runs/40068417349)
  and [Pages deployment](https://github.com/vantageupdates/vantage/actions/runs/40068428348)
  succeeded. Nine public Companion assets match tagged source, including the
  1.44.141 service worker. Verification was completed after deployment finished.

## Tests and build

- Complete collection: **2,654 cases across 226 modules**; **2,652 passed**, two
  platform-conditional skips, zero failures/errors/omissions/duplicates.
- Skips: POSIX mode-bit semantics on Windows; unavailable Windows symlink privilege.
- Reset-layout coverage ran separately after the three parallel suites and
  passed in 32.97 seconds. No timeout or assertion was relaxed.
- Frozen-source checks cover **741 files** before/after the fresh portable build
  and against committed source. All test harness files required by this gate
  are tracked. An earlier partial run was retained and superseded by this
  complete run after the final typed-configuration comparison change.
- Fresh `vantage.spec` build succeeded. The candidate portable self-test exited
  0 with the expected version marker in a disposable profile.
- All four shared phone DKP assets in the executable match source bytes.

## Preservation and map coverage

- Separate-process save/shutdown/restart tests preserve 17 window geometries
  and opacities, reduced-size presets, map zoom/zone, overlays, sounds, extension
  preferences, buffs and Smart Timers. Buff deadlines retain the existing
  whole-second rounding allowance; timer deadlines match exactly.
- Full configuration checkpoint checks reject missing/changed values, including
  changes in value type. Failed update handoff resumes live spell tracking.
- Focused map regressions cover hover without held buttons, immediate toggles,
  viewport-edge placement, keyboard L, saved zoom, character/server switching,
  camp events and unknown/same-zone transitions.
- Geometry regressions cover recorded Nektulos positions, compact arrow bounds
  at five zoom levels, stationary/jump/stale-sample travel headings, Skyshrine
  maze geometry, boundary tolerance and a known ground location.
- Native Qt review kept coordinate text compact with an opaque dark card and
  non-intercepting pointer behavior; keyboard access and an accessible description
  supplement hover. This is a scoped review, not a full accessibility certification.

## User state and limits

The installed `D:/Vantage.exe` still has its original 1.44.140 SHA-256,
`f9ffb5de294b3f9a87c02f72a0a30100aa2fffab65c5b7e334eb1bcf6ea705f2`.
No installed application, real profile, EverQuest INI or VantageUI skin was
replaced by this work. Update through Companion; no layout reset is required.

The arrow indicates travel between reported locations, not character facing.
A fixed-screen-size marker can overlap a narrow corridor without its underlying
coordinate being wrong. Upper Skyshrine maze behavior still needs in-game
confirmation; no verified live upper-maze location was available.

Machine-readable proofs, suite logs and the candidate are retained locally in
`SideKick/work/map-fixes-141/final`.
