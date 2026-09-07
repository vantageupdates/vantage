"""Offline palette generator: ColorAide 8.12.1; prints JSON, never edits a skin.

Install ColorAide only in a tooling environment. The game/updater needs no
color library; ui_health_palette.py consumes the checked-in RGB samples.
Reference: https://facelessuser.github.io/coloraide/interpolation/
"""
import json

from coloraide import Color

STOPS = ((0, (239, 68, 68)), (20, (249, 115, 22)),
         (40, (245, 158, 11)), (60, (240, 220, 0)), (80, (0, 240, 0)))
THRESHOLDS = (*range(0, 61, 5), *range(62, 81, 2))


def palette():
    ramp = Color.interpolate([Color('srgb', [v / 255 for v in rgb])
                              for _, rgb in STOPS], space='oklab')
    anchors = dict(STOPS)
    samples = []
    for hp in THRESHOLDS:
        rgb = anchors.get(hp)
        if rgb is None:
            sample = ramp(hp / 80).convert('srgb').fit(method='oklch-chroma')
            rgb = tuple(round(v * 255) for v in sample.coords())
        samples.append({'hp': hp, 'rgb': list(rgb)})
    return {'schema': 1, 'generator': 'ColorAide 8.12.1',
            'interpolation': 'oklab', 'gamut': 'srgb', 'samples': samples}


if __name__ == '__main__':
    print(json.dumps(palette(), indent=2))
