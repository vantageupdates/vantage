# Companion 1.44.132 — complete compact header menus

## Scope

Follow-up to the native window-header audit in 1.44.131. Disposable native Qt
fixtures only; no installed executable, running game, character INI, VantageUI
skin, or independent UI release metadata was changed.

## Confirmed defects and fixes

- Combat's compact More menu flattened Copy format and Save format into inert
  rows. It now retains the source action hierarchy and all nested commands.
- Combat's live-overlay settings were missing on a cold start because their
  source menu was populated only when opened directly. More now populates it
  when the corresponding submenu opens, using current destinations, row limits,
  enabled states, and selections. The split-button primary toggle still works.
- Repeated menu rebuilding now detaches borrowed actions before clearing local
  entries, preserving both native actions and their Python handles.
- Server Tick's composite countdown disappeared when a compact rolled header
  could not fit it. More now includes a readable, live countdown and progress
  readout, driven by the existing render timer. The selected window width stays
  unchanged, including at 25%, 35%, 50%, and 75% sizes.

## Focused verification

- Thirteen focused tests passed, including the existing physical-header and
  Combat output/overlay tests and three new regression cases.
- Real pointer and keyboard input opens Combat's More menu at 25% and 35%.
  Tests exercise nested Copy/Save menus, synthetic clipboard output, destination
  selection, persisted row counts, the primary toggle, and reopening after a
  normal-to-mini transition. Source QAction identity survives repeated use.
- Server Tick tests cover waiting, pulse, countdown, clearing, repeated popup
  replacement, live updates while open, accessible descriptions, unchanged
  source ownership and width, and absence of additional render timers.
- Screenshot-first reviews of final native popups, including independent
  image-only reviewers, found no definite clipping, overlap, or unreadable
  labels in the reviewed captures. These are not in-game tests or a claim of
  screen-reader certification.
- No new animation was added: menu navigation is frequent, and the tick readout
  displays changing data that must remain directly readable.

## Release gates

- Complete collection: 2,286 cases across 201 modules. All 2,284 applicable tests
  passed; two existing environment-dependent symlink/POSIX permission cases were
  skipped. No failures, errors, omitted cases, or duplicate cases.
- Three disjoint complete-module shards were checked against the final test
  collection. All 694 frozen source/data/test files remained byte-identical
  through the complete suite and candidate build.
- Single-file portable Windows build succeeded. Portable self-test exited zero
  in a disposable profile, with file/product versions both reporting 1.44.132.
- Candidate: 75,986,218 bytes; SHA-256
  `9d90a261fb74058987ba3e91fb0647d29acf4edbde7219cb8c743b7f6e6e3da9`.
- Independent final code review found no actionable blockers; an additional
  20-cycle Qt ownership probe retained source actions and nested menus.

## Public release verification

Published stable [Vantage Companion 1.44.132](https://github.com/vantageupdates/vantage/releases/tag/v1.44.132)
at `2026-10-13T06:38:08Z`, from commit
`f061a08f8a08ad12d57e0612939fd78e9965c779`.
Anonymous GitHub API checks confirmed Companion Latest is `v1.44.132`, not a
draft or prerelease, with exactly one uploaded `Vantage.exe`. Its 75,986,218-byte
size and GitHub SHA-256 digest match the tested portable candidate above.
Release ID: `411362770`; asset ID: `636144015`.
