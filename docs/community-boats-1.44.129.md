# Companion 1.44.129: community boat timers

## Using the feature

Open Buffs / Spells and enable **Boat Schedules** from its settings. Select
**Green** or **Blue** above the boat rows; changing the selection immediately
clears the other server's rows. The app checks the community service every
minute while boat schedules are enabled. No Vantage account is required.

When the boat actually reaches your selected arrival point:

1. Choose **Sync arrival...** (also available in the boat settings menu).
2. Select the exact **Arrival point**, enter your public character name or
   nickname, and check **Publish this arrival and my public name**.
3. Press **Boat arrived · Sync** immediately when it arrives, not for a future
   NPC announcement or an unrelated shuttle. Read the resulting status.

The report server follows the active character independently of the viewed
server. If unknown, choose it manually. Unsupported active servers cannot
submit. Changing servers while the report dialog is open cancels the old
confirmation before any request is sent; reconfirm the actual arrival.

Rows show **Reported by**, the observation's age, and **unconfirmed** or
**corroborated**. Names are self-reported, not verified character ownership.
Corroboration means different device credentials agree, not verified people.
A large correction to a recent estimate remains pending until another device
confirms it. First reports and stale recalibrations can be accepted unconfirmed.
These are modeled estimates, not exact arrival guarantees.

The original seven routes, four boats, periods, and dock offsets are retained.
A dock arrival is converted to the original phase origin; freshness is measured
from the actual arrival, not the earlier origin. Local log observations remain
local and can override an older community observation. Missing community boats
use labelled **PigParse fallback** data. Cached countdowns continue during
outages and display an offline status; observations older than three modeled
trips are labelled stale. Public community observations expire after seven days.

## Privacy and limits

Reading estimates does not upload logs, buffs, character INIs, settings, or
other private parser state. Only a manually confirmed boat/dock/server/time/name
report is published. Enrollment occurs only when explicitly reporting, with
a private endpoint-specific local credential outside Device Sync exports.
Reports are never queued offline for later submission. The versioned Terms &
Privacy notice explains the optional service and retention, with per-report
confirmation as an additional gate.

The public service uses a strict, bounded JSON API, server UTC receipt times
adjusted only by a bounded monotonic click age, transactional replay protection,
hashed credentials/address keys, request/rate/count/expiry/database limits, and
SQLite secure deletion. Anonymous device enrollment cannot prevent coordinated
false reports or prove that two credentials represent different people.

## VPS operation

Dedicated endpoint: `https://vantage-boats.217-216-55-237.sslip.io`.
The stdlib Python service runs as unprivileged `vantage-boats`, with code in
`/opt/vantage-boats`, private SQLite state in `/var/lib/vantage-boats`, and a
loopback-only listener on `127.0.0.1:8790`. Its systemd unit enables startup and
restart-on-failure, a read-only filesystem outside state, no capabilities,
private temporary/device views, and bounded memory/tasks/open files.

Caddy handles HTTPS using only the dedicated `vantage-boats.caddy` import.
It overwrites the backend's trusted client-address header with the actual
connection address. No additional public port, firewall edit, other application
configuration, game process, installed Companion executable, skin, or INI was
modified. All pre-existing Caddy file hashes were verified unchanged.

Source/configuration: `locationserver/boat_server.py`,
`locationserver/vantage-boats.service`, and `locationserver/vantage-boats.caddy`.
Keep state private when backing up; it contains public report history and
private hashed identifiers. For a service-only code update, verify the new
source, preserve the database, and restart only `vantage-boats.service`.
For proxy changes, validate Caddy before a graceful reload. Do not change its
other imports. HTTPS/DNS and the VPS remain external availability dependencies;
restart-on-failure is not a guarantee against provider or host outages.

## Verification

The backend was verified under VPS Python 3.12.3 with isolated in-memory HTTP
enrollment, arrival submission, idempotent replay, Overthere's 1,975-second dock
offset, Green/Blue isolation, and secure deletion. No synthetic arrival entered
the public database. Public TLS-verified health and separate empty Green/Blue
snapshots succeeded from the Windows PC; unsupported Red returned HTTP 400.

Final focused verification: **217 passed**, exit 0, **24.65 seconds**. The
complete suite finished with **2,219 passed, 2 skipped**, **zero failures and
errors**, exit 0, in **1,124.48 seconds**. The two skips are Windows symlink
privilege and POSIX permission-bit checks. Two earlier full runs were stopped
to include the final visual corrections; only this completed frozen-source
run qualifies as the release gate.

The final one-file portable build used `vantage.spec`, Python **3.14.6**, and
PyInstaller **6.22.2**, completing successfully (build log **96.840 seconds**).
Its isolated hidden **--portable-self-test** exited **0** and wrote the
**1.44.129** marker. Windows file and product versions both read **1.44.129**.
Candidate **Vantage.exe** is **75,973,402 bytes**, SHA-256
`95ccd3a279747014316985efff9e1bb4ed3ba0c3012e37835f18445f4c40ab4a`.
All **23** changed production/version/service files were hash-checked frozen
through tests, build, and before publication. Earlier candidates are not used.

The actual Qt client also read both public HTTPS snapshots with an isolated
cache, without account enrollment or report uploads. This exposed a PySide6
header-name binding mismatch; the corrected string argument is covered by
real QNetworkReply callback tests that capture unexpected Qt exceptions.

Native Qt previews validated dark backgrounds, complete instructions, keyboard
focus/names, pinned action buttons, and maximum-length public names wrapping
without horizontal scrolling. The compact report dialog and its 150% text
variant remain readable; larger text scrolls inside the body. In an artificial
150%-text stress on a fixed narrow timer panel, two long route headings crowd
their countdown; native-size headings are intact and full names are available
through tooltips. These isolated previews do not certify in-game behavior.
