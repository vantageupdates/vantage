# Triggers audit and TTS selection: Companion 1.44.126

Audited on 2026-10-06. Baseline: Companion 1.44.125, source
`df8fe9f4df8c2176c0dd2cf6c18f147158098e12`. The running `D:/Vantage.exe`
matched the published 1.44.125 byte count and SHA-256; an old installed binary
was not established as the explanation for the reported TTS selection issue.
No running app, EverQuest installation, skin, character INI, or account was changed.

## Outcome and scope

Vantage is not an exact GINA implementation. The review found useful coverage
of GINA-style workflows, real runtime limitations, and unverified external
interoperability. Internal round-trip tests do not establish full parity.

The specific TTS change is scoped to **Sounds → Trigger audio actions**.
Previously, those rows offered WAV/gallery/Off choices only, omitted TTS-only
rules, and changing the selected sound forced that phase to Sound or Off on
Save. The full **Quick Bar → Triggers** editor already offered TTS; isolated
pointer and keyboard checks did not reproduce an inability to select it there.
The user's precise failing screen has not yet been confirmed.

The Sounds rows now offer **Sound / WAV**, **Text to speech**, and **Off** for
the matched, ending-soon, and ended phases that are applicable/configured.
Speech mode exposes its message, Windows voice, volume, pitch, interruption,
and explicit Test action. Switching modes retains inactive WAV and speech
settings. Save merges changed audio fields into the existing rule, rather
than replacing unrelated fields or phases. Trigger mute and Master Mute still
apply. Audio Off does not disable matching, timers, or written output.

## Current workflow review

| Step | Health | Finding or check |
| --- | --- | --- |
| 1. Open Quick Bar → Triggers | Available | Independent library entry, groups and search; not a second parser |
| 2. Select Basic → Delivery → Text to speech | Tested in isolation | Existing full editor permits pointer/keyboard selection; speech controls become available |
| 3. Open Sounds → Trigger audio actions | Fixed omission | Consistent three-way delivery choice, including TTS-only rules |
| 4. Enter speech, Test, Save and reopen | Focused verification passed | Current-draft Test, cancellation, saved route/voice/message and retained inactive audio verified; final full-suite gate recorded below |
| 5. Import or share a pack | Partial compatibility | Review and disabled copies; native files/codes differ from GINA hosted sharing |
| 6. Run multiple character/target timers | Warning | Two concrete isolation defects reproduced below; not changed by this release |

Fresh rendered screenshots cover the Sounds dropdown and speech form at
80%, 100%, 125%, and 150% dialog scale, with 125%/150% DPI coverage. Additional
full-editor Basic/Ending/Ended screenshots cover 125% and 150%. They are saved
under `SideKick/work/triggers-audit-126`, named
`sounds-trigger-dropdown-<scale>.png`,
`sounds-trigger-text-to-speech-<scale>.png`, and
`trigger-editor-<phase>-<scale>.png`. The release owner opened and inspected
100%/150% Sounds and 150% Basic captures. A separate image-only reviewer
found no visible overlap of the core fields or footer controls; subdued
dropdown/border affordances and tight phase-caption spacing remain visual
opportunities. That review does not measure exact contrast or audio behavior.

This is an offscreen native-Qt
development audit, not a live GINA, game, physical-audio, or screen-reader certification.

## GINA comparison grounded in original documentation

The original host could not be resolved during this check. The review instead
read archived copies of the original GimaSoft documentation, not third-party
descriptions, another product named GINA, or decompiled application code.

