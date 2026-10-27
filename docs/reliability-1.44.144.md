# Logs, map pointer, DKP and Wiki reliability — Companion 1.44.144

## Log recovery and zone changes

Native file notifications are backed by a one-second recovery poll. Removed
watches, newly created character logs, replaced/truncated files and temporary
sharing violations recover without reconnecting manually. Every log retains its
own byte cursor. Incomplete lines wait for their newline; bursts drain in small
batches so parsing does not monopolize the Qt event loop. Corrupt oversized
records cannot block subsequent zone events.

A bounded tail read recovers the latest zone when connecting to an existing
log. Only zone context is restored: old casts, buffs, audio and combat events
are not replayed. Live zoning and /loc events still use the character/server
identity of their source log. Stopping monitoring also stops recovery timers
and ignores queued notifications from the old reader.

## Map pointer

The physical LOC readout now accepts coordinates from the inner canvas's mouse
events as well as the outer viewport and desktop cursor sampler. A valid local
event is not immediately discarded when the global cursor position is stale.
Cached events are invalidated when the window/proxy geometry changes. The normal
arrow cursor remains while dragging; empty-space panning preserves clickable
map points. The old generic hover tooltip is replaced by accessible instructions.

Tests exercise actual mouse press/move/release through the outer graphics proxy,
cursor coordinates at different positions, stationary-cursor geometry changes,
and log recovery all the way through the application parser to the map. Isolated
Qt tests do not claim to reproduce the user's active EverQuest desktop session.

## Guild DKP

Public responses are scoped to their guild and obsolete requests are cancelled.
Repeated refreshes coalesce pending reads instead of restarting them. Ongoing
guild loot pagination survives Refresh. Unchanged personal history and loot
reuse their prepared data; large personal histories reconcile in one background
worker, with obsolete character/guild results discarded before display.

## P99 Wiki cache

Challenge pages, failed/empty API responses and incomplete catalogs cannot
overwrite previously valid references. Writes are atomic and saved references
show cache freshness. Wiki views share cooldown/backoff for access restrictions,
rate limits and server overload, honoring Retry-After. Cached details and bundled
catalogs remain available while refresh is paused.

A normal read-only request during investigation returned HTTP 403 with
`cf-mitigated: challenge`. No access-control bypass was attempted. This release
protects a partial, on-demand cache; it does not include a complete Wiki backup.
A full offline corpus needs a permitted export or a maintainer-provided dump.
See [MediaWiki API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) and
[MediaWiki export documentation](https://www.mediawiki.org/wiki/Help:Export).

Installed executables, running game processes, VantageUI skin files and existing
user profiles are not replaced by the release workflow.
