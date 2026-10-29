# Companion 1.44.151 — group invitation triggers

The built-in trigger library now includes **Group invitation received** and
**Group invitation sent**, under **Vantage · Basics**. They identify the other
player in their Quickbar message and alert overlay:

- `Mindflux invited you to a group`
- `Group invitation sent to Wildflux`

These use the exact client system messages from `eqstr_us.txt`: string 12280,
`%1 invites you to join a group.`, and string 12273,
`You invite %1 to join your group.`. Matching is anchored to the complete system
line and rejects chat-wrapped invitations. No group action is performed.

Both triggers use the existing editor, test button, Sound/Text to speech/Off
delivery, individual mute, and overlay selection. Their default action is the
existing Warden bell with a one-second repeat guard. Turning audio off still
allows the written notification; turning the trigger off disables the match.

The built-in catalog migrates from version 5 to 6, adding missing trigger names
without overwriting customized or disabled same-name rows. Repeated loading
does not duplicate the entries. No separate notification route or audio engine
was introduced, and no game files, input or VantageUI changes are required.

Release validation is recorded separately after the complete suite, portable
build, self-test, packaged-code comparison and public download verification.
