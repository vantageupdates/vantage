# Companion 1.44.131 — stable window headers

## Scope

Native Companion windows only. VantageUI skin/version authority remains in the
separate UI chat. No installed executable, live game, character INI, or skin was
modified by this audit. All test profiles and captures are disposable fixtures.

## Confirmed baseline defects

- Mini shrank title strips to about 10 px and lettering to about 6 px, while
  rolling switched back to full-sized controls. Native corner resize handles
  could intercept the tiny frame/hide buttons.
- Long captions in rolled windows budgeted against the larger design canvas,
  overlapping controls or extending outside the fixed rolled rectangle.
- Repeated same-state collapse calls overwrote the saved expanded geometry.
- Expanding showed every body widget, including deliberately hidden sections.
- Vertical Quick Bar acquired a 96 px minimum width, magnifying a 30 px column.
- Smart Timer keyword counters used a missing icon and icon-only width limits.

## Changes

- Titles, icons, margins, and controls retain authored physical dimensions while
  body replicas keep their selected scale. Native menus and body fonts are not
  scaled with header chrome.
- Roll-up preserves the actual width and transform. Only the body disappears;
  expansion and tray reopening restore the exact selected rectangle.
- Packing uses the actual canvas width. Secondary controls move to More, with
  native-scale editable selectors/spinners when primary inputs cannot fit.
  Full captions remain available to tooltips and assistive technology.
- Live menu editors survive their own value changes and background repacking.
- Collapse is idempotent and restores prior body-widget visibility.
- Vertical Quick Bar stays one column at 1:1 scale. Horizontal Quick Bar retains
  readable header height plus visible scaled command/notification lanes.
- Keyword-rule counters use the bundled bolt icon and fit their complete text.

## Verification

The focused gates cover every catalog window, Tiny/Mini/Compact/Normal/enlarged
scales, long dynamic captions, repeated roll/tray cycles, native pointer hit
targets, readable fonts, popup editing, and multiple Windows display scales.
Native Qt captures supplement geometry checks; they are not an in-game test.
Release verification is recorded after the complete suite, portable build,
self-test, and anonymous public asset verification succeed.

### Final automated gates

- Complete collection: 2,283 cases across 199 modules; 2,281 passed and two
  existing environment-dependent cases skipped. No failures, errors, duplicate
  cases, or omitted cases. Disjoint complete-module shards were checked against
  the final collection; entire failed modules were rerun after adapting obsolete
  size assumptions and exercising real visible More-menu launchers.
- Actual pointer/keyboard launch and focus return passed for all eight settings
  owners at Normal and Tiny, including native popup tooltips and Escape.
- A 25-row synthetic timer zone exercises genuine overflow and deferred focus
  reveal, without background network, game discovery, or audio services.
- The 18 changed production/data/version files remained hash-identical through
  the final suite and candidate build; later changes were test-only.
- Single-file portable Windows build succeeded. Portable self-test exited zero;
  Windows file/product versions both report 1.44.131.
- Candidate: 75,984,270 bytes; SHA-256
  `ec86129ab3c481939a347e359e207552a82a5c10ed7f5792a866187572602538`.
- Screenshot-first independent review of native header crops found no definite
  clipping, overlaps, or stray icon fragments in the reviewed final captures.
- Stress audit: all 17 windows, 1,122 state records, zero findings or exceptions.
  Popup clones are audited in their native menu coordinates, not misclassified
  as hidden authored header controls.
