# Vantage 1.44.136 release evidence

Published on 2026-10-16 at 23:07:23 UTC. Anonymous public verification completed
at 23:07:36 UTC with all three verification groups passing.

- Stable release: [v1.44.136](https://github.com/vantageupdates/vantage/releases/tag/v1.44.136)
- Tested source and exact tag target: `ff7b039ccb2709d33d4e5093290c74b8499e8b8e`
- Scope: [timer mute, zone popup, and timer size presets](timer-mute-1.44.136.md).

## Executable

| Check | Result |
| --- | --- |
| Final candidate | `final3/dist-candidate/Vantage.exe` |
| File / product version | `1.44.136` / `1.44.136` |
| Portable self-test | Passed, exit 0 |
| Candidate and public asset size | 76,017,457 bytes |
| Candidate and downloaded public SHA-256 | `778c99794d8833c0af34946df06adae0b1e81b0f97ed42267698ed828bc622a4` |
| GitHub digest, initial and final | `sha256:778c99794d8833c0af34946df06adae0b1e81b0f97ed42267698ed828bc622a4` |
| Release / asset IDs | `415449787` / `648891174` |

The public binary was downloaded independently. Its raw hash and size matched
the candidate, and the GitHub digest was checked separately. Latest release,
tag target, asset identity, and candidate hash were rechecked at completion.

## Final complete suite

The final frozen run collected **2,430 cases in 212 modules**: **2,428 passed,
2 skipped, 0 failures, 0 errors**, with no omissions or duplicate executions.
All 721 frozen source files were verified before and after the commit.

The platform-specific skips were:

- `tests/test_ui_skin_windows_permissions.py::test_real_posix_stage_keeps_private_mode_after_publication`
- `tests/test_ui_skin_versioned.py::test_symlink_collision_never_changes_outside_target`

An earlier run identified a stale 300-pixel assumption in a 130-pixel resize
test and a real Tiny-preset height-floor regression. The test now uses the
actual transform plus viewport containment; the timer preset computes its
floor at the requested width. A new repeated-shrink regression covers saved
rows. The complete suite was rerun after both corrections. Earlier candidates
were not published.

## Interaction and audio checks

- Detached zone popup: 85 supplied zones, primary and secondary windows,
  rolled header, screen edges, 100%/150% DPI, keyboard and pointer selection,
  scrolling, reopened selection visibility, and Escape.
- Mute button: shared state across timer windows, persistence through restart,
  keyboard/accessible checked state, compact layout, and enlarged text.
- Audio: timer WAV/TTS and previews/replay obey mute; counters and visual
  events continue; unrelated channels retain their audio. Serial and native
  queues cover reentrant mute/unmute and canceled phrases.
- Native speech cancellation retains silent queue entries where Qt cannot
  remove individual phrases, as described in the feature guide.

The interaction checks used isolated offscreen Qt fixtures and audio adapters;
they are not a claim of physical in-game or hardware speech-engine testing.
EverQuest, WinEQ, the installed Vantage executable, and VantageUI were not
modified or replaced.

Detailed evidence is retained under `work/timer-mute-136/final3`, including
`candidate-proof.json`, `verified/complete-suite-proof.json`, and
`public-proof.json`. This post-publication document does not modify the tagged
executable or frozen application sources.
