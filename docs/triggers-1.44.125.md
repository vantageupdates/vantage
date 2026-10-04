# Companion 1.44.125: Triggers

Triggers is an independent Quick Bar tool for the existing custom trigger
library. It uses the same parser, saved rules and timer engine as before;
automatic buff and spell tracking remains separate. This guide describes the
released 1.44.125 implementation. Final verification evidence is recorded below.

## Open and edit a trigger

1. Open **Quick Bar → Triggers**. The nearby order is **Buffs → Triggers →
   Smart Timers**. The older **Settings → Buffs & Triggers → Open Library**
   entry opens the same editor, not a second library.
2. Select a saved trigger or group, or choose **New trigger**. Library search
   finds names, groups, log patterns, sources, profiles and comments without
   changing saved order or the current draft. Clear search before dragging
   rows to reorder or move them between groups.
3. Enter **Name** and **Log text**, then choose the Basic action's display,
   overlay and **Delivery**. Friendly patterns support `*` and captured tokens;
   type `{` in a token-aware field for suggestions.
4. Use **Timer** for no timer, countdown, stopwatch or repeating behavior.
   Fixed durations use `H:MM:SS`: `00:03:00` means three minutes. A `{ts}`
   capture can supply a dynamic duration instead.
5. Enable **Advanced options** for regular expressions, repeat guards,
   character/zone restrictions, group overrides, clipboard output, early-ending
   patterns and Timer Ending/Timer Ended actions. Configured advanced options
   reveal themselves when a rule is selected. Hiding them does not clear their
   values.
6. Choose **Save** to apply the edited rule. **Clone** creates a disabled copy.
   Closing persists the library, not an unapplied form draft. Use **Save**
   before closing or sharing if those draft changes should be included.

The editor is nonmodal: other tools remain available. Reopening an already
visible editor keeps its draft; reopening a hidden editor reloads saved data.
The Triggers button indicates whether the editor is open, not whether a log is
currently active. Read the monitoring/profile/log status inside the editor.

### A narrow vertical Quick Bar

Adding Triggers does not stretch an existing saved **30 × 767** Quick Bar.
That physical rectangle stays exact while the complete logical column remains
**791 px** high and the authored action targets remain **24 px**. A visible
bottom scroll arrow exposes actions below the viewport. You can also use the
mouse wheel or **Page Up/Page Down**; **Tab** reveals the focused action instead
of leaving it clipped. For a labeled list, right-click the bar or press
**Shift+F10** or the **Menu** key and choose **All Quick Bar actions**.
Notifications and the horizontal Quick Bar presets keep their existing
behavior; the viewport change is scoped to the vertical launcher.

## Check matching without running actions

Choose **Show match check**, paste one sample EQ log line, and press **Check
match**. This checks the current unsaved draft and reports a match, no match,
invalid pattern or rejected safety filter. Results include named/numbered
captures, expanded configured text and a timer-duration preview when applicable.
The current detected character is used for `{c}`; the preview counter is `1`.

This check does not play Sound or Voice, start/change timers, write the
clipboard, show overlays, append runtime match history or save the draft.
**Hide match check** collapses the result without discarding it. Scope notes
are advisory: a sample match is not proof that live log monitoring is active.

**Test trigger now**, **Test** and **Test voice** are different: they deliberately
exercise notification/audio delivery and respect mute/volume. **Match Log**
shows bounded runtime history, with filtering, copying and CSV export; it is
not a permanent archive of all EQ log lines.

## Monitoring and audio are different controls

| Control | Effect |
| --- | --- |
| Monitoring Off | Pauses custom matching and new custom stage alerts. Existing timer deadlines remain; automatic spell/buff tracking is not disabled. Alerts skipped while paused are not a promise of later replay. |
| Trigger or group Off | Gates that rule/group's custom actions. Saved definitions and audio choices remain. |
| Delivery Off | Silences audio for that phase. Matching, timers and configured written/visual output remain enabled. |
| Mute this trigger | Silences that trigger's audio across its phases while preserving saved Sound/Voice choices, matching, timers and visual output. |
| Master Mute / zero Master Volume | Blocks audible output, including explicit audio tests. Written notifications remain available. |

The visible profile/log status reports the current application context; an
undetected profile or `NO LOGS` is not presented as successful live monitoring.
Editable basic-alert rules in the custom library follow custom monitoring;
the independent automatic buff/spell parser keeps its existing preferences.

## Import a pack as reviewed disabled copies

Use **Import Trigger Pack…** for GINA `.gtp`, `ShareData.xml`/XML,
GamTextTriggers `.gtt`, or a Vantage native `.json` pack. Use **Paste code or
link…** for a Vantage `VT1:` share.

