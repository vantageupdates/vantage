# Companion 1.44.143 — release verification

Published stable release: [Vantage Companion 1.44.143](https://github.com/vantageupdates/vantage/releases/tag/v1.44.143).

## Exact candidate

- Tested source and release tag target: `26ca22496efbe57fbdd0c8512756eefe797de4d9`.
- Asset: `Vantage.exe`, **76,122,339 bytes**.
- SHA-256: `7f3259c5e465572af10a5a5f4e385b3986301958dedaa0420d444e0bb1f8da5d`.
- Fresh portable build using `vantage.spec`; file/product version `1.44.143`.
- Portable self-test: exit 0, matching version marker, isolated profile.
- Extracted map window, canvas and marker bytecode matches the tested source;
  shared mobile DKP assets also match the source bytes.
- Anonymous GitHub verification confirmed stable Latest, exact tag target,
  API asset size/digest, independently downloaded bytes and final unchanged
  release/tag/asset checks.
- Companion refresh workflow `40073133543` and Pages deployment `40073145084`
  succeeded. All nine checked public Companion files matched the tested source,
  including the `1.44.143` service worker, after deployment propagation.

## Complete-suite evidence

The final clean run covered **2,670 collected cases in 228 modules**:
**2,668 passed, 2 platform-dependent skips, 0 failures, 0 errors**.
The frozen-source verifier checked 743 files, with no omitted or duplicated
test results. The two skips concern symlink creation availability and POSIX
directory permissions on Windows.

An earlier full run exposed a pre-existing test-isolation defect: a parentless
DKP test page remained visible after `deleteLater()` and intercepted synthetic
map mouse moves. A minimal two-test reproduction and event trace confirmed it;
closing only that leaked page made both unchanged tests pass. The fixture now
closes its windows and flushes deferred deletion. **The entire suite was then
rerun from a new frozen source manifest**, producing the clean results above;
the earlier failure was not hidden or replaced with a reconciled pass.

## Pointer behavior checked

- Cursor-only updates with no player object, game logs or MouseMove delivery.
- Inactive windows without focus stealing; keyboard L remains available.
- Mini at 100px, regular widths, 150% DPI, map previews and live-map return.
- Stationary-pointer pan/zoom updates, lifecycle stop/restart and popup hiding.
- Intact wrapped Mini coordinates, compact normal readout and no repeated text
  layout when the cursor and coordinates are unchanged.
- Previous player arrow and saved preferences preserved.

This is automated Qt and packaged-application verification, not a claim that
a live EverQuest session was exercised. Publication did not replace the user's
installed executable or close Vantage, EverQuest or WinEQ. VantageUI is unchanged.
