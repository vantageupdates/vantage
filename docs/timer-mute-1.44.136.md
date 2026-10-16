# Timer audio and zone selection — Companion 1.44.136

## Mute timer audio from the timer window

Open **Timers** from the Quick Bar and select **Mute timers** directly below
the header. The button changes to **Timers muted** while enabled. Select it
again to restore timer audio. Keyboard users can focus the button and press
Space, or use **Ctrl+Shift+M** in a timer window.

- The switch applies to every open timer window and is remembered after restart.
- It silences all sounds and text-to-speech routed through Timers, including
  countdown, encounter, and death-loop alerts owned by that panel.
- Counters, timer completion, and visual notifications keep working.
- Other audio channels, the app's master volume, and each timer's saved sound,
  voice, pitch, and volume remain unchanged.
- Timer sound tests and replay obey the same mute switch.
- Already queued timer phrases are canceled and do not come back when unmuted.

Qt's native speech queue cannot remove individual phrases. Canceled timer
phrases therefore drain silently in their original positions without stopping
or replaying another notification. Older serial speech engines discard pending
timer phrases directly. This preserves unrelated speech at the cost of a
possible silent interval while a native canceled phrase drains.

## Select zones without enlarging the timer window

The zone list opens as a separate popup outside the timer window's clipped
surface. Long lists scroll, stay within the available screen, and reveal the
currently selected zone when reopened. Arrow keys, Home/End, Enter, Escape,
and pointer selection remain available. The same behavior applies to secondary
timer windows and rolled-up headers.

Timer size presets now compute their minimum height at the requested width,
so switching from a wider window to Tiny does not retain the wider window's
old height floor. Visible timer rows still determine the required space.

## Verification scope

Regression coverage exercises the shared audio gate, active and queued WAV/TTS,
cross-window controls, restart persistence, visual/countdown continuity,
keyboard interaction, and zone popup placement at normal and high-DPI scales.
Isolated native-window fixtures do not read live game logs or replace the
installed executable. Release evidence is recorded separately after the full
suite, portable build, self-test, and public artifact verification complete.
