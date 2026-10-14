# Vantage public landing page

Canonical public URL: https://vantageupdates.github.io/vantage/

The root landing page is plain static HTML. It preserves the Vantage dark/gold design, local Geist fonts, emblem, feature descriptions, setup instructions and creator/contact/support details. There is no build or server step. The existing `companion/` phone application and older published assets are independent and must be preserved.

## Landing files

- `index.html`: complete content and dated fallback downloads, functional without JavaScript.
- `landing-assets/site.css`: design tokens and responsive layout.
- `landing-assets/downloads.mjs`: live status, version check/retry and link updates.
- `landing-assets/releases.mjs`: public GitHub release selection and dated snapshot.
- `landing-assets/`: copied source emblem, social image and local font assets. Geist and Geist Mono use the included SIL Open Font License (`OFL.txt`).
- `landing-assets/screenshots/`: nine real gallery PNG captures, including one privacy-redacted in-game image and two pixel-exact details from it, with `provenance.json` (dimensions, SHA-256, source type, data type, date, version evidence and privacy processing).
- `website-tests/*.test.mjs`: focused Node tests; run `node --test website-tests/*.test.mjs`.

All local resources use relative paths so they work below `/vantage/`. Social and canonical URLs include that public base path. The page has no authentication, cookies, browser storage, analytics, external font requests or API server. Release checks use the public GitHub API with `credentials: omit` and no token.

## Real screenshots

The `#screenshots` gallery separates Companion from the optional VantageUI skin; `#vantageui-screenshots` links directly to the skin showcase. The hero uses the actual Companion map capture instead of an illustrative HTML buff preview. Every screenshot opens its published PNG in the same browser tab, without JavaScript, a carousel or a modal. The main VantageUI image links only to its privacy-redacted copy, never the unredacted attachment. Use browser Back to return. Images keep their full aspect ratio with `object-fit: contain`; below-fold images load lazily and all images reserve their intrinsic dimensions.

Six Companion images come from real Qt app windows with demo data: Quick Bar, West Freeport map, combat parser and Heal Chain (1.44.133 audit, October 13); Triggers (1.44.125 audit, October 4); and Boat Schedules (1.44.130 audit, October 12). Captions explicitly identify the demo data; boat countdowns and fight results are not live. These are not web reconstructions or generated artwork.

All three active VantageUI images come from the user’s October 14 actual gameplay attachment, with skin version 1.44.109 (VBuff) visible in the source. The main image shows the spellbook, inventory, bags and item card. Chat text is hidden through direct-pixel redaction, not AI image generation, and the caption explicitly identifies the privacy edit. Inventory/stats and four open containers are pixel-exact, unscaled crops from that same redacted image. Crop rectangles and checksums are documented in the manifest. Never place the unredacted source attachment in the website tree. These are versioned examples, not screenshots claimed to show the latest release. Do not use them to infer current download versions. Earlier image files may remain as unused published assets, but they are not linked by the active gallery.

The main VantageUI screenshot has a documented privacy redaction; its original dimensions and all pixels outside the defined chat rectangles are preserved. Its two detail crops preserve their selected pixels without enlargement, and the six Companion assets remain byte-for-byte identical to their reviewed sources. The manifest uses logical audit paths and attachment identifiers, never local user account paths. Before adding or replacing an image, inspect its actual pixels for private conversations, QR codes, connection tokens, IP addresses, credentials and personal file paths. Keep honest version/date/demo/privacy labels, meaningful action-oriented linked-image alt text and a useful adjacent caption. Add its published dimensions and checksum to the manifest, then run the screenshot tests alongside the existing release tests. A full-size link must never bypass a privacy redaction.

## Release confirmation

Snapshot confirmed against the unauthenticated public API on October 14, 2026 at 05:09 UTC: Companion `1.44.133` (`Vantage.exe`) and VantageUI `1.44.110` (`VantageUI-Updater.exe`). Both release pages and exact download URLs were verified. The full API listing contained 187 releases when migration was checked.

The client scans at most five pages of 100 releases within a total 12-second timeout. It compares three numeric version components independently for tags `vN.N.N` and `vantage-ui-vN.N.N`, excludes drafts/prereleases, requires uploaded assets with the exact product filename, and accepts only exact official GitHub HTTPS release/download URLs. Requests do not follow redirects. API response link headers never become fetch targets.

“Latest stable” is shown only after the complete listing has been checked successfully and both products have valid downloads. Network, rate limit, malformed response, missing product, timeout or pagination-limit failure retains the last confirmed pair and its date; retry remains available. A failed retry after success retains that session’s newer confirmed pair. No-JavaScript visitors always see dated “Last confirmed” labels and working release-note/download links.

To refresh the fallback later, confirm the public API, then update both `snapshot` in `releases.mjs` and the matching version, URL and date text in `index.html`. Update the static recent-improvements Companion release-note link too. Tests enforce consistency for the download versions and URLs. If release history reaches 500 entries, review the bounded scan rather than treating an incomplete result as latest.

## Verification before publishing

Run the focused tests, then serve the checkout as static files. Check desktop/mobile layouts, no horizontal overflow, keyboard skip-link/focus, reduced motion, a successful live check, denied API access, retry, timeout and disabled JavaScript. Verify every landing resource under `/vantage/` and confirm `git diff -- companion/` is empty before pushing only the website changes. Do not change application versions, executable assets, application source or GitHub releases for a landing-page update.
