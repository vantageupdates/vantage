# Companion 1.44.128: pointed red map arrow

The direction indicator now uses a bright red (`#ff4b4b`) dart with a sharp
tip, notched tail, and dark outline. It remains a native vector path, with
mitered rather than rounded joins. The map's position, travel-direction
calculation, inverse-zoom sizing, label layout, and preview behavior are
unchanged. This change does not modify the game skin or mobile live image.

## Verification

Focused map tests: **26 passed**, exit 0, **20.01 seconds**. Coverage includes
red rendering (including antialiased tip pixels), precise pointed/notched
geometry, four cardinal travel directions, constant device-space size at
0.1x/1x/4x zoom, marker position, map browsing, sources, and POI interactions.
A separate isolated Qt rendering preview was visually checked at native and
2x display sizes. It was not an in-game screenshot.

The initial render-test draft passed a null style option to Qt's native
paint function and crashed; the fixture now passes QStyleOptionGraphicsItem.
Its initial exact-color tip assertion also incorrectly ignored antialiasing;
the corrected test verifies red dominance there and exact red in the body.
Neither issue required a production behavior change.

The complete suite finished with **2,024 passed, 2 skipped**, **0 failures and
0 errors**, exit 0, in **1,137.35 seconds**. The two skips are Windows symlink
privilege and POSIX permission-bit checks. Native tests do not certify live
in-game behavior.

The `vantage.spec` single-file portable build completed with exit 0 in
**117.627 seconds**, using Python 3.14.6 and PyInstaller 6.22.2. Its isolated,
hidden portable self-test finished with exit 0 in **4.150 seconds** and wrote
the **1.44.128** version marker. Candidate **Vantage.exe** is **75,943,515
bytes**, with SHA-256
`1997e7112480dc0bc8672917b80c48b04dc64d74fda78a1dd0caafb05f12963a`.
All 14 changed production/version files were hash-checked unchanged after
build and before publication. The public-release proof will follow
publication without changing the source tag or executable.

No running Vantage, EverQuest, WinEQ, skin, character INI, or user permission
was changed. The user installs through Vantage's normal updater.
