# Mobile Guild DKP: scoped UI and accessibility review

Scope: the new shared OpenDKP panel in the permanent phone app and local QR
page, its cache/data adapter, packaging, and integration. This is not a new
audit of every unrelated Vantage screen.

The accessibility-lead, keyboard, ARIA, forms, live-region, contrast, headings
and link-purpose checklists informed the implementation and independent
review. Existing dark/gold styling and native controls are retained.

## Resolved findings

| Rule / criterion | Severity | Specialist | Location | Description / impact | Remediation |
| --- | --- | --- | --- | --- | --- |
| WCAG 2.4.3 Focus Order | Major | Keyboard | `companion-web/guild-dkp.js`, `renderRows`, detail and Forget actions | An async completion could steal focus, collapse a different pool's row, or remove a focused record beyond the first 60. | Preserve same-context batch size, pool-specific disclosure identity and only the focus owned by the replaced row. Forget respects intervening focus and hidden panels. |
| WCAG 4.1.3 Status Messages | Major | Live regions | `guild-dkp.js`, roster search | The search-count announcer was hidden before selecting a character. | Persistent, debounced roster announcement outside the hidden history section. |
| Data-removal contract | Major | Cache/privacy review | `storage.js`, guarded writes and prefix deletion; `guild-dkp.js`, request chains | A second tab could recreate data after Forget completed, including partial/failed directory refreshes and delayed selection restore without a broadcast notification. | Atomic persistent revision check in the write/delete transaction, cross-view notification, and inherited initiating revisions through restore, directory and character automatic chains. |
| Error recovery | Major | Forms/live status | `dkp.js`, request/collect; `guild-dkp.js`, error states | Restricted public data looked like a connection failure, encouraging ineffective retries. | Structured public-restriction reason with safe, specific guidance; no credential import or authentication bypass. |
| WCAG 2.4.9 Link Purpose (AAA recommendation) | Minor | Link checker | `guild-dkp.js`, item links | Identical names hid different item destinations in a link list. | Include the item name and new-tab warning in each Wiki link. |
| Offline shell completeness | Minor | Lifecycle review | `mobile_share.py`, service worker shell | Newly external shared scripts were absent from the local shell's cache. | Add four exact static assets and advance its shell version; private API responses remain excluded. |
| WCAG 4.1.3 / truthful load state | Major | Browser lifecycle review | `guild-dkp.js`, status-only rendering | An empty saved history could remain labelled Loading after the request completed. | Update only the empty-state paragraph when busy changes; regression covers empty success, offline restore and restricted responses without replacing focused record rows. |

Independent review initially reran 61 focused tests successfully. Later
empty-state and cross-view clearing regressions were added and corrected before
the final full-suite candidate. Native labels, buttons, selects, details and
landmarks were checked; PWA headings follow h1/h2/h3, local-panel headings
h2/h3/h4. Reviewed text contrast is at least 7.58:1 and control borders 4.91:1.

## Browser evidence and limits

- Chrome and WebKit: synthetic roster of 1,201 characters and 67 history
  records; search reaches beyond the first display batch, Show more preserves
  keyboard focus, native details open with Enter, and empty search is explicit.
- At 320, 390 and 768 CSS-pixel widths, no horizontal document overflow and no
  visible panel input, select, button or summary below 44px high.
- Delayed raid responses were tested against changing search focus, a record
  beyond the first 60 and leaving for another tab. Current focus remains with
  the user's chosen control instead of returning to a hidden panel.
- An anonymous, read-only browser check against Castle found the full 1,736
  character roster and loaded Mindflux's authoritative balance and history.
  No real guild records or screenshots are committed as test fixtures.
- Chrome and WebKit were actually closed, reopened with isolated saved profiles and
  placed offline before navigation; saved balance/history remained available
  with a stale-data notice.
- Automated WebKit emits CSP warnings associated with native hidden elements;
  the existing public pre-change app reproduces the same warning class. The
  tested hidden/visible behavior and layouts work. The CSP was not weakened to
  silence them.
- These are desktop browser-engine tests, not certification on a physical
  iPhone, its Home Screen lifecycle, or VoiceOver/NVDA. No screen-reader pass is
  claimed.

## Existing shell limitation (outside the new panel)

| Rule / criterion | Severity | Specialist | Location | Description / impact | Remediation |
| --- | --- | --- | --- | --- | --- |
| WCAG 1.4.4 / 1.4.10 Resize and Reflow | Minor | Browser layout review | Existing `app.css`, `.header-actions` | At 320px with the root font doubled to 200%, the existing Online/Install App header extends the document to 352px. The public pre-change version reproduces exactly the same width. The new Guild panel stays inside the viewport under enlarged text and spacing. | Follow up on the shared shell header's wrapping; no whole-application accessibility-conformance claim is made here. |

Full-suite/build/public release checks are documented separately after those
gates complete. User-installed Vantage, EverQuest and VantageUI were untouched.