| Area | Original documented workflow | Vantage finding |
| --- | --- | --- |
| Match, display and speech | Patterns, character token and regex capture substitutions feed configured output. [Official Triggers guide, archived](https://web.archive.org/web/20250520194145/http://eq.gimasoft.com/gina/Triggers.aspx) | Friendly patterns, Python regex, captures and output exist; whole-line friendly matching and raw `.match()` are local semantics, not a certified GINA equivalent |
| Basic audio | Alternative audio formats, speech text, interruption, and per-character audio preview. [Official Basic guide, archived](https://web.archive.org/web/20250422065041/https://eq.gimasoft.com/gina/TriggersBasic.aspx) | One audio route per phase, voice/interruption controls and explicit tests; the previous combined Sound+Voice parity claim was not established |
| Timer | Duration, name, retrigger behavior and early-ending text. [Official Timer guide, archived](https://web.archive.org/web/20250219060733/https://eq.gimasoft.com/gina/TriggersTimer.aspx) | Countdown/restart/keep/new, stopwatch/repeating extensions, duration captures and early enders; multi-character/target isolation has reproduced problems |
| Ending soon | Configurable warning deadline, display and audio. [Official Ending guide, archived](https://web.archive.org/web/20250518110129/https://eq.gimasoft.com/gina/TriggersTimerEnding.aspx) | Corresponding configurable ending stage; not proof of every timing/retrigger edge case |
| Ended | Completion-stage display and audio. [Official Ended guide, archived](https://web.archive.org/web/20250318000547/https://eq.gimasoft.com/gina/TriggersTimerEnded.aspx) | Corresponding stage on normal expiry; early cancellation removes the run without that stage |
| Groups | Nested organization and enabling groups separately for characters. [Official Groups guide, archived](https://web.archive.org/web/20250422063048/https://eq.gimasoft.com/gina/TriggerGroups.aspx) | Groups, parent gating and character overrides; local profile keys lack server identity |
| Characters | Multiple logs with separate voice, speed, volume and phonetic name. [Official Characters guide, archived](https://web.archive.org/web/20250520192831/http://eq.gimasoft.com/gina/Characters.aspx) | Multiple log contexts and character filtering, but not the same complete character-audio profile system |
| Categories | Route text/timers to selected overlays. [Official Categories guide, archived](https://web.archive.org/web/20250518110201/http://eq.gimasoft.com/gina/Categories.aspx) | Local overlay routing exists; external category/overlay definitions and layouts are not fully preserved in packs |
| Match history and library | History aids diagnosis; a hosted library supplies packages. [Official Features guide, archived](https://web.archive.org/web/20250518105708/http://eq.gimasoft.com/GINA/Features.aspx) | Bounded Match Log/search/copy/CSV exist; no equivalent hosted Gimagukk library |
| `.gtp` sharing | Compressed XML/media packages imported through Merge. [Official Package guide, archived](https://web.archive.org/web/20250520191505/http://eq.gimasoft.com/gina/SharingPackageFiles.aspx) | Known XML/WAV subset with review; IDs/GUIDs are not retained for identity-based merge; no external GINA-app import certification |
| Codes/hosted sharing | Upload, temporary token, log-detected invitation, trusted senders and Merge. [Official GimaLink guide, archived](https://web.archive.org/web/20250520183909/http://eq.gimasoft.com/gina/SharingGimaLink.aspx) | Self-contained `VT1:` native code/link and manual paste; not GimaLink or its log-invitation/trust workflow |
| In-game trigger exchange | Import/export game trigger sets, including speech-to-WAV export. [Official In-game guide, archived](https://web.archive.org/web/20250520195148/https://eq.gimasoft.com/gina/SharingIngameTriggers.aspx) | Not implemented as an equivalent character trigger-set import/export system |

The archived documents describe intended workflows; they do not certify the
current GINA binary or availability of the original hosted service. No GINA
installer was run or copied into Vantage. Actual GINA-app import/export remains unverified.

## Prioritized local findings not fixed in this scoped change

| Priority | Finding | Evidence and consequence |
| --- | --- | --- |
| P1 | Timer ownership crosses character contexts | Actual application dispatcher: Alice starts a rule, Bob starts it with standard Restart and zero repeat guard; only Bob's run remains. Matching runs/keys are definition-wide, not character/server-wide |
| P1 | A target-specific early ender cancels other targets | Actual dispatcher: independent Goblin A/B runs in New mode; `End target Goblin A` removes both. Captures are not correlated with the initiating run |
| P2 | Import silently shortens some output to 120 characters | `_safe_name` in `gina_import.py` is used for display text, timer names, and Ending/Ended speech; no dedicated truncation warning |
| P2 | Regex and token compatibility is partial | Python versus imported .NET syntax; friendly patterns are anchored, generic captures are ASCII-focused and not necessarily numeric. Compile success is not behavior equivalence |
| P2 | Identity/profile/layout interoperability is partial | Accepted IDs are not stored/exported; imports create renamed disabled copies, not identity-aware updates; layouts and complete character audio settings are not transported |

The default match guard and counter are also definition-wide, so quick events
from distinct log contexts may interact. These are present-source findings,
not proven regressions against an earlier release. The audit does not infer
precise GINA outcomes for undocumented corner cases.

A durable probe at `SideKick/work/triggers-audit-126/runtime_parity_probe.py`
uses `native_audit_fixture.isolate()` before importing the application. It
disables live logs/discovery, audio, network, updates and sharing, then sends
the same tuple shape as LogReader through `VantageApp._parse`. Both scenarios
were reproduced by the independent code reviewer and by the release owner.
Its assertions record observed defects, not desired regression behavior.

## Candidate and publication evidence

The first candidate used Settings SHA-256
`699e5e246d4e4760ba1f4b54368f05667e335745415b9b1de3606f4429d20b23`.
That single-file build completed with exit 0 in 103.463 seconds using the
repository's `vantage.spec`, Python 3.14.6, and PyInstaller 6.22.2. No runtime
packages were installed or upgraded during this work.

Superseded candidate, never published:
`SideKick/work/triggers-audit-126/portable/Vantage.exe`.
FileVersion, ProductVersion and the isolated portable self-test marker are
all **1.44.126**. The self-test returned **exit 0**; the user app was not launched
or replaced. Candidate size: **75,940,529 bytes**. SHA-256:
`038c6cf43d8de8dd20768dd96f8e008cbcedccf4553182e27498128ac2e2361a`.

The first independent focused run was 99 passed/1 failed in 28.42 seconds.
Its failure was an old parent-widget lookup for Test after the button moved
into the phase's delivery row. The updated test finds the same accessible
Test through its route and retains the mute/no-playback assertions.

Some initial whole-app offscreen matrix subprocesses faulted in native Qt
after producing successful behavior results. These nonzero exits were not
accepted as passes. The new picker tests use themed QApplication, existing
SettingsSignals, actual widget classes and the real bound Spells delivery
method, without constructing unrelated background parsers. The offscreen
accessibility bridge is stubbed only in that fixture; visible/accessibility
status values remain checked. Existing full-application integration tests
remain in the suite. Physical Windows accessibility/audio is not certified.

The next focused run passed **33 tests in 86.45 seconds**, with strict
successful subprocess exits. An independent final code review then found a
new mismatch on legacy speech-only rules: editing only their visible TTS
volume stored 42%, and Test used 42%, but actual delivery still inherited the
37% global fade volume. The full-suite run was deliberately interrupted at
18%, with no completed-suite success claim. Only the verified owned pytest
process was stopped; no Vantage or game process was stopped.

The initial bounded correction pinned explicit TTS delivery when active speech
controls were edited on a still-legacy phase. Untouched legacy rows and
externally edited explicit modes remained unchanged. On Settings SHA-256
`7f97641eba86b4c059f4ea66848ab8fc44f0c11ec527317a6b341af723e9e670`,
the independent actual-Sounds-save and bound-runtime probe passed in 7.03
seconds: Basic/Ending/Ended stored, Test and live delivery all used 42%.
It also verified unchanged legacy rows and preservation of concurrent explicit
Sound mode, WAV references and comments. The original candidate is retained
for provenance, not offered as an update.

The final correction commits the selected Sound/TTS/Off mode for **any dirty
phase still using legacy delivery**, while an untouched row returns without
conversion and an external explicit mode is preserved. This also covers
selecting Sound, adding an inactive WAV, then returning to the original TTS
selection; the WAV must not become active merely because fallback priority
would otherwise select it. The analogous return-to-Sound and return-to-Off
cases retain their inactive speech choices.

Final production Settings SHA-256:
`90c69507067fb4e956c93fa8df4e4b61dee9f6fed6b3ed1842b72b9b3b32d7b9`.
New test-file SHA-256 before lifecycle hardening:
`f0c2f28d9c9852b864cad027415d692eae00fe3102b9280352fb49657876991f`.
The combined focused gate passed **34 tests in 87.02 seconds**; the final
simplified legacy fixture separately passed in **1.08 seconds**, with no
relaxed exit-code/assertion requirements. It uses one themed settings window
and one Save for all subjects, avoiding unrelated rendering/lifetime overhead.

The release candidate was built from that frozen production source using
`vantage.spec` in **87.938 seconds**, exit 0. Archive inspection confirmed
the final `legacy_phase_edit` logic in the bundled SettingsWindow. The new
isolated portable self-test returned **exit 0**, marker **1.44.126**.
Candidate: `SideKick/work/triggers-audit-126/portable-release/Vantage.exe`.
Size: **75,940,262 bytes**; FileVersion/ProductVersion: **1.44.126**.
SHA-256: `2768d4d33406a941f86d1f644c5ead896f73947e47d04ae4775d40310ec93e19`.
Earlier candidates were not published or installed.

The first completed full-suite gate finished with **1,922 passed, 2 failed,
2 skipped in 869.42 seconds**. It was not accepted for publication. One new
Sounds case completed its behavior checks but exited with Windows access
violation `0xC0000005` after emitting its result. Its fixture still used a
forced process exit. The test now uses orderly Qt teardown, explicitly
disposing retained dialogs, proxy-owned widgets and test-owned parentless
compatibility editors before QApplication destruction. It verifies those
objects are gone and emits JSON only after cleanup; every child must exit 0.
No `os._exit` remains. No production Settings Save/close crash was reproduced.

The other failure was the pre-existing window-preset subprocess, exit 1.
Its original stderr was not retained in the report, so the precise cause
cannot be honestly named. The same complete geometry/rollup/tray assertions
passed **3/3** when prefixed with the existing disposable native fixture.
The test now applies that fixture before application imports and preserves
child stdout/stderr on failure. It keeps every original assertion and normal
`app.quit()`. A direct run passed **1 test in 8.13 seconds**; no production
window logic changed. The existing quest timeout-disconnect warning was
observed, not suppressed or treated as a fatal error.

The final new test-file SHA-256 is
`b1d4964820964fb1f6d2c4b927de526eb9da7ddcb02f53ed6943c8eaf9067aec`.
All **9** picker/legacy cases passed in **54.10 seconds**, plus **10/10**
fresh repetitions of the formerly failing 100% Sounds case, all with normal
successful exits. Production Settings and the built/self-tested candidate
remain unchanged from the hashes above.

A fresh complete rerun started on 2026-10-06 at approximately **09:58 UTC**.
Its JUnit/log artifacts are
`SideKick/work/triggers-audit-126/full-suite-verified-126.xml` and
`full-suite-verified-126.log`. It completed with **1,867 passed, 57 failed,
2 skipped in 925.85 seconds**, not an accepted publication gate. All nine
new TTS cases passed. The failures required separating test environment and
fixture behavior from production changes:

- **55 UI installation/retention cases** failed under Windows account
  `codexsandboxoffline`, primarily with WinError 5 in the existing directory
  ancestor guard; one dependent collision assertion failed after the early
  denial. No UI-updater code was changed or guard bypassed. Running those
  modules with the normal Windows user, still using only disposable fake
  installations, passed **80 tests, 2 skipped in 22.78 seconds**.
- The Market synthetic signature-error assertion was overwritten by a real
  startup network response: the actual status said the source was unreachable.
  That fixture now calls the existing native isolation helper and disables
  startup gear-index refresh before constructing its fake application. Its
  signature handler and all original assertions remain real and unchanged;
  its explicit Refresh callbacks are still tested. Three fresh runs passed
  in **4.31, 4.26 and 4.75 seconds**. A transient incorrect fixture class-name
  reference was corrected before accepting these runs, and child-error output
  is now retained.
- The existing sharing-editor case timed out at 55 seconds in the suite.
  Independent repetitions also exposed a native access violation at tree
  clearing. The complete production CustomTriggerSettings class was unchanged
  from the baseline. Its test kept an active tree iterator/current item alive
  across imported tree rebuilds; releasing those traversal references after
  the selection assertion passed **10/10** fresh repetitions. The two editor
  tests passed in **9.92 seconds**, with original assertions, accessibility,
  timeout and strict exit 0 unchanged. The exact timeout mechanism itself
  was not reproduced, so it is not claimed as definitively explained.

Final sharing-test SHA-256:
`ba508abe056f451862e0ca03991ec3886e73e5eb14c048deb59dccaf3da519c6`.
Production Settings and the built candidate remain unchanged. These fixture
changes do not certify physical Windows/game behavior or remove the GINA
runtime limitations listed earlier.

The final complete host-user gate started on 2026-10-06 at approximately
**10:20 UTC**, again with disposable profiles and a fresh temporary root.
Its artifacts are `SideKick/work/triggers-audit-126/full-suite-host-126.xml`
and `full-suite-host-126.log`. The two platform-dependent skips concern
unavailable Windows symlink privileges and POSIX mode-bit semantics, not TTS.
The complete gate finished with **1,924 passed, 2 skipped, zero failures and
zero errors in 1,001.44 seconds**, process exit **0**. JUnit records all 1,926
cases. The new TTS matrix, sharing case, Market state and window-preset
assertions passed inside this full run, not only in isolated repetitions.
The portable candidate and production source hashes above were rechecked
unchanged after completion.

## Public release verification

[Companion 1.44.126](https://github.com/vantageupdates/vantage/releases/tag/v1.44.126)
was published as a stable, non-draft, non-prerelease release on
**2026-10-06 at 10:40:22 UTC** and verified as Companion Latest. The annotated
tag resolves to tested source commit
`5dcf0e0f73a2b2f37409cbf6e48d3e8b8fc1afc6`. Main and that tag were pushed
atomically without force or overwriting an existing version.

The release has exactly one asset, **Vantage.exe**, **75,940,262 bytes**.
GitHub's public SHA-256 digest matches the built/self-tested candidate:
`2768d4d33406a941f86d1f644c5ead896f73947e47d04ae4775d40310ec93e19`.
No previous candidate was published. The user installs this release through
Vantage's normal updater; publication did not replace their local executable
or modify EverQuest, UI skins, character INIs, game permissions or the
independent VantageUI release. This final evidence update is documentation
only; the tested source tag and published executable remain immutable.
