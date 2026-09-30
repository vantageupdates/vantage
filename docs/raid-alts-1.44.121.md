# My raids alt groups — Vantage 1.44.121

## Workflow

**Guild DKP & More → My raids → Recorded attendance → Manage alts…**
opens a compact editor with the guild's complete character directory. Choose
or type a character, **Add alt**, then **Save**. Each saved alt is visible in
the list; **Remove selected** edits the group, and **Cancel** discards edits.

The selected character is always included. **Include alts** adds the saved
group to the date-range lookup; turn it off for a single-character search.
Adding the selected character to the group is permitted but does not issue
a duplicate request. Groups and the Include alts preference persist separately
for each guild, survive settings normalization, and are limited to 24 alts.

Results contain one row per stable raid ID, with a **Characters** column.
Filtering searches participant names as well as event/date/pool/raid ID across
all results before pagination. The guild's DKP pools remain distinct in the
Pool column; the feature does not combine account balances.

## Counting and safety

- Shared raid IDs count once; shared tick IDs within a raid count once.
- Tick awards are counted once per shared tick, not added repeatedly for each
  alt. Missing or conflicting amounts stay unknown. When missing tick IDs make
  deduplication uncertain, the unique tick count stays unknown instead of being
  invented. Per-character membership counts are retained with the pooled row.
- **Check selected raid DKP** reads a single public raid roster and verifies all
  group members. It reports individual matching tick counts and the unique
  combined tick award. No guild records or DKP balances are modified.
- Character histories are fetched at most two at a time. Each response is
  correlated with the search generation, guild, and character ID. Edited groups,
  guild switches, retries and late responses cannot mix previous results.
- Failed or malformed alt requests do not erase successful results: the UI
  names unavailable members, labels the result partial and allows a retry.
- Saved identities must still exist in the loaded guild directory before a
  search starts; an invalid saved alt prompts the user to update the group.
- User-specific character names are verification fixtures, not hard-coded
  defaults assigned to other users. Real running app/game profiles are untouched.

## Verification

- Focused OpenDKP, aggregation, config persistence, modal Save/Cancel,
  scaled interaction and heartbeat checks: **70 passed**.
- Read-only live Castle check for the user's examples, last 90 days:
  Mindflux 19 raids, Wildflux 14, Fistflux 2, Spiritflux 5. The union is
  **39 unique raids / 53 unique ticks**, not 40 duplicated character memberships.
- Actual character IDs were resolved from the public directory:
  Mindflux 163372, Wildflux 163374, Fistflux 163375, Spiritflux 163373.
- Qt design guidance informed the compact editable list, explicit Include alts
  control, written partial/error states and keyboard help. The themed workspace
  was visually checked at 1000×580 and 520×580, plus the 440×360 alt editor.
  No physical screen-reader or OS-large-font testing is claimed.
- Final portable candidate: **1.44.121**, **75,862,610 bytes**,
  SHA-256 `B5FA6C38C735A9EBB09849B6B13FC58C84014000F772429A3226F58CE75F7617`.
  Isolated self-test exit **0**; frozen editor, preference restoration, bounded
  queue, attendance union and public pooled-DKP check verified.
- Complete final suite: **1,726 passed, 2 expected skips, 798.78 seconds**.
- Tested source/tag: `1c27fa55ec156d53a4986ec4e2b5df439b8e3ade` on `main`.
- Published stable/latest release **399746700**, asset **600129160**, at
  `https://github.com/vantageupdates/vantage/releases/tag/v1.44.121` on
  2026-09-30 05:38:02 UTC. The latest endpoint reports draft false and
  prerelease false, with exactly one uploaded `Vantage.exe` matching the
  candidate's size and SHA-256 digest. The anonymous public release page
  independently confirms the version, Latest designation and source commit.
- Installed `D:\Vantage.exe` remained the user's 1.44.120 executable with
  SHA-256 `F68A5E48AB6ADB77329E48618BB1D8301DB50556822951E2783BEA8DDFB5C8B1`;
  the live config remained
  `C418D49888A0E4B38FE0A34C9CA1075D57FD98F50E00981F2CF1C97B476BC0A5`.

## Release verification boundary

The normal standard publication command succeeded after the complete tests;
the delivered update is public, not draft-only. The installed executable and
EverQuest/WinEQ/Vantage processes were not replaced or closed.
The previous combined fresh public binary download-and-execution verification
was rejected by tool policy. Do not bypass that restriction through another
route; distinguish candidate self-test and public size/digest metadata checks
from the unperformed fresh-public-download self-test. That extra check was not
retried for this release; the candidate self-test and public size/digest checks
are the verified evidence. VantageUI ownership and its files remain unchanged.
