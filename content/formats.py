"""
Video formats. Each is a different reason for a viewer to stop scrolling,
watch to the end, and comment, which is what all three algorithms reward.

Hooks must be true for every video they're used on: no invented statistics.
`ctas[i]` is the end-of-video call to action that answers `hooks[i]`.
Placeholders like {triangles} are filled from the mesh analysis.
"""
from typing import Dict, List

FORMATS: Dict[str, Dict] = {
    # Blurred silhouette that sharpens: people stay to see it and comment guesses.
    'guess_the_object': {
        'hooks': [
            'Can you guess what this is?',
            'Guess it before it un-blurs',
            'Engineers: what is this part?',
            'What would you use this for?',
        ],
        'ctas': ['Comment your guess', 'Comment your guess', 'Name the part below', 'Wrong answers only'],
        'motion': 'turntable',
        'blur_reveal': True,
        'show_answer': True,        # shows Claude's guess at the end, if confident
        'hashtags': ['#guessthat', '#engineering', '#cad', '#3dmodel', '#puzzle'],
    },
    # Pure loop: no text after the hook, built for re-watches.
    'satisfying_spin': {
        'hooks': [
            'Wait for the loop',
            'Oddly satisfying CAD',
            'Watch it one more time',
        ],
        'ctas': ['Did you watch it twice?', 'Follow for a new model every day', 'Follow for a new model every day'],
        'motion': 'turntable',
        'hook_seconds': 1.6,
        'hashtags': ['#satisfying', '#oddlysatisfying', '#3dmodeling', '#cad', '#loop'],
    },
    # Asking for a number is the lowest-effort comment there is.
    'rate_the_design': {
        'hooks': [
            'Rate this design 1-10',
            'Would you 3D print this?',
            'Good design or overbuilt?',
        ],
        'ctas': ['Drop your rating 1-10', 'Yes or no?', 'Tell me in the comments'],
        'motion': 'reveal',
        'hashtags': ['#productdesign', '#industrialdesign', '#3dprinting', '#cad', '#design'],
    },
    # Real numbers from the mesh give the nerdy crowd something to argue about.
    'specs_breakdown': {
        'hooks': [
            'This part is {triangles} triangles',
            'Every angle of this part',
            'How would you machine this?',
        ],
        'ctas': ['How would you make it?', 'CNC, casting or 3D print?', 'CNC, casting or 3D print?'],
        'motion': 'reveal',
        'stat_cards': True,
        'hashtags': ['#mechanicalengineering', '#cnc', '#machining', '#cad', '#engineering'],
    },
}

# Broad tags that go on everything, trimmed per platform.
COMMON_HASHTAGS = ['#shorts', '#3d', '#blender3d', '#engineering', '#cad']
NICHE_HASHTAGS = ['#solidworks', '#fusion360', '#3dprinting', '#mechanicalengineering',
                  '#productdesign', '#3dmodeling', '#render', '#industrialdesign']

TEXT_STYLES = ['stroke', 'pill']


def cta_for(fmt: str, hook_index) -> str:
    """CTA paired with a template hook; Claude-written hooks get the format's first CTA."""
    ctas = FORMATS[fmt]['ctas']
    return ctas[hook_index] if isinstance(hook_index, int) and hook_index < len(ctas) else ctas[0]


def fill_placeholders(text: str, stats: Dict) -> str:
    values = {
        'triangles': f"{stats.get('triangles', 0):,}",
        'vertices': f"{stats.get('vertices', 0):,}",
        'holes': stats.get('genus') or 0,
    }
    try:
        return text.format(**values)
    except (KeyError, IndexError):
        return text


def stat_lines(stats: Dict) -> List[str]:
    """Short factual lines for the stat cards overlay."""
    lines = [f"{stats['triangles']:,} triangles"]
    if stats.get('genus'):
        lines.append(f"{stats['genus']} through-hole{'s' if stats['genus'] != 1 else ''}")
    lines.append('Watertight: yes' if stats.get('watertight') else 'Watertight: no')
    if stats.get('bodies', 1) > 1:
        lines.append(f"{stats['bodies']} separate bodies")
    return lines
