"""
Colour palettes: an object colour plus a two-tone background gradient that
contrasts with it, grouped into named families the experiment engine can
compare (e.g. soft pastels vs. bold colours on a dark background).
"""
import colorsys
import random
from typing import Dict, Optional, Tuple

RGB = Tuple[float, float, float]

# hue ranges, saturation range, value range for the OBJECT colour,
# and whether the background should be dark or light.
PALETTE_FAMILIES = {
    'pastel': {'hues': [(0.0, 1.0)], 'sat': (0.25, 0.45), 'val': (0.85, 0.95), 'bg': 'dark'},
    'muted': {'hues': [(0.0, 1.0)], 'sat': (0.35, 0.55), 'val': (0.60, 0.75), 'bg': 'light'},
    'calm_blues': {'hues': [(0.50, 0.65)], 'sat': (0.30, 0.50), 'val': (0.70, 0.85), 'bg': 'dark'},
    'warm_earth': {'hues': [(0.03, 0.12)], 'sat': (0.40, 0.60), 'val': (0.65, 0.80), 'bg': 'dark'},
    'bold_pop': {'hues': [(0.0, 1.0)], 'sat': (0.70, 0.90), 'val': (0.85, 1.00), 'bg': 'dark'},
    'studio_white': {'hues': [(0.0, 1.0)], 'sat': (0.00, 0.06), 'val': (0.88, 0.96), 'bg': 'color'},
}


def luminance(rgb: RGB) -> float:
    """Relative luminance (WCAG) of an sRGB colour in 0-1."""
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rgb_to_hex(rgb: RGB) -> str:
    return '#' + ''.join(f'{max(0, min(255, round(c * 255))):02x}' for c in rgb)


class ColorGenerator:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def object_color(self, family: str) -> RGB:
        spec = PALETTE_FAMILIES[family]
        lo, hi = self.rng.choice(spec['hues'])
        hue = self.rng.uniform(lo, hi) % 1.0
        return colorsys.hsv_to_rgb(hue, self.rng.uniform(*spec['sat']), self.rng.uniform(*spec['val']))

    def background(self, obj: RGB, mode: str) -> Tuple[RGB, RGB]:
        """Return (top, bottom) gradient colours contrasting with the object."""
        h, s, v = colorsys.rgb_to_hsv(*obj)
        comp = (h + 0.5 + self.rng.uniform(-0.08, 0.08)) % 1.0
        if mode == 'dark':
            top = colorsys.hsv_to_rgb(comp, 0.35 + 0.2 * self.rng.random(), 0.22)
            bottom = colorsys.hsv_to_rgb(comp, 0.45, 0.07)
        elif mode == 'light':
            top = colorsys.hsv_to_rgb(comp, 0.10, 0.97)
            bottom = colorsys.hsv_to_rgb(comp, 0.18, 0.80)
        else:  # 'color': saturated backdrop for a white/grey object
            hue = self.rng.random()
            top = colorsys.hsv_to_rgb(hue, 0.55, 0.75)
            bottom = colorsys.hsv_to_rgb((hue + 0.06) % 1.0, 0.70, 0.35)
        return top, bottom

    def get_color_palette(self, family: Optional[str] = None) -> Dict:
        family = family or self.rng.choice(list(PALETTE_FAMILIES))
        obj = self.object_color(family)
        top, bottom = self.background(obj, PALETTE_FAMILIES[family]['bg'])
        # Make sure the object never melts into the background.
        mid = tuple((a + b) / 2 for a, b in zip(top, bottom))
        if contrast_ratio(obj, mid) < 2.0:
            top, bottom = self.background(obj, 'dark' if luminance(obj) > 0.3 else 'light')
        return {
            'family': family,
            'object_rgb': tuple(round(c, 4) for c in obj),
            'background_top': tuple(round(c, 4) for c in top),
            'background_bottom': tuple(round(c, 4) for c in bottom),
            'object_hex': rgb_to_hex(obj),
            'background_hex': rgb_to_hex(top),
        }
