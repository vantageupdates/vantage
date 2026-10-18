# Mobile Guild DKP — 1.44.138

The phone Guild tab now reads public OpenDKP records directly. It no longer
requires a PC-exported snapshot to show a character's balance and DKP history.
The permanent Home Screen app and the PC QR page share the same panel.

## Use it

1. Open the permanent [Vantage Companion app](https://vantageupdates.github.io/vantage/companion/#guild).
2. In **Guild**, enter the guild's OpenDKP name or HTTPS website, then choose
   **Open guild**. For Castle, enter `castle` or `https://castle.opendkp.com/`.
3. Use **Find character** and **Character** to select your toon. The search
   covers the downloaded roster, not only the first displayed records.
4. **Current balance** comes from OpenDKP's standings and includes its source
   date when provided. It is not the sum of the selected history period.
5. Choose a history period, search, record type, pool, or sort order. The
   selected history shows credited, spent and net amounts separately for each
   known pool. Expand a raid for attendance and individual ticks; choose
   **Check raid tick details** to retrieve the original raid detail.
6. Use **Refresh guild and history** to check for new awards. Loot with a
   verified item name includes a Project 1999 Wiki link.

Phone selection does not change the guild or character selected on the PC.
The optional **Imported PC snapshot** (or **PC-loaded guild snapshot and
controls** in the QR page) remains separate and clearly labelled.

## Internet and offline behavior

- Public OpenDKP browsing needs internet, but not the PC, its Wi-Fi, a new
  Vantage account, or an imported connection key.
- In the permanent HTTPS app, successful roster/balance and character/period
  requests are saved on that device. Opening it offline restores the saved
  selection and marks stale data. Load the needed character and period online
  first. Unvisited characters and periods are not pre-downloaded.
- Incomplete or failed refreshes do not replace the last complete saved copy.
  A storage failure is reported rather than claiming the data is ready offline.
- **Forget saved OpenDKP data** removes these public copies, not imported PC
  snapshots or reference catalogs. Browser data clearing can also remove them.
- Use the permanent HTTPS address for a Home Screen installation. A plain HTTP
  local PC address cannot provide the same service-worker offline guarantee.
- Live buffs, timers and EverQuest viewing still require the live PC session.

## Data and privacy boundaries

- Generic public OpenDKP guilds are supported. Restricted guild data may require
  signing in on the guild's own OpenDKP website; this panel does not import or
  store OpenDKP credentials and does not bypass guild access restrictions.
- Requests are read-only GETs to `https://api.opendkp.com`, with credentials
  omitted, no referrer, redirects rejected and bounded time/size/page limits.
- Pagination uses a consistent requested page size from the first page.
  Partial results and unavailable sources are reported. A display batch is not
  a data truncation: filtering searches all loaded records.
- Personal raid awards require attendance and matching award evidence; whole
  guild raid totals are not assigned to the selected character. Unknown values
  remain unknown. Different pools and unidentified balances are not added
  together. Mobile normalization is regression-checked against the desktop
  history implementation.
- Public saved data is scoped by guild, character and period. Superseded
  requests cannot overwrite the newly selected character. Clearing saved data
  invalidates outstanding writes across views.
- The private PC API keeps its authentication requirement. Only the exact
  shared static assets are made available to the QR page.

## Verification scope

Focused automated coverage includes desktop/mobile data parity, full roster and
pagination, invalid identities, response limits, cancellation, partial failures,
saved-copy preservation, selection races, scoped deletion, shared assets and
private API protection. Browser checks cover narrow layouts, keyboard details,
search beyond the first display batch and offline reopening. Release-specific
full-suite, portable build, public executable and Pages deployment evidence is
recorded separately after publication.

Desktop browser engines do not certify physical iPhone Home Screen behavior or
VoiceOver. No change to the installed user executable, game processes, game INI
files or VantageUI skin is part of this release.
