"""Generate Vantage's original CC0 notification sound gallery.

The output contains no recordings or third-party samples.  Each short mono WAV
is synthesized from simple oscillators and a soft envelope so the release can
ship a useful, royalty-free gallery without a runtime audio dependency.
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import wave


RATE = 44_100
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "sounds"


SOUNDS = {
    "amber_chime.wav": ((0.00, 659.25, .28), (0.13, 880.00, .38)),
    "arcane_bloom.wav": ((0.00, 392.00, .24), (0.08, 523.25, .30), (0.18, 783.99, .42)),
    "camp_bell.wav": ((0.00, 440.00, .48), (0.00, 880.00, .34)),
    "copper_click.wav": ((0.00, 1046.50, .10), (0.055, 698.46, .13)),
    "dusk_echo.wav": ((0.00, 293.66, .28), (0.20, 440.00, .38)),
    "emerald_step.wav": ((0.00, 523.25, .16), (0.10, 659.25, .18), (0.20, 783.99, .25)),
    "frost_glint.wav": ((0.00, 1174.66, .12), (0.07, 1567.98, .24)),
    "gentle_knock.wav": ((0.00, 196.00, .12), (0.13, 220.00, .14)),
    "moon_drop.wav": ((0.00, 783.99, .20), (0.14, 523.25, .32)),
    "portal_ping.wav": ((0.00, 587.33, .18), (0.10, 987.77, .32)),
    "silver_rise.wav": ((0.00, 493.88, .16), (0.09, 659.25, .18), (0.18, 987.77, .28)),
    "sonar_soft.wav": ((0.00, 349.23, .34), (0.30, 349.23, .26)),
    "temple_note.wav": ((0.00, 261.63, .46), (0.00, 523.25, .30), (0.00, 784.88, .20)),
    "ward_fall.wav": ((0.00, 698.46, .18), (0.12, 523.25, .20), (0.24, 349.23, .30)),
}


def envelope(position: float, duration: float) -> float:
    attack = min(1.0, position / .012)
    remaining = max(0.0, duration - position)
    release = min(1.0, remaining / min(.10, duration * .45))
    return attack * release * math.exp(-2.1 * position / duration)


def render(notes: tuple[tuple[float, float, float], ...]) -> bytes:
    duration = max(start + length for start, _frequency, length in notes) + .035
    samples = []
    for frame in range(round(duration * RATE)):
        t = frame / RATE
        value = 0.0
        for start, frequency, length in notes:
            local = t - start
            if 0.0 <= local <= length:
                env = envelope(local, length)
                fundamental = math.sin(2 * math.pi * frequency * local)
                shimmer = .18 * math.sin(2 * math.pi * frequency * 2.01 * local)
                value += env * (fundamental + shimmer)
        value = max(-1.0, min(1.0, value * .28))
        samples.append(struct.pack("<h", round(value * 32767)))
    return b"".join(samples)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, notes in SOUNDS.items():
        with wave.open(str(OUTPUT / filename), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(RATE)
            stream.writeframes(render(notes))


if __name__ == "__main__":
    main()
