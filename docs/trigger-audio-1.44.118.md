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
  deadlines or rendered target text.
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
