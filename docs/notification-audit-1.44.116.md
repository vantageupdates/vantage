# Companion 1.44.116 notification and UI audit

## Scope and method

Readonly Qt/accessibility and painted-pixel review using an isolated
`VANTAGE_DATA_DIR`. Checked every parser surface instantiated by
`work/closure_ui_audit.py`; captured and inspected Market, Zones, Quests,
Guild DKP, Items & Notes, Log Searcher, Vitals, Mobile Host, Settings,
VantageUI, Combat, Spells, Timers, Live setup, and Quick Bar. Inspected mobile
HTML semantics/static controls and the Quick Bar audio/notice path. The closure
harness reported no missing accessible names/tooltips, table-header tooltips,
or tab tooltips on covered surfaces. Responsive/table/tooltip/scaled-
interaction suite: 13 passed. Broader panel run: 98 passed and one Items &
Notes subprocess failure; that exact test passed alone, so it remains documented
as intermittent rather than treated as a product failure.

## Painted Quick Bar evidence

- Live installed before: `work/notification-audit-1.44.116/01-live-quickbar-before.png`
- 624 px proxy/effect reproduction (blank rail): `work/notification-audit-1.44.116/02-proxy-effect-before.png`
- 624 px effect-free render (visible category and full message): `work/notification-audit-1.44.116/03-effect-free-after.png`
- Final compact reduced-motion rail: `work/notification-audit-1.44.116/04-final-compact-reduced-motion.png`
- Searchable session history: `work/notification-audit-1.44.116/05-notification-history.png`

## Findings and disposition

| Priority | Finding | Evidence | Disposition |
| --- | --- | --- | --- |
| HIGH | Quick Bar notice labels could be logically visible while a nested `QGraphicsOpacityEffect` caused the proxy-hosted rail to paint no written content. Users could hear audio without its textual equivalent. | Actual 624 px before/after pixels above; Quick Bar runtime path. | Release blocker. Remove the nested effect, verify changed physical pixels, preserve readable visual notice when audio is muted or blocked, and retain attributable session history for bounded burst scheduling. |
| HIGH | Pytest had no global profile boundary. Importing `application.py` loads and normalizes the default profile; `portable.py` falls back to `%LOCALAPPDATA%\Vantage`; `config.save()` replaces the full JSON with current in-memory data. Tests installing partial config could overwrite a developer or user profile. | 81 test files import application; 10 call `config.save()`; no prior `tests/conftest.py`. | Release blocker. Force a fresh per-session `VANTAGE_DATA_DIR` before test-module imports, override inherited paths, set offscreen Qt, and prove the protected profile hash/mtime is unchanged. Never print profile or token contents. |
| MEDIUM | Quick Bar notification CSS used 9 px message and 8 px category text; at the user's compact scale this approached 7 px and was not comfortably readable. | `data/ui/_.css` and installed compact screenshot. | Increased the bounded rail faces without changing its 19 px authored height; verify at 624 px and reduced motion. |
| MEDIUM next-step | Shared ParserWindow header targets are authored at 16–19 px, below WCAG 2.2 SC 2.5.8's 24×24 target floor unless an exception or equivalent target applies. Keyboard names and paths exist, but mouse/touch acquisition remains difficult, especially when scaled. | Runtime widget inventory and shared header CSS. | Not part of the bounded notification fix. Enlarge hit rectangles to at least 24 px while retaining dense artwork, or provide and document a persistent equivalent target. Do not claim a full app-wide WCAG pass while open. |
| LOW next-step | Mobile controls are named and semantic, with visible focus and reduced-motion CSS, but Install is 36 px/9 px and timer actions are 34 px/11 px; several tabs, chips, and status labels are 8–10 px. | `mobile_share.py` static controls. | Not a strict 24 px failure; improve toward 44 px mobile comfort targets and more readable support text in a dedicated mobile pass. |

`helpers/motion.py` opacity pulse currently has no call sites. ParserWindow's
header effect is attached only while the header is intentionally hidden and
removed before reveal; no matching painted-content failure was observed there.

## Coverage limits

This was not exhaustive certification. Not verified: physical screen-reader
output; real iOS/Android installed-home-screen behavior; touch ergonomics on a
physical phone; live network/offline/reconnect and remote-service failures;
real EverQuest log/game feed across every parser; every destructive modal
path; contrast over every game-backed image; or every configuration
combination. Final approval is limited to the frozen Quick Bar notification and
history fix, test-profile isolation, and their focused regressions. The dense
header targets and mobile comfort items remain explicit follow-up work.
The screenshots above are an isolated proxy-hosted rendering proof; the
updated candidate has not yet been installed over or validated inside the
user's currently running `Vantage.exe`.

## Implementation verification before the independent gate

- 98 focused notification, audio, rendered-rail, history, and profile-isolation
  tests passed.
- 10 Quick Bar, settings-audio, and trigger-action tests passed.
- 12 responsive table, tooltip, and scaled-interaction tests passed.
- The protected live profile remained byte-for-byte and timestamp identical
  across focused tests (same size, SHA-256, and nanosecond modification time).
- Source compilation and whitespace/diff checks passed. Full-suite, build, and
  installed-runtime verification remain intentionally pending until the
  independent accessibility/UI gate approves the frozen candidate.
- Independent scoped accessibility/UI review of commit `726d476`: **PASS**.
  The gate covered painted proxy-hosted pixels, the keyboard path from the
  Quick Bar history button through Search, Table, Copy, and Close in both
  directions, newest-first order, stale-selection safety, semantic latest-
  audio copy, stable compact geometry, and test-profile isolation. This is a
  scoped approval, not a claim of full-product accessibility certification.
