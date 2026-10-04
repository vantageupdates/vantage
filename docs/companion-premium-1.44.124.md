# Companion premium polish · 1.44.124

## Scope and implemented changes

This pass improves Companion's shared native chrome and selected functional defects found during the audit. VantageUI remains owned, edited and released by its separate UI chat; no skin, UI updater core, game INI, game permission or installed executable was changed here.

| Finding / impact | Evidence and implementation |
| --- | --- |
| P1 · Vertical Quick Bar became a wide empty block | The embedded notification rail imposed a 240 px minimum. The action column now shrink-wraps to 30 logical px; active notices use the same queue in an adjacent 320 px owned tool strip, disappear after their pass/expiry, clamp to the screen and follow live pinning. Horizontal mode still embeds the rail. Saved old vertical rectangles migrate without moving the bar. |
| P1 · Shown Server Tick changed size after roll/expand | A resize callback could measure the temporary rolled width before restoring the saved rectangle. Shared restore ordering now reinstates width while the rolled height limit is active, then restores body height. |
| P1 · Replay shortened long speech and reapplied attenuation | Lossless audio descriptors retain full content, raw volume, character profile, voice, pitch and repeat count. Asynchronous replay callbacks cannot replace the original event or accumulate Replay labels. |
| P1 · Audio tests could silently fail or interrupt speech | Preview controls explain Off, individual mute, master mute, zero alert/profile/master volume, queued output and unavailable backends. Explicit previews bypass hidden-window gating only, not mute. Log-profile previews no longer implicitly interrupt current speech. |
| P1 · Timer-trigger messages depended on sound | Ending/ended stages now emit one semantic Quick Bar notice even with audio Off or individually muted. Per-spell fading tests follow the configured Voice/Sound/Off route and individual mute. |
| P2 · Small, crowded, inconsistent window headers | All 16 registered windows share 12 px titles, 14 px action icons and an inset 28 px logical row. Painted titles elide rather than force width; full text remains accessible and in tooltips. Secondary actions move into a keyboard-accessible overflow menu. Quick Bar retains its intentionally different compact drag handle and 24×24 mute control. |
| P2 · Map Loot had a white scroll backing in a dark dialog | Dialog/scroll/viewport/body have scoped names and dark theme rules. A rendered pixel test checks the actual body, and item links remain active. |
| P2 · Test feedback was inaccessible or misleading | Native status labels have meaningful accessible names and announcements. Timer tests say Voice/Sound queued instead of claiming sound was audibly played. Notification History's tooltip explicitly says browsing does not replay sounds. |

Saved physical rectangles and replica presets remain user-owned. Header padding scales with the logical replica; this is not a change to EverQuest's UI scale or screen resolution.

## Coverage

Native inventory: 220 inspectable synthetic captures covering all 16 registered windows in normal/narrow/mini states, a secondary timer, authored/nested tabs, 40 auxiliary/scoped dialog entries and all four global Settings sections. A separate final header run adds 49 states at each of 100%, 125% and 150% simulated display density.

Registered windows: Map, Buffs & Triggers, Vitals, Server Tick, Smart Timers, Combat, Random Parser, Heal Chain, Market, Guild DKP & More, Zones, Quests, Items & Notes, Log Searcher, VantageUI and Quick Bar.

Tracked regression files:

- `test_shared_header_readability.py`: all-window spacing, painted/full title text, persistent inputs, overflow actions, compact/rolled restore and the true vertical column across three densities.
- Existing compact/header/preset/Spells/Timers/Quick Bar tests remain active; semantic expectations reflect the new row and preserve every hidden action.
- `test_premium_notifications.py`: lossless replay, asynchronous attribution, muted/off written timer stages, native preview feedback, actual orientation button, old geometry migration, screen clamp/pinning/hide/reopen/expiry, Map Loot pixels and item links.
- `test_audio_profiles.py`: failed volume/speech submission, completion polling even when a connected backend omits its final signal, stale callbacks and speech pitch normalization.
- `test_owned_dialog_launch.py`: owned settings launch/reuse/focus, fake OpenDKP sign-in outcomes and safe synthetic startup paths.

