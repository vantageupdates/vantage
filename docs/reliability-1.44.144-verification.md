# Companion 1.44.144 release verification

- Product commit: `038a8eb34793b5c3ee35d24066953bd8cc345971`.
- Public stable release: [v1.44.144](https://github.com/vantageupdates/vantage/releases/tag/v1.44.144).
- Complete suite: 2,720 collected cases across 231 modules; 2,718 passed,
  two skipped, zero failures/errors, omissions or duplicate executions.
- The two skips concern unavailable Windows symlink privileges and a POSIX
  mode-bit assertion that does not apply to Windows DACLs.
- All 747 frozen source/test inputs matched before and after the clean build.
- Portable single-file build from `vantage.spec` completed; isolated portable
  self-test exited successfully with version 1.44.144.
- Packaged bytecode for the changed map/log/DKP/Wiki modules matched source;
  shared phone DKP assets also matched byte-for-byte.
- Public release/tag target, downloaded executable size, GitHub digest and
  independently computed downloaded SHA-256 matched the tested candidate.
- Nine public Companion web assets matched the tested source, including the
  1.44.144 service worker. Pages deployment completed successfully.

Executable: `Vantage.exe`, 76,139,321 bytes.

SHA-256: `82eb5362d20af3b20aee45feb53e2cb17dea9d546abe938b877f0aebeb52d4e2`.

This verifies the released candidate and isolated regression fixtures. It does
not claim an interactive check inside the user's current EverQuest session.
The installed Vantage executable, running game and user profile were preserved.
