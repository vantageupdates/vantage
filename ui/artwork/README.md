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

## Inventory stat sprites

`vantage-stat-icons.png` is the original 1448x1086 RGBA sprite sheet produced by
the built-in Image Gen tool for UI 1.44.69, not a client dependency. It has real
transparent alpha. `scripts/ui_inventory_details.cs` preserves that alpha and
the aspect ratio while packing twelve 12x12 crops into `VantageStatIcons.tga`.
Sprites are separated by four-pixel atlas gutters. Do not edit resistance or
coin artwork to regenerate these assets.

Final prompt: create one production game UI sprite atlas for Vantage UI,
matching tiny classic fantasy RPG resistance symbols, exactly twelve separate
icons in a four-column, three-row grid. Strong simple silhouettes, tiny
jewel-like painted 3D relief, top-left highlights, restrained rich colors,
readable at 12x12. Row 1: ruby heart (HP), blue teardrop crystal (MANA), silver
kite shield (AC), crossed steel swords (ATK). Row 2: golden four-point star
(EXP), bronze fist (STR), amber lightning (STA), pale green feather (AGI).
Row 3: silver hand (DEX), ivory owl (WIS), violet book (INT), gold crown (CHA).
Same optical size, centered, generous clear gutters; isolated objects without
tiles, discs, boxes, shadows, external glow, text, numbers or watermark.
Genuine transparent alpha, no simulated checkerboard; a sprite sheet, not a UI
mockup. Native-size preview and XML layout checks are not in-game validation.

`vantage-weight-icon.png` was generated separately with the built-in tool after
the user requested WEIGHT. Final prompt: one squat iron balance-weight with an
arched handle, broad trapezoid body, dark silver metal, bright top-left bevels
and a small muted bronze accent. Same tiny painted fantasy RPG style, clear
12-pixel silhouette, no inscription or frame, no external shadow or glow;
centered with generous margins and genuine transparent alpha. The packer adds
it at (2,50) in the expanded 64x64 atlas without altering the first twelve cells.

UI 1.44.70 adds `VantageCompactStatIcons.tga`: the same source artwork packed
directly at 10x10 for the 11-pixel Actions/group stat rows, not cropped from the
12-pixel sprites at runtime. Call `VantageInventoryDetails.CompactIcons` with
the same two source PNGs. Its 64x64 atlas uses (3+16*column,3+16*row) cells and
shared animations in `EQUI_Animations.xml`. The original inventory atlas and
all resistance sprites remain unchanged.
