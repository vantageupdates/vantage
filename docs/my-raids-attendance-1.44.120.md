# Recorded character attendance — Vantage 1.44.120

## User workflow

Open **Guild DKP & More → My raids → Recorded attendance**. Load your guild,
choose or type an exact character from its complete directory, select the
date range, and choose **Search attendance**. This public, read-only lookup
does not need a local raid, CSV, login, or a running EverQuest session.

The event/date/pool/raid-ID filter searches the entire returned attendance
history, before splitting it into 250-row pages. The default date range is
90 days; dates may extend back up to ten years, subject to the guild's records.
All columns remain draggable, and narrow windows provide horizontal scrolling.
Raw raid names remain available in tooltips and search even when embedded URLs
and duplicate date prefixes are removed from the displayed event title.

Choose an attended raid and **Check selected raid DKP** to read its public
tick details. Only ticks naming the searched character contribute to the
displayed award. Missing values remain unknown (`—`), never a fabricated zero.
This feature does not modify guild records or infer attendance from EQ logs.
Local raid capture, evidence editing/deletion, and log tick search remain
separate workspaces; **Start raid** still navigates to local evidence.

## Correctness and failure handling

- The character history response uses `RaidName`, `PoolName`, and
  `Ticks[].Attended`; its presence in that endpoint does not mean the character
  attended. Only explicit true/1 tick flags count.
- Missing/malformed attendance evidence is excluded and reported as unknown.
- Responses from previous searches, guild switches, or edited character names
  are ignored. Requests have the existing 30-second network timeout.
- Empty attendance, invalid date ranges, unavailable/malformed responses, and
  retryable request errors have distinct written states.
- Overview uses the same attendance normalizer, no longer substitutes general
  guild raids for a character's attendance, and removes its 100-row cutoff.
- Character lookup includes members with no current DKP record.
- The feature is tenant-generic: Castle/Mindflux are verification data, not
  hard-coded production defaults.

## Verification

- Focused tests: **57 passed** (OpenDKP, attendance, updater heartbeat).
- Read-only live Castle verification: **757 records returned**, **19 attended
  raids**, **26 ticks** for Mindflux in the last 90 days. No credentials used.
- Native Qt screenshot checks at 900×540 and 520×540, with application font
  and theme; event filtering tested with Velketor. The Qt design skill guided
  the separated workflows, explicit error states, and readable date controls.
- Screenshots and live-validation harness are isolated under
  `work/my-raids-attendance-1.44.120`; no real EQ or installed Vantage files
  are changed. Physical screen-reader and OS-large-font tests are not claimed.
- Interaction/scaled panel verification: **18 passed**, including the app-wide
  keyboard/pointer/tooltip regression test. This overlaps attendance coverage
  above and is not an additional unique-test total.
- Complete final suite: **1,714 passed, 2 skipped, 816.95 seconds**.
- Final single-file portable: version **1.44.120**, **75,850,973 bytes**,
  SHA-256 `F68A5E48AB6ADB77329E48618BB1D8301DB50556822951E2783BEA8DDFB5C8B1`.
  Isolated portable self-test exit **0**. Frozen code inspection confirms the
  public lookup, full-history filter, attendance normalizer, tick-detail read,
  input help, and dark date controls are included.
- Installed `D:\\Vantage.exe` and the live Vantage config match their original
  SHA-256 digests. No EverQuest, WinEQ, or installed Vantage process was stopped
  or replaced. Only this task's own test processes were restarted during QA.
- Source and annotated tag `v1.44.120` resolve to tested build commit
  `795fd02966cd660628b36e9953ef0d3eb570d248`, pushed to `main`.
- GitHub release **399721796**, asset **600042349**, contains exactly one
  `Vantage.exe`; GitHub's size and SHA-256 digest match the tested candidate.
  Published stable/latest on **2026-09-30**:
  https://github.com/vantageupdates/vantage/releases/tag/v1.44.120
  Draft is false, prerelease is false, and the latest-release endpoint reports
  `v1.44.120`. The anonymous public release page also confirms publication and
  tested source commit `795fd02`.

## Publication and verification boundary

After the user's renewed explicit request to deliver the update, the normal
`gh release edit` publication command succeeded. No alternative publication
route was used. The release is now public and latest; its executable asset size
and GitHub SHA-256 digest match the already self-tested candidate.

The subsequent combined anonymous-download/hash/fresh-executable-self-test
command was rejected by execution policy **before starting**. Therefore a fresh
public binary download and its separate self-test remain unverified. No retry
through an alternative command, API, or browser was attempted for those blocked
steps. Read-only metadata and the anonymous release-page checks succeeded.
The original candidate already passed the complete suite and portable self-test.
No installed executable was replaced. VantageUI files and authority are unchanged.