The preview lists conversion warnings, skipped entries, invalid patterns,
unsupported settings and substituted/missing audio. Select only the rows you
want, then choose **Import selected**. Every imported trigger starts Off,
regardless of its state in the pack. Review its match, scope, actions and audio
before enabling it. Existing names become separate renamed copies, not
overwrites. Existing local group enabled states, colors and character
overrides win when a native pack uses the same group path.

Validated packaged WAVs are staged in memory. They are copied to the recipient
profile only after selected rows are accepted; cancelling leaves no imported
media. Outside sound paths and executable content are not loaded. A missing
GINA packaged WAV uses a gallery fallback with a warning; native missing audio
references are cleared and warned. Imported markup is shown as plain text.

## Share saved definitions, not live game actions

1. Select a saved trigger or group. Leave **Share scope → Saved selection only**
   for that trigger or that group and its descendants. With no selection,
   sharing asks you to choose one; it does not silently export the library.
   Choose **All saved triggers** explicitly to share the whole saved library.
2. Open **Share…** and choose a native JSON file, GINA compatibility `.gtp`,
   Vantage share code or Vantage share link.
3. Review the scope, size and warnings before continuing. Anyone with the
   resulting file/code/link can import its definitions, comments, selected
   group settings and included WAVs. Do not put secrets in trigger text or
   comments. No general application configuration, accounts or credentials
   are packaged.
4. Send or paste the complete output yourself. Vantage only saves a file or
   copies text; it does not send chat, upload a pack or control EverQuest.

Native JSON preserves Vantage's rule schema and selected group settings.
Only referenced WAVs already stored under the profile's `portable:` storage
are included. Original outside-disk audio paths are not exported. Missing,
denied or unshareable audio produces an explicit warning; it is not silently
removed to fit a code. Gallery sound identifiers are retained in native packs.
A custom overlay ID unavailable on the recipient is remapped to a local
default with a preview warning; overlay definitions are not automatically
created or shared.

### Codes, links and practical limits

`VT1:` codes are self-contained native JSON bytes compressed and encoded into
text. A share link carries the same code in its URL fragment. This is **not
GimaLink**, a short hosted pack ID, a GINA account integration or a GINA server
service. Copying or importing does not upload data or make a network request.
The browser handoff page does not automatically import/enable rules; use the
reviewed paste flow in Vantage.

Codes are bounded to **256 KiB decoded data** and **48 KiB encoded text**.
Those safety limits are not chat limits: ordinary definitions can already be
too long for an EverQuest `/tell`. The editor shows the exact copied length
and warns above 240 characters about game chat, and above 1,800 characters
about Discord messages. These are conservative guidance thresholds, not a
guarantee that a particular chat client accepts the text. Use Discord or a
pack file where appropriate. Nothing is truncated or split, and WAVs are not
dropped to make a share fit.

File packs allow up to **12 MiB** total; XML is bounded to **8 MiB**, each WAV
to **8 MiB**, total unpacked media/package data to **24 MiB**, and rules to
**1,500**. Native metadata also has bounded groups, depth and character
overrides. Invalid/encrypted/damaged archives, XML declarations, excessive
nesting and malformed native data fail safely rather than executing content.

## GINA compatibility boundaries

GINA import/export supports a known data-only XML/media subset: group
hierarchy, match text/pattern mode, display text, packaged WAV references,
speech text/interruption, timer mode/name/duration/restart/visibility,
Ending/Ended actions, early enders, counter reset, clipboard text and comments.
Unsupported settings are surfaced in import review. Millisecond durations
are converted to whole seconds with a warning when precision is lost.

- GINA uses .NET regular expressions; Vantage uses Python regular expressions.
  .NET-only syntax is not translated. Invalid patterns are warned, and even a
  compiling pattern needs a sample/live-behavior review before enabling.
- GINA can use Sound and Voice together. Vantage selects **one audio route per
  phase**. Legacy combined choices retain both values for editing, with Sound
  priority; simultaneous playback is not implemented.
- `.gtp` export requires an explicit compatibility/loss acknowledgement.
  Vantage-specific character/zone restrictions, activation state, match
  filters/repeat guards, overlay/color routing, group enabled/style/profile
  preferences, and per-phase Vantage voice/volume/pitch choices are not
  guaranteed portable. Inactive/muted choices and gallery sounds can also
  lose meaning; warnings explain the selected pack's losses. Prefer native
  JSON to retain Vantage-specific settings.
- The exported archive follows the XML fields and numeric WAV comment IDs
  covered by repository tests. There is no verified external GINA-app import,
  version/ID merge certification, complete GINA feature parity or GimaLink
  service claim. Review the `.gtp` inside GINA before enabling it.

## Verification evidence and release status

