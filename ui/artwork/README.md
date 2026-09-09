# Vantage UI identity

`vantage-ui-approved.png` is the user-approved logo concept, generated with the
built-in Image Gen tool. It is a source asset, not an extra skin folder or a
client dependency. Do not ship this full-resolution reference inside `ui/skin`.

Final approved edit prompt: preserve the exact "Vantage UI" serif wordmark and
horizontal framed version layout; replace bright extruded gold and irregular
colored edges with smooth, restrained satin antique gold on neutral charcoal.
No extra marks, glow, tint or ornaments. The reference shows v1.44.67 only as an
example, not as the version of a later delivery.

`scripts/ui_brand_header.cs` packs the original approved wordmark crop into a
256x32 top-origin BGRA TGA. This is a mechanical crop/resize for the legacy EQ
texture format, not a substitute font. The final 202x20 header has a neutral
rounded background and a native-size, thin rounded frame for the version.
The version digits are **not** sampled from the reference. The native XML label
`HB_VantageVersionLabel` supplies `v<version>` and packaging checks it against
`ui/release.json`. The hotbar's 215x237 window and all game controls stay fixed.

Regenerate only into the canonical editing skin, then export with the normal
UI packaging script. Do not regenerate into an installed version folder.
