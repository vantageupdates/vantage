# Companion 1.44.137 — personal DKP history, Heal Chain overlay, and polish

## Where your DKP came from

Open **Guild DKP & More → Overview**, choose your guild and character, and use
**My DKP history**. The current guild-reported balance remains separate from the
filtered transaction summary. Raid awards, signed adjustments, and loot costs
show their date, source, amount and pool. Select a movement to see its explanation
and attended ticks. **Check raid details** reads the original public raid;
**Open item** is available when a canonical item name can be verified.

Search the entire loaded history, sort any column, drag column dividers, or filter
by period, movement type and pool. Refresh history retries unavailable sources.
Changing characters, guilds or periods invalidates old requests. Restoring a saved
character now loads its history without requiring another manual selection.

These are available records, not a reconstructed lifetime account balance.
Unknown dates are labeled and included; missing values remain unknown. Separate
or unidentified pools are never added together. The public personal transaction
endpoint can include linked alts: explicit other-character records are excluded.
Raid values require attended tick evidence; guild-wide award totals are not used.
The existing **My raids → Recorded attendance** still pools alt attendance with
its own shared-tick rules; it is not a combined balance.

## Heal Chain overlay

Use **Heal Chain → Overlay** for an independent, always-on-top live rail. It shares
the existing log tracker and remains visible when the main monitor is hidden.
The overlay shows per-target cast rails, current cast remaining time, interruption
state and the expected next marker/known cleric. The next call is a prediction
from observed order and configured spacing, not confirmation that a spell cast.
No game memory is read and no heal is cast automatically.

Drag the title or focus it and use arrow keys to move. Hide/Escape hides only the
overlay, not the parser. Position is remembered; opacity and position reset live
in Heal Chain Settings. Paused/off monitoring is stated explicitly.

Behavior was compared with EQTool/PigParse's independent event overlay and its
per-tank moving Complete Heal markers. The Vantage implementation reuses its own
rail/tracker, not original code or assets. Primary references:

- https://github.com/smasherprog/EqTool/blob/main/EQTool/UI/EventOverlay.xaml.cs
- https://github.com/smasherprog/EqTool/blob/main/EQTool/UI/EventOverlay.xaml

## Independent Market filters

**PigParse · prices** and **Gear · stats** each have their own search and
class/race/slot filters inside their tab. Price filters no longer change the
equipment results, or vice versa. Gear-only stat/effect/binding/era controls stay
with Gear. Each tab has its own Clear action; it does not clear the other tab,
server, watchlist or live-auction selection. Switching tabs preserves both sets
of filters. Server and source/refresh actions remain shared.
The footer reserves two styled text lines so ordinary refresh/offline messages
do not shift the results after a resize. Longer messages can still expand.

## Broader polish and verification scope

The Qt design and frontend UI standards skills guided legibility, consistent
controls, explicit state, keyboard access and source clarity. The separate local
Product Design audit skill could not run in full because its required
`critical-overrides.md` reference was absent; native Qt inspection was used.

A new isolated inventory captured 223 states across 17 parser panels, 40 dialog /
settings surfaces, tabs and normal/narrow/rolled states. Contact sheets and
selected full-size captures were inspected; this is not a claim that every
possible live-game workflow was exercised.

Evidence-backed corrections:

- Parser Diagnostics now uses the shared readable 80% minimum scaling floor.
- Log Searcher's rolling-day filter is accurately labeled **Past 24 hours**.
- Friends asks before discarding unpushed edits on server changes, reload or close.
  Cancel keeps the selected server, draft, cursor and focus. Failed pushes retain
  the draft, and restore confirmation warns when it will discard edits.

Focused tests cover provenance, alt identity, unknown amounts, zero awards,
conflicting pools, duplicate ticks, stale responses, empty/error/retry states,
selection persistence, canonical item links, search beyond initial rows, sorting,
readability, draft protection and overlay behavior. Native fixtures use disposable
profiles and disable live game capture, audio, log monitoring and external services.
Public OpenDKP schema checks were read-only and unauthenticated. No guild data,
VantageUI skin, user game files or installed Vantage executable was changed.

Release build, complete-suite totals, self-test and anonymous download verification
are recorded separately after publication. Physical in-game overlay/audio behavior
and screen-reader output are not asserted by offscreen tests.
