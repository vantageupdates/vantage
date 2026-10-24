# Companion 1.44.142 release evidence

Verified October 24, 2026. See [behavior and verification limits](map-hover-1.44.142.md).

## Published candidate

- [Stable release](https://github.com/vantageupdates/vantage/releases/tag/v1.44.142), confirmed Latest.
- Tested source and tag: `86362821819b062a56c64f6ea0a7e587d7316080`.
- Portable `Vantage.exe`: **76,118,260 bytes**, file/product version **1.44.142**.
- SHA-256: `a407b5ae548453f6a3384220828f4d8c54bd997cee0e97b367ef80772651fe9d`.
- GitHub's asset digest and API size match the tested candidate. An anonymous
  public download independently matches its bytes and SHA-256. Latest, tag
  target and asset identity were checked again at the end.
- [Companion refresh](https://github.com/vantageupdates/vantage/actions/runs/40070498418)
  and [Pages deployment](https://github.com/vantageupdates/vantage/actions/runs/40070511248)
  succeeded. Nine public Companion assets match the tested source, including
  the 1.44.142 service worker, checked after deployment completed.

## Tests and build

- Complete collection: **2,660 cases across 227 modules**. Final reconciled
  result: **2,658 passed**, two platform-conditional skips, no unresolved
  failures/errors, missing cases or duplicate final results.
- The original three parallel shards had one Quick Bar subprocess timeout at
  its existing 30-second limit. The exact unchanged case passed independently
  in 20.33 seconds overall (19.993-second recorded case), then its complete
  seven-test module passed in 33.42 seconds (19.431 seconds for that case).
  No assertions, timeout, production code or frozen source changed for reruns.
- Raw failed and passing XML reports are retained. The separate reconciliation
  verifier requires the exact original failure, entire affected module, isolated
  passing case, exact collection and unchanged source; it records hashes of
  every original/rerun report and explicitly retains the initial failure in the
  machine-readable proof. Independent read-only review found no blocking issue.
- The two skips concern POSIX mode-bit semantics on Windows and unavailable
  Windows symlink privilege. Reset-layout coverage ran separately after other
  suites finished and passed in 43.31 seconds.
- The focused map/window suite passed **48 tests**. New tests use the physical
  outer panel viewport rather than bypassing it with direct inner-map events.
- **742 source files** were frozen and verified before/after the clean
  `vantage.spec` build and against the committed source. The portable self-test
  exited 0 in a fresh profile with the expected version marker. All four bundled
  shared phone DKP assets match source bytes.

## Map verification and preservation

- Reproduced the stale inner-map width on a width-only expansion before fixing
  it. Tests cover expansion/contraction, compact sizes, live/preview maps,
  physical header activation, lost inner move delivery, pointer leave/header
  behavior and keyboard selection in the real embedded context menu.
- Restored the pre-1.44.141 arrow shape/size, icon and label. Existing location,
  travel-heading, Skyshrine and settings-preservation regressions still pass.
- Rendered and inspected isolated 400- and 800-pixel map windows with the
  bundled fonts; pointer coordinates remain readable and inside the viewport.
- Native Qt review retained existing styling and keyboard access, and made
  the LOC toggle explicit in the context menu and On/Off header tooltip.

The general hover issue was not reproduced in every Windows/game condition;
the proven width fix and defensive outer-event bridge are documented separately.
Live in-game confirmation remains useful. No game input or memory access was used.

The installed `D:/Vantage.exe` remains 1.44.141 with SHA-256
`067820d767e51e51110bc2979d87dd7e63b8f7defc34f59e27bdb560ff20358a`.
No installed executable, real user profile, EverQuest INI or VantageUI skin was
modified. Install through Companion's updater; no reset is required. Existing
hover-Off and click-through preferences are preserved.

Machine-readable proofs, original/retried reports, candidate and rendered
checks are retained locally in `SideKick/work/map-hover-142/final`.
