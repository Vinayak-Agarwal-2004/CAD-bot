"""
Color generation with eye-soothing palettes and contrasting backgrounds
"""
import colorsys
import random
from typing import Tuple

class ColorGenerator:
    # Eye-soothing color palettes
    SOOTHING_PALETTES = {
        'pastel': {
            'hue_ranges': [(0.0, 1.0)],
            'saturation': (0.25, 0.45),
            'value': (0.85, 0.95)
        },
        'muted': {
            'hue_ranges': [(0.0, 1.0)],
            'saturation': (0.35, 0.55),
            'value': (0.60, 0.75)
        },
        'calm_blues': {
            'hue_ranges': [(0.50, 0.65)],
            'saturation': (0.30, 0.50),
            'value': (0.70, 0.85)
        },
        'warm_earth': {
            'hue_ranges': [(0.05, 0.15), (0.85, 0.95)],
            'saturation': (0.40, 0.60),
            'value': (0.65, 0.80)
        },
        'soft_greens': {
            'hue_ranges': [(0.25, 0.45)],
            'saturation': (0.30, 0.50),
            'value': (0.70, 0.85)
        }
    }

    @staticmethod
    def generate_random_soothing_color() -> Tuple[float, float, float]:
        """Generate a random eye-soothing color in RGB (0-1 range)"""
        # Select random palette
        palette = random.choice(list(ColorGenerator.SOOTHING_PALETTES.values()))

        # Select hue from available ranges
        hue_range = random.choice(palette['hue_ranges'])
        hue = random.uniform(hue_range[0], hue_range[1])

        # Select saturation and value
        saturation = random.uniform(*palette['saturation'])
        value = random.uniform(*palette['value'])

        # Convert HSV to RGB
        rgb = colorsys.hsv_to_rgb(hue, saturation, value)
        return rgb

    @staticmethod
    def generate_contrasting_color(base_color: Tuple[float, float, float], 
                                   contrast_level: str = 'high') -> Tuple[float, float, float]:
        """
        Generate a contrasting background color

        Args:
            base_color: RGB tuple (0-1 range)
            contrast_level: 'high', 'medium', or 'low'

        Returns:
            RGB tuple (0-1 range)
        """
        # Convert to HSV
        h, s, v = colorsys.rgb_to_hsv(*base_color)

        # Adjust based on contrast level
        if contrast_level == 'high':
            # Complementary hue + opposite value
            new_h = (h + 0.5) % 1.0
            new_v = 0.95 if v < 0.5 else 0.15
            new_s = max(0.1, s * 0.5)  # Reduce saturation for background

        elif contrast_level == 'medium':
            # Split complementary
            new_h = (h + random.choice([0.4, 0.6])) % 1.0
            new_v = 0.85 if v < 0.5 else 0.25
            new_s = max(0.1, s * 0.6)

        else:  # low contrast
            # Analogous with value difference
            new_h = (h + random.uniform(-0.1, 0.1)) % 1.0
            new_v = 0.75 if v < 0.5 else 0.35
            new_s = max(0.1, s * 0.7)

        # Convert back to RGB
        rgb = colorsys.hsv_to_rgb(new_h, new_s, new_v)
        return rgb

    @staticmethod
    def rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
        """Convert RGB (0-1) to hex color code"""
        r, g, b = [int(c * 255) for c in rgb]
        return f'#{r:02x}{g:02x}{b:02x}'

    @staticmethod
    def get_color_palette() -> dict:
        """Generate a complete color palette for rendering"""
        object_color = ColorGenerator.generate_random_soothing_color()
        background_color = ColorGenerator.generate_contrasting_color(
            object_color, 
            contrast_level='high'
        )

        return {
            'object_rgb': object_color,
            'background_rgb': background_color,
            'object_hex': ColorGenerator.rgb_to_hex(object_color),
            'background_hex': ColorGenerator.rgb_to_hex(background_color)
        }
