# Companion 1.44.133 — functional and reference audit

Audit date: 2026-10-13. Base: Companion 1.44.132, commit
`5a76e6d2e3b2ecc277c6603951196a14796e7f76`.

## Scope and method

This is a regression audit of Vantage's implemented features, with targeted
comparisons against original-author documentation and tests. It is **not** a
claim that Vantage implements every feature of GamParse, GINA, EQTool or
NinjaLooter, nor a binary-to-binary certification. No upstream implementation
was copied. Complete Heal was compared with EQTool/PigParse as confirmed by the
user; a separate CCH executable was not available for differential testing.

Testing uses synthetic EQ log lines, disposable profiles and temporary
databases. Native UI tests run the actual Qt application offscreen with external
services disabled. The installed Vantage executable, game processes, live log
files, character INIs and skins were not modified. VantageUI publication remains
under its independent owner.

## Confirmed defects corrected

### Combat / GamParse comparison

- Incoming damage from a non-current active opponent now belongs to that fight,
  rather than creating a fight against the player being hit.
- A hit after the inactivity timeout starts a new encounter instead of reviving
  an expired one. Delayed death lines can still finalize an active encounter.
- Exact death names take priority over substring matches. Ambiguous partial
  names no longer arbitrarily finish the most recent opponent.
- Combining fights retains damage timing, so even a one-fight selection keeps
  its duration/DPS. Combining an archived homogeneous profile retains its
  character/server metadata; mixed profiles are not given invented ownership.

Evidence: `test_combat_parity_regressions.py` — 13 failures before the fix,
16 passing cases afterward; 62 combat-focused cases passed before the full gate.

### Triggers / GINA comparison

- Timer restart/keep/new behavior, cooldowns and counters are scoped by
  character **and server**. One character no longer replaces another's timer.
- Early-end rules correlate shared named or unnamed captures with the starting
  match. Ending Goblin A does not end Goblin B. An explicitly capture-free rule
  can still end all matching runs within its originating profile. Capture-free
  starts also retain structural raw-regex enders such as `(interrupted|fizzles)`;
  an independent review caught and tested that compatibility case.
- `${name}`, `$1` and existing brace tokens render in one pass, without leftover
  dollar signs or interpreting captured text a second time.
- Imported display/speech text is no longer silently reduced to a 120-character
  title. Output is bounded at 4,096 characters, with an import warning if trimmed.

Evidence: `test_trigger_parity_regressions.py`, `test_gina_import.py` and
existing runtime/pack tests. Thirteen new runtime cases failed against the old
code; the final regression file has 25 cases, including actual app dispatch and
structural-ending compatibility.

### Complete Heal / EQTool comparison

- Own `/say`, OOC, shout, auction and supported group/guild call variants work.
- The default format accepts bounded, ordered CH/RCH calls such as
  `001 CH -- Tank`, prefixed chain tags, RAMP markers and named pet targets.
  Custom formats remain explicit filters; ordinary CH conversation is rejected.
- Numeric markers such as `001` advance to `002`; existing repeated markers
  such as `AAA` and `111` retain their previous progression.
- Interruptions only affect a currently active cast, not old history.
- `!KI` must be a complete valid interval command. `!KI10`, `!KI3x` and a
  conversation mentioning the command no longer change the interval.
- Duplicate format tokens fail safely instead of raising a regex exception.
- Chat interval changes update both header and embedded settings, preventing a
  later edit from silently restoring the old interval.
- Compact settings scroll instead of overlapping controls. Keyboard access and
  wraparound include the new scrollbar.

Evidence: `test_heal_chain_parity.py` (22 failures before the fix),
`test_heal_chain_settings_sync.py`, existing CH and window-settings tests:
38 focused cases passed.

### Random Parser / NinjaLooter comparison

- Round winner(s), highest roll and accepted count survive eviction from the
  bounded 500-row display. A 501st participant cannot erase the original winner.
- Full-round ties remain correct, and Clear/New Round/Reset clear all cumulative
  state. Zero-based range locking and one accepted roll per player are unchanged.
- Overflow states explain that only the latest rows are displayed. Default
  Result width fits Winner, Tied winner and Participant; saved user widths remain
  respected.

Evidence: new `test_random_round_history.py` plus existing RandomParser tests:
9 cases passed, with overflow and column-width failures reproduced first.

## Application-wide coverage map

The complete test gate includes every collected test module, not only modules
changed here. Passing coverage is evidence for the scenarios tested, not proof
of every live-service or in-game situation.

| Area | Principal regression coverage |
| --- | --- |
| Quick Bar, headers, window state | Notification rail, vertical/rolled layout, overflow actions, physical metrics, local settings, geometry persistence and accessible control names |
| Combat, history, exports | Damage/tanking attribution, encounter closure, archived profiles, charts, selected fights, export options and output UI |
| Buffs and triggers | Self/other attribution, fading notifications, persistence/update handoff, trigger phases, test actions, mute/TTS selection, packs, sharing and keyword matching |
| Complete Heal | Calls, spacing, interrupted casts, rails/history, local settings and rolled countdown |
| Random, raids and loot | Fair paired rolls, ties, raid ticks, explicit attendance, alt pooling, loot quantities/source, archive persistence and filters |
| Smart Timers and boats | Death/zone matching, cross-zone watch lists, log commands, audio routes, boat schedules and community client/server fixtures |
| Maps and Vitals | Map sources, browsing/interaction, coordinate handling; synthetic percentage/number recognition and alert-state tests |
| Market and item cards | Filters, live auction alerts, item clicks/effects, stats, comparison, sources and servers |
| Zones and quests | Zone data/parsing, quest loading/cache and UI fixtures; no exhaustive live-wiki content certification |
| Guild DKP | Read models, character/alt attendance and ledger tests. Bid requests checked against an in-memory client, without sending real bids |
| Items, notes and logs | Item/note UI, sticky notes, log search/indexing, archive, profile boundaries, folder setup and shutdown |
| Sounds and notifications | Sound gallery, audio choices/profiles, TTS delivery routing, overlays, fading and Quick Bar notification tests |
| Mobile and device sync | Mobile-share endpoints/assets, sync data/conflicts and profile boundaries under test fixtures |
| Updates and UI profiles | Heartbeat, checkpoint/handoff, updater verification, portable packaging/self-test, UI profile backups/restoration and skin-updater tests |

