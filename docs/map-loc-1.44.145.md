# Map LOC, spell references and log delivery — Companion 1.44.145

## Preparation status

This document records the candidate changes and focused evidence. The complete
test suite, clean portable build, portable self-test and public release
verification are pending. The candidate has not replaced the installed app.

## Cursor-adjacent map coordinates

The LOC readout now uses one text item in the map scene. Local mouse movement
maps directly from viewport coordinates to scene coordinates and updates that
item. Outer-window and desktop-cursor recovery update the same item; they no
longer rely on a separate label layered above the graphics proxy.

The implementation follows the original nParse scene-rendering approach,
reviewed at commit
[`b9d897ea867825e489c42aa32bd6d5684749e0cd`](https://github.com/nomns/nparse/tree/b9d897ea867825e489c42aa32bd6d5684749e0cd),
in `src/nParse/parsers/maps/mapcanvas.py` and
`src/nParse/parsers/maps/mapclasses.py`. Existing nParse attribution and GPL-3.0
notices are retained.

The readout compensates for the outer Mini scale, stays within the viewport,
and disappears when the pointer leaves, a menu opens, or the map is hidden.
The normal arrow cursor still pans the map; POI clicks, map previews, the LOC
toggle and the keyboard shortcut remain available. An inner enter event no
longer discards a valid local position just received from the outer viewport.

Focused coverage passed 72 map tests. The assertions compare rendered pixels,
text and positions, including Mini sizing and viewport edges, rather than
treating a visibility flag as proof that text was painted. A separate native
Windows diagnostic fixture was also observed painting the LOC readout. That
fixture is isolated; this is not a claim that the running user installation
was replaced or that every desktop configuration has been verified.

## Spell references when the Wiki is unavailable

The spell-reference changes retain usable local data when the Wiki cannot
provide a valid response, including HTTP 403 challenge responses. Focused
spell/Wiki coverage passed 43 tests. This is local resilience, not a Cloudflare
bypass or a complete Wiki mirror.

## Timely log delivery

A directory-change event now reads the first completed lines of a newly
created character log immediately. Previously, adding the file watch after
that first write could leave its cast and landing messages waiting for the
next recovery scan.

Known logs receive a 250 ms fallback check when Windows notifications are
lost. Directory discovery stays at one second; native file notifications
still deliver immediately. Independent character cursors, original EQ
timestamps, partial-line handling and rotation recovery are preserved.

Fifteen focused reader tests passed, including a native event-loop burst of
302 ordered cast/combat lines, recovery after a missed notification, a brief
Windows sharing violation and cancellation after stopping the reader.
Comparing nParse's original reader did not justify replacing these safeguards
with its single global cursor and watcher-only delivery.

## Owned buffs and whole-second log timestamps

The active log was confirmed in Windows VirtualStore using recent application
chat activity; the older canonical log alone is not evidence of a wrong active
connection. All six recent Symbol/Bravery casts in the Holyflux log contained
matching landing messages. With a 250 ms user casting buffer, Bravery on another
character was rejected: its 2.75-second cast appeared as two whole seconds in
the log. Same-second Yaulp casts were also rejected.

Matching now retains at least one second of early timestamp precision tolerance,
while preserving the existing late cutoff and cleanup timer. It still requires
the owned cast, the exact effect message and a bounded landing window. A focused
run across six spell regression modules passed 22 tests, including a real-time sequence through
the file watcher, application dispatch and visible Symbol/Bravery target rows
with 0 ms and 250 ms settings. The test processes Qt events during the 4-second
and 2.75-second casts, then verifies that rows remain active after cleanup.
Boundary tests cover the exact late cutoff and rejection immediately beyond it.

The default 1000 ms setting successfully reproduced these rows before the fix;
the exact failure in the installed instance is therefore not fully established.
Durations still depend on the caster's known/configured level. An unknown-level
fresh profile can underestimate an initial Symbol duration; this release does
not infer a caster level from an ambiguous cast/item message.

## Release verification still required

The external `map-loc-145` verification scripts bind the frozen source, complete
suite, clean executable, packaged modules, portable self-test and exact release
commit. Packaged-code checks include map rendering, `logreader`, `spell_library`
and `spells`. Public verification must compare the release asset size and
GitHub SHA-256 digest with the tested executable and check the deployed phone
assets. No passing full-suite, build or publication result is claimed here.

The independent VantageUI version, skin files, installed executables and user
profiles are preserved by this preparation step.
