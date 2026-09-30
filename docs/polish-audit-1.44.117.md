# Companion 1.44.117 polish audit

## Scope and method

This pass used an isolated temporary `VANTAGE_DATA_DIR`, Qt offscreen rendering,
and a loopback-only mobile fixture containing synthetic data. It did not read or
write the installed Companion profile, EverQuest files, or the installed
executable. The inventory covers every major Companion parser at normal,
narrow, and mini sizes plus the available dialogs; its manifest is
`work/polish-audit-1.44.117/inventory.json`.

The bounded release fixes are:

- keyboard exit from adjustable tables while retaining arrow-key cell
  navigation and the Shift+F10 column menu;
- stale mobile item responses, including late success, late error, close/reopen,
  and cross-kind dialog changes;
- an actionable Smart Timers empty state and a clear disabled Zones drop state;
- a truthful Market verification failure with a safe Refresh action; and
- a compact mobile EQ-style item sheet with complete common stats, data-backed
  flags/restrictions, linked effects/drops/quests, a secondary market reference,
  and a collapsed original-text fallback;
- generic own-message Smart Timer keyword actions, including safe Create timer;
- an early fading sound cue with exact spell/recipient speech at five seconds;
  and
- reversible Character UI layout copy with explicit source/target/backup
  preview and a truthful installed-versus-available VantageUI audit.

## Visual evidence

All mobile captures use the same synthetic enriched DTO. The baseline page was
loaded directly from `origin/main`; the candidate page was loaded from the
working tree.

- Fair baseline at 390 × 844:
  `work/polish-audit-1.44.117/mobile--fair-before--390x844--item-detail.png`
- Candidate at 390 × 844:
  `work/polish-audit-1.44.117/mobile--after--390x844--item-detail.png`
- Candidate at 319 × 700:
  `work/polish-audit-1.44.117/mobile--after--319x700--item-detail.png`
- Candidate at 319 × 700, scrolled to the links, source fallback, and market
  reference:
  `work/polish-audit-1.44.117/mobile--after--319x700--item-detail-scrolled.png`
- Candidate at 768 × 900:
  `work/polish-audit-1.44.117/mobile--after--768x900--item-detail.png`
- Smart Timers actionable empty state:
  `work/polish-audit-1.44.117/timers--normal--after-fix.png`
- Zones disabled drop selector placeholder:
  `work/polish-audit-1.44.117/zones--normal--after-fix.png`

The candidate has no horizontal overflow at 319, 390, or 768 CSS pixels. The
Close target is at least 44 pixels high. Labels precede values in semantic
`dl`/`dt`/`dd` reading order; visible item metadata is not conveyed by color
alone. Only the modal scrolls while it is open, avoiding competing page and
dialog scrollbars in browsers that support `:has()`; older browsers retain the
safe prior behavior. Original text is retained in a collapsed, named disclosure for fields
the parser does not recognize.

## Market verification evidence

The public P99 Planner metadata expected decompressed SQLite SHA-256
`ebd27df9aa29c41b0780e46a53a819433af093dae77a60459dadae6dc8372c3d`
and size 1,454,080 bytes. The downloaded database decompressed to SHA-256
`68e833fecf6458e4427e33f9e766ffd96a920ff22efc9d4d43bb9cba7598489d`
and size 1,908,736 bytes. A no-cache retry returned the same mismatch. Vantage
continues to reject that database; this pass does not weaken origin or digest
validation. The UI now states that item stats failed verification, keeps
PigParse prices available, and offers Refresh to retry both sources.

## Verification

- Focused feature suite: 6 passed.
- Mobile, responsive/table, Market, Timers, Zones, and spawn-timer regression
  suite: 193 passed in 147.55 seconds.
- The synthetic delayed-request browser flow was also exercised interactively:
  a slow Jade Mace request was closed, Golden Efreeti Boots loaded, and the late
  Jade response did not replace Golden.

Independent scoped reviews approved the mobile/polish, spell fading, Timer
keyword, and Character UI candidates. The final combined suite passed
**1,666 tests with 2 expected platform skips in 943.13 seconds**. The one-file
candidate and a fresh public download both passed the isolated portable
self-test and reported **1.44.117**. Public `Vantage.exe` is **75,835,529
bytes**, SHA-256
`4252139FFD85DE604FCFED2FA8D03A59B42D091C7BA225A045748076B617CE3F`.
Full release evidence is recorded in `design-qa.md`.

## Limits

The screenshots are synthetic layout evidence, not proof of external item or
market truth. This is not exhaustive accessibility certification. Physical
screen-reader output, physical-phone touch ergonomics, every live network
failure, every real EverQuest feed, and every configuration combination remain
outside this bounded pass. No broad ParserWindow header or mobile navigation
redesign was attempted because the fresh inventory did not demonstrate a
release-blocking crop in those surfaces.