Mobile: the shipped page was rendered using Qt's Chromium runtime at 319×700, 390×844 and 768×900. Eight tabs at each size, person search, linked guild loot, named-zone records, item detail and cached guild data after a synthetic offline failure were checked. All 33 recorded states retained one selected tab/visible panel and no page-level horizontal overflow. The server bound only to loopback and returned fake data; no real credentials, guild requests, phone pairing or EQ stream were exercised. No mobile production layout changes were needed for this pass.

Validation status: the complete suite and final portable self-test passed. The stable public release, tag, asset size and GitHub SHA-256 also matched the tested candidate.

## Rendering and motion decisions

Qt 6 already provides Windows Per-Monitor DPI awareness; SVG icons and DPI-aware pixmaps were present. This pass improves typography, insets and fit rather than claiming a new HD rendering engine. Tested densities are simulated with Qt, not physical multi-monitor hardware. Native fonts/vectors stay sharp; classic pixel artwork is not globally blurred by enabling smooth bitmap transforms.

Primary references: [Qt high-DPI rendering](https://doc.qt.io/qt-6.11/highdpi.html), [QIcon high-DPI support](https://doc.qt.io/qt-6.11/qicon.html).

Rejected motion candidates:

- Spell/timer row animation: frequent core data updates; would distract from readings.
- Core navigation/Quick Bar action animation: repeated tens or hundreds of times per day; no decorative delays.
- Combat table/chart motion: interferes with data being read.
- Forced marquee under reduced motion: retain the existing bounded static notice instead.

The audit used qt-ui-design, frontend-ui-standards, accessibility-lead, audit and QA guidance to prioritize consistency, honest feedback and keyboard access. This is not whole-app WCAG certification or a physical screen-reader assessment.

## Safety and limits

Tests use disposable profiles. `native_audit_fixture.isolate()` blocks Python/Qt network and live capture/audio/indexing/update/sharing services, and supplies only three synthetic Audit character INIs. An initial audit fixture applied its override before application config verification; that first Character UI capture read installed character UI files. Import order was corrected, a regression added, and all affected evidence overwritten with synthetic-only captures. No live game INIs were modified.

The generic audit reference and Chrome DevTools integration were unavailable; the native Qt harness and existing Qt Chromium renderer were used. The optional Playwright CLI was not in the offline cache and was not installed as a workaround.

The QA fresh-eyes gate remains blocked: one neutral image-only reviewer attempt was rejected by the agent thread limit. It was not retried or replaced with a primed review. Captures were inspected by root and the implementation reviewer, but independent visual verification is not claimed.

Live EverQuest behavior, real audio quality/background playback, actual OCR calibration, real guild authentication, peer/phone reconnection, hardware DPI transitions, install/restore of game files and a user's in-game skin still require live validation. Existing automated tests do not substitute for those checks.

## Release record

- Final complete suite: **1,784 passed, 2 skipped in 1,054.20 seconds (17:34)** with a fresh disposable test directory. An earlier complete run exposed one obsolete Vitals assertion for the former 24 px header; it now checks the exact shared 28 px row, passed its focused test, and passed this complete rerun.
- Final single-file portable candidate: `Vantage.exe`, file/product version **1.44.124**, **75,889,212 bytes**.
- SHA-256: `92016ded08d1882c75a9f0a01c836ced82ee4b733dc50af5a92ed51b24864ac7`.
- Portable self-test: exit **0**, version marker **1.44.124**, isolated profile; no installed executable was replaced.
- Published stable Latest: [Vantage 1.44.124](https://github.com/vantageupdates/vantage/releases/tag/v1.44.124), **2026-10-04 06:12:23 UTC**, neither draft nor prerelease.
- The public annotated `v1.44.124` tag resolves to tested source commit `6f79af809bf0a3bf23af9e6668c54400384f8a91`.
- Public `Vantage.exe` is uploaded. GitHub's public asset metadata reports **75,889,212 bytes** and the exact SHA-256 above, matching the local tested candidate. Verification used GitHub metadata; no fresh public asset download was performed.
- No running installed app was replaced. Independent fresh-eyes visual review and live validation remain subject to the limits above; Companion publication does not publish VantageUI.
