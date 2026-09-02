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
