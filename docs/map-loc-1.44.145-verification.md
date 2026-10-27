# Companion 1.44.145 release verification

- Product commit: `5925cb46b1a107de73d7ed831be1c4eabf172a72`.
- Public stable release: [v1.44.145](https://github.com/vantageupdates/vantage/releases/tag/v1.44.145).
- Complete suite: 2,752 collected cases across 233 modules; 2,750 passed,
  two skipped, zero failures/errors, omissions or duplicate executions.
- The skips concern unavailable Windows symlink privileges and a POSIX
  mode-bit assertion that does not apply to Windows DACLs.
- All 750 frozen source/test inputs matched before and after the clean build.
- Clean single-file build from `vantage.spec` completed. The isolated portable
  self-test exited successfully and reported version 1.44.145.
- Packaged bytecode for twelve modules matched the frozen source, including
  map rendering, log reading, buff detection and the spell library. Four
  shared phone assets also matched byte-for-byte.
- Public release/tag target, executable size, GitHub SHA-256 digest and the
  independently hashed anonymous download all matched the tested candidate.
- Nine public Companion web assets matched the product commit, including the
  1.44.145 service worker. Refresh and Pages deployment workflows succeeded.

Executable: `Vantage.exe`, 76,141,075 bytes.

SHA-256: `cf9a889f7df476e648b2735e9cff540fdf0bc92084108ac9e25e3814314d2fc6`.

The buff regressions exercise real file writes, Windows watcher delivery,
application dispatch, and visible Symbol/Bravery rows with event-loop waits
during casting and after landing. The matching precision allowance preserves
the existing late cutoff. Native map diagnostics showed a painted LOC badge;
pixel tests additionally verify Mini, preview and viewport-edge rendering.

The default 1,000 ms buffer did not reproduce the installed-instance failure;
the confirmed rejection occurs with smaller settings. This release fixes that
case and improves log recovery, without claiming every possible live-session
cause was proven. Known/configured caster level still controls owned-buff
duration. The installed executable, running game and user profile were preserved.

This record completes the pending release checks listed in
[the candidate notes](map-loc-1.44.145.md).