The focused editor/import/audio/transport run passed **83 tests in 38.81
seconds**. It covered saved selection/group/all/no-selection scope, GINA
acknowledgement cancellation without a file, native copy/paste, disabled
selected imports, cancellation without copied WAVs, local group collision
preservation, bounded malformed metadata/archives, staged Sound priority,
search/draft preservation, hidden advanced values and no-actions sample checks.

The final focused Quick Bar viewport run passed **13 tests in 77.52 seconds**.
It covered exact saved geometry, the complete logical column, unchanged target
sizes, scrolling/focus reachability and the all-actions route. This is focused
functional evidence, not the final complete-suite result.

The first complete-suite attempt finished with **1,911 passed, 2 skipped and
4 failed in 1,188.74 seconds**. The missing sample-result tooltip was fixed;
the tooltip-closure/editor gate then passed **3 tests in 27.54 seconds**.
Outdated catalog-order and minimum-aspect test expectations were corrected.
The history test's fixed 20 ms activation assumption was replaced by a bounded
`qWaitForWindowActive(1000)` check and event draining. The old full Rail tests
passed **5/5 on both baseline and current code**; forcing the window inactive
made all six focus checks false on both versions, so that check did not
reproduce a product regression. Final Rail repeats passed **3/3**, and the
combined follow-up gate passed **17 tests in 88.56 seconds**, preserving all
90 history entries and all six focus checks.

The rebuilt local single-file candidate is
`SideKick/work/triggers-125/portable-final/Vantage.exe`. The build completed in
**113.888 seconds**, and its portable self-test returned **Exit 0**. The
release marker, FileVersion and ProductVersion are all **1.44.125**. The
candidate is **75,935,843 bytes** with SHA-256
`d4eeea76f3dcd22e90f3f33b0b8dc4f8030804e607b45169970af31d9da064aa`.
Archive inspection confirmed the bundled `trigger_sharing`, `gina_import`,
`settings` and `quickbar` modules. This verifies the local candidate, not a
published download.

The second complete suite finished successfully on **2026-10-04**:
**1,915 passed, 2 skipped in 1,118.80 seconds (18:38)**, exit 0.
The full output and JUnit report are preserved under
`SideKick/work/triggers-125/full-suite-final-125.log` and
`full-suite-final-125.xml`. This includes all four corrected regression checks.

Reproduction uses a fresh writable temporary directory and disposable
profiles, with the tracked native audit fixture blocking live log discovery,
game capture, audio, services and external network:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_trigger_tool_editor.py tests/test_trigger_pack_compatibility.py tests/test_gina_import.py tests/test_trigger_editor_tree.py tests/test_trigger_audio_controls.py tests/test_trigger_sharing.py -q -p no:cacheprovider --basetemp <fresh-writable-test-directory>
```

Local rendered evidence includes Basic/Advanced, search, invalid/sample match
and selective import review captures at Qt scale factors **1.00, 1.25 and
1.50**, under `SideKick/work/triggers-125/captures-1`, `captures-1-25` and
`captures-1-5`. Additional focused screenshots/crops are under
`SideKick/work/triggers-tool/captures`. These are development artifacts, not
shipped pack data or proof of live game/audio behavior.

Vertical-column evidence adds **12 PNG captures** under
`SideKick/work/triggers-125/column-captures`: saved/short viewports at first/last
scroll positions and Qt scale factors 1.00, 1.25 and 1.50. The release owner
inspected the 1.00 and 1.50 captures. This author inspection does not replace
the independent review below.

The required independent image-only fresh-eyes review was attempted once but
blocked by the agent thread limit. Author inspection and captures do not
replace that gate. No live EverQuest, physical audio or screen-reader
certification is claimed.

**Public release verified on 2026-10-04:**
[Vantage Companion 1.44.125](https://github.com/vantageupdates/vantage/releases/tag/v1.44.125)
is stable, non-draft and GitHub Latest, published at 20:39:32 UTC. The tag
resolves to tested source commit `08993d4a64054f170366ac755fc1349d1196873c`.
The uploaded `Vantage.exe` is exactly 75,935,843 bytes; GitHub's SHA-256 digest
matches the tested local candidate's `d4eeea76f3dcd22e90f3f33b0b8dc4f8030804e607b45169970af31d9da064aa`.

The [public share page](https://vantageupdates.github.io/vantage/companion/share.html)
returned HTTP 200 with the reviewed paste instructions and no-account message.
Its deployed Git blob `d5cee0d45fadb90fa014b19de245cf0ebf28ab02` matches the
release source. The existing
[Companion publisher run](https://github.com/vantageupdates/vantage/actions/runs/37232922605)
completed successfully. These public checks did not send a private share code.

The running app and user's installed executable were not replaced. Install
the published update manually through Vantage. VantageUI's independent release
channel and skin files were not changed by this Companion release.
