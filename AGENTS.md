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
