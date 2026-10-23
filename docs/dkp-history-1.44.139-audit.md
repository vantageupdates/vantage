# DKP history 1.44.139 — scoped review

## Confirmed diagnosis

Anonymous, read-only character-source checks found 18 Mindflux purchases before
and after enrichment. The observed disappearance was primarily a display and
selection defect: a long transaction/raid source replaced the item title, then
the mutable selection key jumped to another record. Separately, a partial item
ledger could replace and omit valid character purchase records.

No guild data, account settings, game files, installed executable, or VantageUI
assets were modified by the verification.

## Findings and disposition

| Rule / criterion | Severity | Specialist | Location | Description and impact | Remediation / disposition |
| --- | --- | --- | --- | --- | --- |
| Record provenance and completeness | Major | Data review | `src/vantage/helpers/dkp_history.py`, loot normalization | Ledger-first replacement could drop purchases and hide item names. | One-to-one matching; preserve unmatched evidence, canonical titles and signed source amounts. Ambiguous overlap is labelled and excluded from known totals. Covered in Python/JS shared fixtures. |
| Qt multi-input / WCAG 2.4.3 | Major | Keyboard navigator | `src/vantage/helpers/dkp_history_view.py`, reset/selection handling | Changing source text lost the selected purchase and disabled its item action. | Stable purchase identities and unique aliases; preserve button focus through reset; clear ambiguous/missing selection instead of choosing an unrelated record. Fixed and tested. |
| WCAG 2.4.3 | Major | Keyboard navigator | `companion-web/guild-dkp.js`, `renderRows` | Rebuilding disclosures with mutable keys could lose the user's reading/focus position. | Guild/character-scoped identities, reciprocal unique matching, no focus theft from filters or another page. Fixed and tested. |
| UI-thread responsiveness | Major, initially stop-ship | Independent keyboard/live-region reviewer | Python `_reconcile_loot` and JS `reconcileLoot` | Initial all-pairs matching blocked input for 31.375s Python / 9.022s JS with 2,000 matching purchases. | Initial suite/build stopped and rejected. Typed-ID and raid/name/cost/time indexes plus cached comparisons replaced all-pairs scans. Independent recheck: 0.1183s Python / 0.0518s JS for the same fixture. Closed. |
| WCAG 4.1.3 / native semantics | Pass in changed scope | Live-region controller | `companion-web/guild-dkp.js` | Dynamic status/focus must remain understandable. | Existing polite statuses, debounced announcements, native details/summary and descriptive links retained. No new ARIA roles or layout changes. |

## Evidence and limits

- 122 focused tests passed after indexing, including three 2,000-pair tests with
  bounded predicate-call counts and exact Python/JavaScript output parity.
- Independent seeded replay of 600 mixed cases matched an exhaustive matching
  reference, including conflicts, pools, unknown costs, timestamps and suffix names.
- Post-fix live Qt response replay preserved all 18 Mindflux purchases, canonical
  titles, unique identities, selection and item action through all four sources.
- A Chromium mobile-width check (390 × 844) showed all 18 loot entries, distinct
  repeated purchases, readable titles and a keyboard-reachable canonical Wiki link;
  document width remained 390px. Test output contains public guild data and is not
  committed. Local catalog/image 404s were expected because the source-only server
  did not generate deployment catalogs; this was not an offline-install test.
- Qt offscreen and DOM/session tests verify focus/selection behavior. This is not
  a claim of a physical iPhone test, manual screen-reader validation, or a new
  full-application WCAG conformance audit.
- The Qt and accessibility skills guided stable selection, accessible titles,
  keyboard focus retention, and independent review.

Final complete-suite, portable self-test and public release verification are
recorded separately. The rejected initial run is not counted as release evidence.
