# Continuous log delivery — Companion 1.44.146

## Reproduced failure paths

The reported failure is intermittent: Vantage's buttons still respond when
events appear to stop. Read-only inspection found current Holyflux chat
activity during this investigation, so a continuously disconnected log folder
was not established. These fixes address reproduced failure paths rather than
claiming an exact diagnosis of the installed session.

Nested Qt event loops could reenter the log reader during context or line
delivery. Reproductions demonstrated duplicated/skipped bytes and later batches
overtaking earlier cast/landing messages. Reading is now serialized, with
deferred work queued for the existing reader. Stopping a reader during a signal
also cancels remaining delivery and prevents its watches from being restored.

A consumer exception previously escaped the application's dispatch loop and
prevented later features from seeing that event. Character context, chat
classification/notifications, camp tracking, each feature and profile saving
now receive independent error boundaries. Failed context creation uses the
current event's identity instead of the previous character's context.

## Recovery and visibility

The existing 250 ms fallback continues checking known logs. A 15-second health
check repairs stopped polling timers or missing watches on the same reader,
preserving per-file cursors. Intentional disconnection remains respected.
Quiet logs are not treated as evidence that EverQuest is closed.

Log Profiles now shows reading versus processing counts, pending bytes, the
last delivered line and active feature errors. Copy diagnostics includes these
details without conversation content. Bounded local dispatch diagnostics keep
component names, exception types and code locations, not exception messages or
EQ text. Repeated notices and diagnostic writes are throttled.

A native Qt compatibility check also covers Wiki response headers, preventing
a bytes/string mismatch from interrupting asynchronous reference-data handling.

## Focused evidence and limits

Reader tests include 4,480 events across two characters, nested event loops,
rotation and missing watches, with exact once-only ordered delivery. Dispatch
fault injection includes an isolated native file-watcher/application run:
Bravery appears on another character while map processing raises an exception,
then the next healthy zone event restores map processing without losing the
buff. Log Profiles tests distinguish quiet, disconnected, pending and failed
states, and check that copied diagnostics exclude message and credential fields.

These tests use disposable profiles and synthetic logs. They do not replace
the running installation or establish that every intermittent desktop failure
has been reproduced. Existing buffs, settings, game files, VantageUI skin and
the independent UI release channel are unchanged by this release process.

## Release evidence

The external `log-monitor-146` gate binds the complete collected test suite,
frozen source, clean portable build, packaged modules, portable self-test and
release commit. Final public verification is recorded separately in
`log-monitor-1.44.146-verification.md` after completion; preparation alone is not
evidence of a passing build or published update.
