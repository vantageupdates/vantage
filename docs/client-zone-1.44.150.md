# Companion 1.44.150 — recover zones missing from the normal log

Repeating `/who` can repair the map because its response writes the zone name.
The preceding heartbeat could only recover context that existed in the normal
character log. In the reported session, some transitions were absent there,
while the same installation's `Logs/dbg.txt` recorded the character and zone.

## Read-only fallback

The existing two-second zone check now also follows `dbg.txt` in the selected
Logs directory. It accepts a strict timestamped `Player = ..., zone = ...`
record only after a matching initialization/readiness message. Loading,
unconfirmed connections, partial records and unrelated UI reload messages do
not create a confirmed zone. The application never sends a game command.

The server comes from a known character log, not from debug text. A duplicate
character name across servers is ambiguous and cannot supply this fallback.
A confirmed new character can select its unique known profile only when newer
than the active source's zone/location activity. Pending bytes from that source
are drained before a character switch is considered.

Newer normal `/who` or zone entries retain authority. Sharing violations still
compare against the cached normal timestamp; they do not make an old client
record authoritative. Map ordering uses event timestamps across the two files,
and older queued zone/location messages cannot undo a confirmed client zone.

The tracker reads an initial bounded 256 KiB tail and incremental 64 KiB chunks.
Unchanged files use stat checks, partial lines are bounded, and replaced,
truncated or inaccessible files cannot keep certifying the old client record.
Repeated confirmation preserves the current marker and manual map browsing.
Log Profiles displays the selected zone source for diagnosis.

## Scope

The fallback supplies map zone context only. Buffs, auctions, chat and other
live parsers still need EverQuest logging enabled. No synthetic game events
are replayed through those parsers. No game memory, game input, INI changes,
permission changes or independent VantageUI modifications are involved.

## Validation

Focused coverage includes real debug-record syntax, readiness ordering,
partial CRLF, aligned initial tails, duplicate messages, replacement during a
read, character/server ambiguity, inactive-client freshness, pending-byte
authority, read failures and map ordering.

A full offscreen VantageApp reproduces East Freeport to North Ro without a new
`/who` or normal zone entry. Its fixture combines a filtered copy of original
Holyflux system records with an explicitly labeled transcription of debug
records observed before that debug session was overwritten. This is a replay
of the observed format and chronology, not a claim of controlling or observing
the live game during validation.

The complete suite, portable build, self-test, packaged-code comparison and
public release verification are recorded separately.
