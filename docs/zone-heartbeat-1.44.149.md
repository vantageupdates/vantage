# Companion 1.44.149 — continuous zone recovery

The map now reconciles its zone with the active EverQuest log every two seconds.
Normal live parsing still changes maps immediately. The periodic check recovers
a missed map event without replaying historical casts, buffs or chat.

Previously, bounded historical zone lookup ran only once per log, and the map
used that context only before an active source had been selected. A later missed
zone event could therefore leave the map on the preceding zone indefinitely.

## Log reader

- Cache the latest completed zone/loading context before dispatching each live
  event. Track the character/server and exact file identity and byte position.
- Every two seconds verify the active source and emit its latest context through
  a dedicated signal. Unchanged files reuse verified context after a stat check.
- Independently drain unread bytes if the native watcher and short recovery poll
  have both missed a write. Recheck the file after that drain so a concurrent
  append cannot replace fresh context with an older tail boundary.
- Read at most a 256 KiB tail page plus one historical page per heartbeat. If the
  last zone is older than the tail, continue looking backwards across subsequent
  checks, retaining split-line boundaries. Large logs are not read in full on a
  timer callback.
- Loading, explicit zoning and `/loc` activity select the active source; unrelated
  chat in another character's log does not take over the map.
- Rotation, truncation, partial writes and temporary sharing violations retain
  the reader's normal recovery behavior. The zone timer stops with the reader
  and participates in automatic timer repair.

## Map reconciliation

- Accept the periodic snapshot in addition to the older startup-only context.
- Order observations by file revision, log timestamp and observation time,
  including distinct transitions within one whole-second EQ timestamp.
- Load a newly recovered zone and clear stale player coordinates. A later real
  `/loc` places the player on the corrected map.
- Repeated confirmation preserves the current marker and a manually browsed map.
  A new active zoning event returns the panel to its live map.
- Loading or an unsupported zone clears the old location instead of reusing it.
- Recognize `You have entered`, plus `You have zoned into/to` variants.

## Validation

Reader tests exercise repeated snapshots without replay, dropped live delivery,
partial records, active-character isolation, rotation/truncation, deeper reverse
lookup and split-page lines, sharing violations, timer shutdown and unchanged
file reuse. Map tests cover ordering, duplicate observations and manual browsing.

A complete VantageApp with a real LogReader deliberately skips one map dispatch,
then verifies that the real two-second timer loads the new zone and clears the
old marker. Subsequent `/loc` updates and repeated checks preserve the correct
marker and manual preview.

Release verification records the complete suite, portable executable, self-test,
packaged-source checks and public asset verification. The installed application
and EverQuest processes are preserved during release preparation.
