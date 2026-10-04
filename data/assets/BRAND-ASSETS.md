# Vantage Companion brand assets

`vantage-companion-logo-source.png` is the project owner's selected circular
gold-diamond concept, generated specifically for Vantage Companion with
OpenAI's built-in image-generation tool on September 8, 2026. It was not
copied from another application or icon set.

The source intentionally preserves the exact selected render. Run
`scripts/build_brand_assets.mjs` with Node.js and `sharp` to remove its baked
checkerboard, create the transparent 1,254 px master, produce the optimized
256 px app/PWA icon, and package the 16–256 px Windows ICO frames.

Active application surfaces must use `data/ui/icon-master.png`,
`data/ui/icon.png`, or `data/ui/icon.ico`. The GitHub Pages workflow publishes
those same PNG assets to the permanent Companion PWA.
