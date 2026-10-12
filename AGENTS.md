# Vantage release policy

For every completed user-facing Vantage change made in this repository:

1. Increment the patch version everywhere it is embedded. Never overwrite or reuse a published version or GitHub tag.
2. Run the complete test suite and add focused coverage for changed behavior.
3. Build the single-file portable Windows executable with `vantage.spec`.
4. Run the portable self-test against the candidate.
5. Preserve EverQuest, WinEQ, and any running Vantage instance. Do not replace the user's local executable as part of a release.
6. Publish the tested candidate as the `Vantage.exe` asset of a stable GitHub Release in `vantageupdates/vantage` using the matching `vX.Y.Z` tag.
7. The user installs published updates manually through Vantage's updater.
8. Verify the public Release, asset size, and GitHub SHA-256 digest against the tested candidate.

The user expects a published update after each completed Companion change,
not just a prepared draft. Complete the normal release flow when authorized
and permitted. If a tool policy blocks a step, do not bypass it through another
route; report exactly which publication or verification step remains incomplete.

The update repository is only for Vantage. Do not add unrelated organization, project, or account branding to the application or release metadata.

## Independent VantageUI release exception

The policy above continues to govern Companion changes and `Vantage.exe`.
A UI-only change is released independently and must not increment the Companion
version, build `Vantage.exe`, or publish a Companion `vX.Y.Z` release.

For a UI-only release:

1. Increment `ui/release.json` independently and keep schema 2 with
   `skin_folder` exactly `VantageUI-v<major.minor.patch>`.
2. Run focused UI-updater/package tests and the complete test suite.
3. Build and self-test only `VantageUI-Updater.exe` plus the deterministic UI
   manifest and payload. Candidate builds are allowed before publication approval.
4. Coordinate publication under a new, matching
   `vantage-ui-v<major.minor.patch>` stable tag; never overwrite or reuse a tag.
5. Verify the published UI assets and SHA-256 digests against the tested
   candidates. Do not publish `Vantage.exe` as part of the UI-only release.
6. Every delivered UI change must be exported to `ui/skin` and published in this
   independent update channel. Local installation must use the same verified
   published release, not an unmanaged local-only copy. Always use a new matching
   `VantageUI-v<version>` folder; preserve existing versions and Companion Latest.

## Complete UI downloads and vertical priority

The user requires the latest four published UI skins to be available in Git,
not only as updater executables. Maintain `ui/downloads` with four complete,
ready-to-copy versioned-folder ZIPs, a source-pinned catalog and installation
instructions. Derive them from the verified published manifests and payloads;
keep every XML/image byte, numeric folder name, historical badge and tag intact.
Do not include executables, character INIs, updater markers or shared registry
state in these manual bundles. Preserve older release history.

Every future UI delivery must publish matching vertical and horizontal skins
from the same UI base and make both available in `uifiles` through the updater
and a complete paired manual ZIP. Do not alternate one orientation per delivery.
The current pair is 1.44.109 (VBuff) / 1.44.110 (HBuff). The canonical numeric
folder contract requires distinct patch versions for the two presets; do not
rename them with V/H suffixes or invent counterparts under old published tags.
Maintain the paired download in Git alongside the latest-four catalog. Before
publishing a new pair, update the updater's paired-version targets, release both
fully tested candidates and verify both complete installations. Preserve existing
skins, INIs and socials. Historical releases remain unchanged.

Prioritize the vertical buff layout for future UI improvements. Highlight the
newest published vertical `(VBuff)` download and its exact `/loadskin` command;
keep the horizontal option available. This preference does not authorize
silently changing an existing published skin or the updater's selection logic.

Repackaging already published, byte-identical skins for this download catalog
does not change the UI or Companion version and must not replace existing
release assets/tags. Verify all bundled files against their pinned published
manifest, run archive/package regression tests, and verify the public Git
downloads. New skin or updater behavior still follows the full release policy
above, including new versions, complete tests, build and self-test.
