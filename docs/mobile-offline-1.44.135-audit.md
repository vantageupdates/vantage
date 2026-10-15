# Vantage 1.44.135 mobile offline accessibility audit

Reviewer: codexvenuify, independent mobile_offline_security agent.
Date: 2026-10-15. Scope: companion-web/index.html, app.js, app.css, offline.js,
storage.js, and the PHONE APP dialog in src/vantage/helpers/mobile_share.py.

## Result

All five findings below are resolved and their final implementation changes
have been independently reviewed. No unresolved blocking accessibility finding
remains in this scope. This is a scoped source review with shared browser
evidence, not a whole-application WCAG certification. The release owner retains
the final test, build, and publication gate.

## Findings

| Criterion | Original severity | Specialist | Path / control | Impact | Verified remediation | State |
| --- | --- | --- | --- | --- | --- | --- |
| WCAG 2.4.1 / 2.4.3 | Major | keyboard-navigator | companion-web/index.html and app.js: Skip to content | The #main fragment could be interpreted as an unknown route and switch Spells or another section to Guild. | Skip prevents default navigation and focuses main; the route handler explicitly excludes #main. | Resolved |
| WCAG 4.1.3 usability recommendation | Moderate | live-region-controller | companion-web/app.js and index.html: search counts | A 90 ms visual debounce also drove announcements, risking repeated intermediate speech while typing. WCAG does not itself prescribe a 500 ms delay. | Visual counts remain fast; a dedicated atomic polite live region announces only the visible section after 550 ms. Visual count elements are no longer live. | Resolved |
| WCAG 2.4.3 | Moderate | keyboard-navigator / modal-specialist | companion-web/app.js: Forget saved copy | Successful deletion disabled the dialog's original return-focus control. | Successful deletion assigns import-file as the dialog return target and explicitly focuses it. Errors preserve the existing copy. | Resolved |
| WCAG 2.4.3 | Moderate | keyboard-navigator | companion-web/app.js: Show more | Loading the final batch hid the focused button and could lose the user's place. | Focus moves to the first newly revealed record, with the section heading as fallback. | Resolved |
| WCAG 1.4.11 | Moderate | contrast-master | companion-web/app.css: search/select/file controls | Original boundaries measured approximately 1.98:1–2.69:1 against adjacent backgrounds. | Shared #809392 control boundaries measure 5.41:1 against #111b21, 5.72:1 against #0c151a, and 4.91:1 against #18242b. | Resolved |

## Specialist passes

- Keyboard: native controls, roving tab focus, Left/Right and Home/End navigation,
  visible focus, and section-heading focus are present. Reported focus issues
  are resolved as described above.
- ARIA: tabs and panels are associated; native dialogs are named; loading
  containers expose busy state. Hidden sections are excluded from interaction.
- Forms: inputs/selects have visible labels. The file control describes its
  visible status/error message and size limit. Invalid files and failed saves
  do not replace the stored copy.
- Modals: native modal containment and Escape dismissal; initial focus on a
  non-destructive close control; explicit Save this copy confirmation; Cancel
  preserves data. The LAN PHONE APP dialog restores its invoking focus.
- Live regions: pending, offline-ready, failure, and transfer states use text;
  transfer/import statuses are polite. Search announcements are separately
  debounced at 550 ms.
- Headings and alternatives: one visible section-level heading; subordinate
  record/dialog headings; decorative brand image has empty alt text with an
  adjacent visible name.
- Contrast and reflow: muted text approximately 7.63:1 and focus blue 10.42:1
  against #18242b; controls target 44 px; reduced-motion and forced-color rules
  exist. Root's tested 320 px fixture had no page-width overflow.
- Links: descriptive Wiki/sheet/permanent-app labels and explicit new-tab cues;
  online-only link content is distinguished from locally saved details.

## Browser and test evidence

The release owner supplied these real-browser results:

- Chrome and WebKit imported the fixture through explicit confirmation.
- Both browsers were fully closed and reopened with persistent isolated
  profiles. Networking was disabled before navigation. The app shell and
  IndexedDB records recovered offline; Aster showed 125 DKP and Clarity was
  searchable in Spells.
- In Chrome, an items refresh returning 503 and a spells refresh returning
  invalid JSON preserved the saved catalogs and guild records.
- In Chrome, upgrading the app shell from v3 to v1.44.135 preserved an imported
  625-member guild copy. Searching Roster624 returned that character with 624 DKP.
- The 320 px viewport fixture had no horizontal overflow. Root inspected the
  guild-empty-390 and webkit-guild-390 screenshots in output/playwright.
- Backend focused tests: 41 passed. Frontend focused tests: 6 passed.

WebKit emitted style-src warnings associated with empty style attributes from
browser/automation behavior; tested controls remained functional. CSP was not
weakened to suppress those warnings.

## Readiness and privacy spot-check

Saved data is not called Ready offline before the app shell is saved. Storage
errors retain and distinguish the prior durable copy. Export time is not
presented as the last server refresh. The handoff validates opener window,
exact private origin, nonce, schema, one-use state, and expiry. Explicit user
confirmation precedes durable storage and acceptance acknowledgment. No LAN
pairing URL is persisted by the public app.

The guide documents the permanent HTTPS Home Screen upgrade, separate Safari
and installed-app storage, private JSON fallback, snapshot limits, and the
same-Wi-Fi requirement for live PC tools. Its labels match Saved & Help,
Choose Vantage offline file, Import copy, and Save this copy.

## Limits

No physical iPhone/Android installation or VoiceOver, TalkBack, or NVDA session
was performed for this review. Desktop WebKit is not a claim of full iOS
installation/storage equivalence. The explicit private-file fallback remains
necessary. No deployment or publication was performed by this audit.
