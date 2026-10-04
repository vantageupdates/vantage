# Companion 1.44.118: trigger audio controls

## Changes

- Fixed custom trigger sound edits being saved only from the wrong settings
  section. Sounds now applies changed choices to the named trigger, even if
  the trigger list was reordered while the dialog was open.
- Clearing a trigger WAV sets that phase to Off instead of restoring the
  default WAV or falling through to legacy speech. Unedited stale gallery
  controls do not overwrite newer trigger audio choices.
- Added **Mute this trigger** in the trigger editor and Sounds. It silences
  basic, timer-ending, and timer-ended audio without disabling detection,
  timers, or configured visual alerts. Unmuting restores the configured sound
  and voice choices. Preview tests respect the mute and show its state.
- Running custom timers receive saved audio changes without resetting their
  deadlines or rendered target text. Their mute also blocks the general buff
  fading route, not only the trigger-specific ending and ended actions.
- Named the local auction route **Auctions / Market sale**. Both it and
  **OpenDKP auction** expose Off / Sound / Voice. Off is persistent and keeps
  written notifications available while blocking their audio.
- Added **Speak before fading**, independently of **Warn before fading**, in
  Buffs & Triggers settings. Default speech remains 5 seconds; users may choose
  1–600 seconds. Voice only speaks once per cast. The early beep precedes the
  voice when its threshold is higher; otherwise it is skipped. Existing WAV,
  Off, master mute, volume, and durable warning claims retain priority.

## Verification scope

Focused coverage includes all trigger phases and delivery modes, backward
compatible serialization, save/reopen, live parser refresh, active timers,
no legacy speech fallback, stale/reordered gallery data, auction Off, selected
fading boundaries, and a real attached spell row speaking once at a 15-second
stop. Screenshots from the isolated Qt harness are under
`work/trigger-audio-1.44.118/`. The controls retain the existing dark/gold style,
keyboard operation, and explicit accessible labels.

No VantageUI skin or independent updater code was changed. Live EverQuest,
WinEQ, installed Vantage executables, character INIs, and user profile data are
outside this implementation. These tests do not claim live in-game audio or
physical screen-reader verification.

## Final candidate and publication status

The final complete suite passed **1,686 tests**, with **2 expected platform
skips**, in **737.77 seconds**. Final source and the annotated `v1.44.118` tag
resolve to `28a0f28d9e59bdffe3bcaae3e2492c0d601ceb2b`; that commit is on public
`main`. The single-file build passed its isolated portable self-test with exit
0 and reported FileVersion/ProductVersion **1.44.118**. Frozen-code inspection
confirmed mute persistence, custom timer fading mute, the configurable spoken
stop, the editor, both Windows voice plugins, and all 20 built-in WAV files.

The candidate is **75,839,973 bytes**, SHA-256
`A9016029DA7F902BDE212E292983D1F2D700AB7F97DB41C0671477ADAA6E8C72`.
GitHub draft release **399654138** contains exactly one uploaded asset,
`Vantage.exe` (**599758278**), whose size and GitHub digest match that candidate.

**Not published:** the execution tool rejected the final combined publication,
public download, and public self-test command before running it. A subsequent
read-only check confirms `isDraft: true`, `isPrerelease: false`, and zero asset
downloads. Publishing the draft and validating a fresh public download remain
required; this is not yet an update available to installed users. The draft is
[available to the repository owner](https://github.com/vantageupdates/vantage/releases/tag/untagged-2f8e07c4b8950e889527).

The protected installed `D:\Vantage.exe` remained the user's 1.44.117 binary,
SHA-256 `4252139FFD85DE604FCFED2FA8D03A59B42D091C7BA225A045748076B617CE3F`.
The protected live profile retained SHA-256
`C418D49888A0E4B38FE0A34C9CA1075D57FD98F50E00981F2CF1C97B476BC0A5`.
Neither was replaced or modified by this task.
