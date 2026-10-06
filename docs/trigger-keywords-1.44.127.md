# Companion 1.44.127: keyword triggers

Open **Quick Bar → Triggers → New trigger** and type any word or phrase in
**Log text**. **Text match → Contains text** is the default for new rules.
It searches anywhere in the log message, ignoring capitalization.

For example, `the tangrin` matches both `You have slain The Tangrin!` and
`The Tangrin begins to cast a spell.` The same works for other words or phrases;
you do not need the complete message or wildcards.

Choose the Basic action's **Delivery** (Sound/WAV, Text to speech, or Off),
configure the message, then **Save** and enable the trigger. Monitoring and
existing character/zone/group restrictions still apply. Contains text searches
literal substrings, not only whole words: choose a specific phrase to avoid
unwanted matches. It does not normalize spelling or punctuation. Empty text
cannot activate a Contains trigger.

Use **Show match check** with a sample log line to test the unsaved draft without
playing audio, starting a timer, or changing the clipboard. The editor preview,
runtime matching, and Match Log dry-run use the same text-matching scope.

## Existing and advanced rules

Saved rules without a matching scope keep **Entire log line**. Change a saved
keyword trigger to **Contains text** once and save it; no automatic broadening
of existing spell/casting or timer rules is performed.

In Contains mode, punctuation, `*`, and `{tokens}` are literal text. Choose
**Entire log line** for wildcards and captures such as `{Mob}`, `{c}`, or `{ts}`.
The advanced **Regular expression** option retains its existing matching
behavior and disables the plain-text scope selector until it is turned off.
Early-ending patterns keep their existing independent full-line/regex behavior.

## Save, clone, and share

Saving, reopening, and cloning retain the selected matching scope. Native JSON
packs and Vantage share codes/links also retain it. Packs containing Contains
rules require Companion **1.44.127 or newer** (native schema 2). Full-line-only
packs remain schema 1 for earlier readers. Imported rules still start disabled
for review. The `VT1:` transport prefix is unchanged.

GINA `.gtp` export remains a compatibility subset, not an exact engine clone.
Its warning identifies that Vantage's literal Contains scope is not guaranteed
there; use native JSON or a Vantage code/link to preserve this choice exactly.
See the [earlier compatibility audit](triggers-audit-1.44.126.md) for other
engine/import limitations; this change does not resolve target-owned timer
restart/early-end behavior or translate all .NET regex syntax.

## Release verification

The final complete host-user gate finished on **2026-10-06** with
**2,019 passed, 2 skipped, zero failures and zero errors in 1,002.87 seconds**,
process exit **0**. JUnit records all **2,021** cases (1,002.710 seconds in its
suite timing). The skips concern unavailable Windows symlink privileges and
POSIX mode-bit semantics. Artifacts are
`SideKick/work/trigger-keywords-127/full-suite-delivery.log` and
`full-suite-delivery.xml`. Profiles and temporary roots are disposable.

Focused checks cover actual runtime parsing, audio claims, dry-run/editor
parity, literal punctuation/empty input, old rows, precise built-ins, regex,
captures, fixed literal `{ts}` timers, independent early enders, native sharing,
and real keyboard/editor save/reopen/clone at 1.0× and 1.5× scales.
The keyword/audio/editor/share group passed **115 tests in 26.53 seconds**.
A combined trigger-and-Vitals parent-process check passed **313 tests in
153.48 seconds**; its artifact is `vitals-semantic-parent-load.xml`.

Earlier gates exposed fixture assumptions rather than production matching
failures. Mute persistence now checks its stable index 48 and the appended
scope independently. The Quick Bar fixture uses the existing synthetic
isolation to avoid live startup services while retaining every control check
and its 30-second timeout; its entire module passed **7 tests in 27.57 seconds**.
Calibration checks observe the correct overlay actor rather than an unrelated
control's later announcement. They retain all movement/keyboard/preview/cancel
checks and the initial 220 ms wait, followed by event processing bounded to one
second total for the asynchronous result. Production 180/220 ms timers are
unchanged. Ten isolated repetitions and the complete **80-test Vitals module**
passed before the combined/full gates. No forced callback or exit bypass was
used, and the final complete gate includes these corrected fixtures.

The single-file Windows candidate was built with `vantage.spec`, Python
**3.14.6** and PyInstaller **6.22.2**, build exit **0** (78.45 seconds). Its hidden
portable self-test exited **0**, imported the complete application graph and
wrote a **1.44.127** marker under an isolated profile.

Candidate **Vantage.exe** is **75,942,960 bytes** with SHA-256:
`118218f66349b6d7aa0a4a3ad12b93b9065a071ab0e551f758f76feb6f5f7a94`.
The fifteen affected production/version files remained frozen throughout the
final gates and were rechecked against their pre-test hashes. Settings source
SHA-256 is `1c5611a4acd58838c973e7456b0d6cebe4ed1c38da3ce5497698ceb2f874cc00`.
Native tests do not certify physical speech quality or live in-game behavior.
No installed executable, game process, UI skin, character INI, game permission,
or independent VantageUI release was changed.

## Public release verification

[Companion 1.44.127](https://github.com/vantageupdates/vantage/releases/tag/v1.44.127)
was published on **2026-10-06 at 22:50:01 UTC** and verified as stable,
non-draft, non-prerelease **Companion Latest**. The new annotated tag resolves
to tested source commit `22784d2832c40d04200b047428f5a5d5c7d9a022`.
Main and that tag were pushed atomically without force or version reuse.

Its single public asset is **Vantage.exe**, **75,942,960 bytes**. GitHub's
public digest is
`sha256:118218f66349b6d7aa0a4a3ad12b93b9065a071ab0e551f758f76feb6f5f7a94`,
matching the built/self-tested candidate exactly. The source tag and executable
remain immutable; this verification addition is documentation only.
Install through Vantage's normal updater. Publication did not replace the
user's local executable or change EverQuest, its files/permissions, or the
independent VantageUI release.
