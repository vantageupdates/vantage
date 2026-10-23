# Companion 1.44.140 release evidence

Verified 2026-10-23 UTC. This release fixes personal Recent Loot disappearing
after the character response and removes the 500-record guild-loot fetch limit.
See [behavior and use](guild-loot-1.44.140.md).

## Publication

- [Stable release](https://github.com/vantageupdates/vantage/releases/tag/v1.44.140), confirmed Latest.
- Tested source and tag: `33f7526f3129a4ef25987e7c810ad7a4bd34f987`.
- Portable `Vantage.exe`: **76,111,372 bytes**; file/product version **1.44.140**.
- SHA-256: `f9ffb5de294b3f9a87c02f72a0a30100aa2fffab65c5b7e334eb1bcf6ea705f2`.
- GitHub asset digest, API size and independently downloaded anonymous public
  bytes match the tested candidate. Tag and Latest were rechecked at the end.
- [Companion publishing workflow](https://github.com/vantageupdates/vantage/actions/runs/39892401494)
  and [Pages deployment](https://github.com/vantageupdates/vantage/actions/runs/39892417024)
  both succeeded. All nine checked public Companion files match the tagged
  source, including `app.js`, `offline.js` and the 1.44.140 service worker.
- The installed local executable, EverQuest, WinEQ and VantageUI were not replaced
  or modified. Install this release through Vantage's updater, then refresh Guild.

## Release gate

- Complete collection: **2,613 cases in 223 modules**; **2,611 passed**, two
  platform-conditional skips, no failures/errors/omissions/duplicates.
- Skips: Windows symlink privilege unavailable; POSIX mode-bit test on Windows.
- Frozen-source gate verified **738 files** before/after the fresh portable
  build and against the committed source. No test harness remained unpublished.
- Candidate `--portable-self-test` exited 0 with the expected version marker.
- All four shared phone DKP assets inside the executable match source bytes.
- An outdated spreadsheet-test client stub was updated with the newly required
  loot-progress signal; its assertions were unchanged. The full suite was then
  rerun against the final freeze.
- An isolated reset-layout test exceeded its existing 45-second deadline during
  concurrent build/test work. That failed evidence was retained. After other
  runners finished, the same unmodified test passed in **42.03 seconds**.

## Real data and responsiveness

An anonymous, read-only Castle request loaded **30,362 purchases across 61
pages**; the desktop model exposed all **30,362 rows**. All **18** returned
personal purchases remained visible through guild loading, personal response
completion and a repeated overview refresh. No guild records were edited.

The final product-source probe downloaded the history in 14.167 seconds and
prepared its model in 1.394 seconds across event-loop batches. Initial synchronous
setup was 72 ms; the largest measured event-pump gap was 141 ms while other test
and build work ran. These are observations, not universal timing guarantees.
Repeated mobile snapshots reuse the prepared projection instead of rebuilding
30,000 records each second.

## Scoped accessibility and interaction review

### Closed finding: purchase selection identity

- **Criterion:** Stable purchase identity and predictable keyboard selection.
- **Severity:** major; closed.
- **Specialist:** keyboard navigation and focus review.
- **Location:** `src/vantage/parsers/opendkp.py`, `_same_loot_purchase` and Recent Loot selection restoration.
- **Description:** Refresh could transfer selection to another owner or pool when fingerprints matched or transaction IDs were reused.
- **Impact:** Keyboard or assistive-technology activation could open a different purchase than the one previously selected.
- **Remediation:** Reject explicit owner/pool conflicts before ID/fingerprint matching, including string-valued and nested pools. Independently replayed no-ID and reused-ID conflicts; correctly scoped ownerless records can still be enriched.

### Closed finding: snapshot completeness

- **Criterion:** Truthful completion state and persistent dynamic status.
- **Severity:** major; closed.
- **Specialist:** async data correctness and live-region review.
- **Location:** `src/vantage/parsers/opendkp.py` snapshot preparation; `src/vantage/helpers/mobile_offline.py` guild projection; `companion-web/app.js` Guild status.
- **Description:** First-load preparation could expose an empty snapshot that incorrectly claimed a complete history.
- **Impact:** Users, including those relying on spoken status, could mistake an unfinished export for authoritative history.
- **Remediation:** Bind completeness to published prepared rows, preserve previous complete caches through refresh/failure, and disclose unfinished initial exports. Reuse the existing debounced polite status without changing focus. Independently verified producer-to-exporter-to-phone-validator behavior.

Arrow navigation, Enter activation, Tab/Shift+Tab exit, visible focus, and
same-character refresh without focus theft were verified. Existing dark/gold
styling is reused. No new HTML roles, modal behavior or heading structures were
introduced. Native screen-reader and physical iPhone testing were not performed;
this is a scoped review, not a full WCAG-conformance claim.

## Explicit limits

The installed PWA searches the entire imported guild-loot array and reveals
another 100 entries per Show more action. The LAN view keeps its existing
250-row initial preview while searches cover all supplied rows. Neither is a
500-row source-data cutoff. Offline files retain the explicit **8 MiB** budget
and report incomplete/truncated copies. The standalone phone client's existing
40-page personal-history safety limit is separate from guild-wide Loot.

Final machine-readable proofs, logs and candidate are retained locally under
`SideKick/work/guild-loot-140/final2`; the read-only public data probe is under
`final`. Their frozen product files match; only the spreadsheet test stub
changed between those two freezes.