## Native visual evidence

All 17 parser windows were captured expanded and rolled using a disposable
native fixture. Rolled feature headers remained 28 physical pixels high; the
Quick Bar was 30 pixels in this fixture. Six representative screens received an
independent screenshot-only review. It confirmed overlapping Heal settings and
truncated RandomParser results; both were corrected and recaptured.

This is not a certification of every DPI, monitor, theme or assistive device.
Existing compact desktop density was preserved. No decorative animations were
added to frequently read combat, roll or heal data. The intentional horizontal
scrollbar on the wide Combat table remains.

## Explicit compatibility gaps / next validation

- **GamParse:** exact pet-ownership history, raw-log export parity and combined
  inter-fight idle-gap policy were not certified against its executable. Existing
  combined elapsed-gap policy was not changed without reliable evidence.
- **GINA:** bounded `.gtp` import is not full .NET regex compatibility. Conditional
  numeric tokens, exact subsecond timing, all character/overlay settings,
  GUID-based package merging and GimaLink/central-library interoperability remain
  outside verified coverage. Native Vantage share codes are not GimaLinks. One
  audio route per phase remains; import warnings explain Sound/Voice conflicts.
  Early-ended timer phase delivery is not established as identical to GINA.
  Unrelated early-end captures are conservatively rejected rather than stopping
  an arbitrary target.
- **Complete Heal:** RAMP call recognition is not a complete replacement for
  every chain-tag filtering or rotation-scheduling feature. Log announcements
  indicate intent; they cannot prove a heal actually landed.
- **NinjaLooter:** Vantage has standalone rolls, raid/loot evidence, death timers
  and remote OpenDKP bidding. It does **not** yet provide NinjaLooter's full local
  pending-drop/chat-bid/auction-close/award lifecycle. Remote bid confirmation,
  edits and withdrawal need an authorized live-account integration test.
- **Real systems:** physical speaker playback/TTS under live game CPU load,
  fresh OCR captures, authenticated guild services, multi-PC reconnection and
  mobile homescreen recovery need device/in-game checks. These are not replaced
  by offscreen unit tests. External wiki availability cannot be guaranteed.

## Primary references

- [GamParse official changelog archive](https://gambosoft.eqresource.com/gamparsechangelogarchive.php)
  (author-hosted indexed content; direct retrieval was restricted).
- [GINA author documentation: triggers](https://web.archive.org/web/20250520194145/http://eq.gimasoft.com/gina/Triggers.aspx),
  [timer behavior](https://web.archive.org/web/20250219060733/https://eq.gimasoft.com/gina/TriggersTimer.aspx),
  [timer ending](https://web.archive.org/web/20250518110129/https://eq.gimasoft.com/gina/TriggersTimerEnding.aspx),
  [timer ended](https://web.archive.org/web/20250318000547/https://eq.gimasoft.com/gina/TriggersTimerEnded.aspx),
  [packages](https://web.archive.org/web/20250520191505/http://eq.gimasoft.com/gina/SharingPackageFiles.aspx)
  and [GimaLink](https://web.archive.org/web/20250520183909/http://eq.gimasoft.com/gina/SharingGimaLink.aspx).
  Archived author pages were used because the original host was unavailable.
- [EQTool Complete Heal handler](https://github.com/smasherprog/EqTool/blob/main/EQTool/Services/Handlers/CompleteHealCommsHandler.cs)
  and [its original tests](https://github.com/smasherprog/EqTool/blob/main/EQtoolsTests/CompleteHealCommsHandlerTests.cs).
- [NinjaLooter README](https://github.com/eq-p99-tools/ninjalooter/blob/master/README.md)
  and [message handlers](https://github.com/eq-p99-tools/ninjalooter/blob/master/ninjalooter/message_handlers.py).

## Release evidence

- Entire collection: **2,370 cases across 206 modules; 2,368 passed, 2 skipped,
  zero failures/errors**. There are 84 more cases than the 1.44.132 gate.
- Three disjoint, whole-module shards covered the exact collected test IDs:
  no missing or duplicate cases. SHA-256 verification confirmed all **699
  frozen source/data/test files** remained unchanged throughout the final gate.
- Skipped: POSIX private-stage permissions and unavailable symbolic-link setup
  on this Windows environment. They are listed explicitly in the saved proof.
- Single-file `vantage.spec` build completed successfully; the candidate's
  `--portable-self-test` exited 0 in a fresh, isolated profile. File version,
  product version and self-test marker all report **1.44.133**.
- Candidate: **75,990,937 bytes**, SHA-256
  `805630083f48df1744eb44f3fc73f431cf398670fb3433fd24e48e37e1b46b81`.
- Local evidence: `SideKick/work/app-parity-133/final/` contains the frozen plan,
  all three JUnit reports, complete-suite proof, build log and portable proof;
  `SideKick/work/app-parity-133/native/` contains the screenshots.

Public release verification is appended after publication. Earlier top-level
candidate artifacts were superseded before publication; only the `final/`
candidate passed the final gate.
