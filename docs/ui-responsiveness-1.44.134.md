# Companion 1.44.134: periodic UI responsiveness

## Report and scope

The reported symptom was a handful of dropped frames roughly once per second
in Vantage's own windows, not EverQuest. The reported PC has a Ryzen 7950X,
64 GB RAM and an RTX 4090. Diagnosis and synthetic verification were performed
on the connected Ryzen 7 7840HS Windows PC, using Qt/PySide 6.11.2. These
measurements do not replace a real-world check on the reported machine.

## Changes

- Combat continues tracking, expiring/archiving fights and updating live
  overlays while hidden, rolled up or minimized, without rebuilding tables.
  Visible refreshes update only the selected view; unchanged rows reuse their
  existing cells. Opening, expanding and switching views refresh immediately.
- Session aggregation and selected archived encounters are cached until their
  inputs change. Copy and full-report exports explicitly materialize the data
  they require. Fight operations resolve stable archive IDs, not stale rows.
- Vitals skips capture and OCR when no enabled, calibrated monitor needs them.
  Active monitors use a single background capture/OCR job and a bounded result
  mailbox. GUI updates and alerts remain on the GUI thread. Edited, delayed and
  cancelled samples cannot deliver stale alerts; hidden monitors still work.
  A native capture that stalls is reported as no reading and cannot accumulate
  more jobs or block shutdown. Explicit calibration remains a user-driven path.
- Spell bars, Quick Bar server ticks and timer phase labels repolish only when
  their visual state changes. Notification overlays avoid reapplying identical
  stylesheets. Text, countdowns, warning states and active pulses still update.
- Restarting a map spawn countdown reuses its owned single-shot timer rather
  than adding another recurring anonymous callback chain.

## Reproducible workload and results

An isolated offscreen app with a synthetic current fight (26 actors, 5,000
damage events) was sampled over 5.2-second runs. A precise 16 ms heartbeat ran
beside the production 1,000 ms combat refresh timer. There was no live game
capture, real profile, network request, native audio or device sync in the fixture.

| State | 1.44.133 median refresh | 1.44.134 median refresh | 1.44.134 largest heartbeat gap |
| --- | ---: | ---: | ---: |
| Hidden, unchanged fight | 151.98 ms | 0.10 ms | 26.55 ms |
| Visible Overview, unchanged fight | 168.10 ms | 0.19 ms | 22.74 ms |
| Visible Overview, 26 additional events/second | Not measured | 1.19 ms | 19.71 ms |

The original unchanged-fight trials had five heartbeat gaps over 50 ms each;
the optimized trials had none. Offscreen Qt excludes desktop compositor and
GPU presentation costs. New-event refresh timings exclude parsing, while the
heartbeat still spans it. These results establish improvement of this specific
periodic bottleneck, not a guaranteed frame rate for every configuration.

Focused regression coverage exercises the actual connected combat timer,
hidden archival/overlays, lazy tabs, full exports, selection identity, cache
invalidation, inactive Vitals, slow capture/OCR, stale results, hidden alerts,
worker teardown, style transitions and repeated map countdown restarts.

The synchronous log-reading/persistence path remains a separate potential
source of pauses during large log bursts; it is not rewritten in this release.
The installed executable, live profile, game files and VantageUI skin are not
modified by preparing or publishing this Companion candidate.

## Review guidance

The Qt UI design skill informed the separation of background sampling from
presentation while retaining immediate view changes and active alerts. Qt's
[timer guidance](https://doc.qt.io/qt-6/qtimer.html#detailed-description),
[module thread support](https://doc.qt.io/qt-6/threads-modules.html), and
[QRawFont thread-local restriction](https://doc.qt.io/qt-6/qrawfont.html#details)
were checked: workers create/use their own raw fonts and return images and
plain readings; they never manipulate widgets or emit audio directly.

## Release validation

- Complete suite: 2,398 collected cases across 209 modules; 2,396 passed,
  two environment-dependent skips, zero failures/errors/omissions/duplicates.
  The skips are the POSIX file-mode and Windows symlink-creation checks.
- All 703 frozen source/data/test files matched after the complete run.
- The single-file portable build and `--portable-self-test` both passed.
  Its version marker, file version and product version are `1.44.134`.
- Candidate: `Vantage.exe`, 76,002,692 bytes.
- Candidate SHA-256:
  `7b32377cffb471eea9f3f8912eeec72cb332a1ee825b955915ee96f00a4dab0d`.

## Public verification

Published [Companion 1.44.134](https://github.com/vantageupdates/vantage/releases/tag/v1.44.134)
at 2026-10-15 00:48:19 UTC. Anonymous GitHub API checks confirmed the release
is stable, public and Companion Latest; its tag resolves to tested source
`3776e60b62ba37224e328f3cc3acf9a8ae855ee0`. The uploaded `Vantage.exe`
(asset `642186747`) matches the candidate size and SHA-256 above. No installed
executable or VantageUI skin was replaced as part of publication.
