"""
Per-platform titles, captions, hashtags and first comments.

Rules applied:
- YouTube: title <= 100 chars; the first 3 description hashtags show above
  the title, and YouTube ignores all of them if there are more than 15, so
  we use at most 5. `#shorts` goes in the description.
- TikTok: caption <= 2200 chars. 3-5 hashtags mixing niche and broad.
  Keywords in the caption matter because TikTok is used as a search engine.
- Instagram: caption <= 2200 chars, at most 5 hashtags. Keyword-rich first
  line for Instagram search.
"""
import random
import re
from typing import Dict, List, Optional

from content.formats import COMMON_HASHTAGS, FORMATS, NICHE_HASHTAGS, fill_placeholders

LIMITS = {
    'youtube_title': 100,
    'youtube_description': 5000,
    'youtube_tags_chars': 500,
    'tiktok_caption': 2200,
    'instagram_caption': 2200,
}
MAX_HASHTAGS = {'youtube': 5, 'tiktok': 5, 'instagram': 5}

DEFAULT_QUESTIONS = {
    'guess_the_object': 'What do you think this is? Guess in the comments.',
    'satisfying_spin': 'Which angle looks best to you?',
    'rate_the_design': 'Rate it 1-10 in the comments.',
    'specs_breakdown': 'How would you manufacture this?',
    'whats_inside': 'Did the inside look like you expected?',
    'how_many_parts': 'How many parts did you count?',
    'silhouette_guess': 'What did you think it was from the outline?',
}
# Caption opener when Claude isn't writing copy (the hook is already on screen).
DEFAULT_CAPTIONS = {
    'guess_the_object': 'A real part from an open CAD dataset, rendered in Blender.',
    'satisfying_spin': 'One full turn of a CAD model, rendered in Blender.',
    'rate_the_design': 'A real CAD design from an open dataset, rendered in Blender.',
    'specs_breakdown': '{triangles} triangles of real CAD geometry, rendered in Blender.',
    'whats_inside': 'A cutaway of a real CAD part, rendered in Blender.',
    'how_many_parts': 'A real multi-part CAD model, exploded and reassembled in Blender.',
    'silhouette_guess': 'A real CAD part, first as an outline, then fully rendered in Blender.',
}
BASE_KEYWORDS = ['cad model', '3d render', 'engineering design', 'blender render']


def _clean_tag(tag: str) -> Optional[str]:
    tag = '#' + re.sub(r'[^0-9A-Za-z_]', '', tag.lstrip('#'))
    return tag.lower() if len(tag) > 2 else None


def _dedupe(items: List[str]) -> List[str]:
    seen, out = set(), []
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(' ', 1)[0]
    return cut.rstrip(' ,.;:-') + '…'


def choose_hashtags(fmt: str, llm_tags: List[str], limit: int, rng: random.Random,
                    include_shorts: bool = False) -> List[str]:
    """Niche first (they reach the right people), one or two broad ones, rotated so
    every post doesn't carry the identical set."""
    niche = [t for t in (_clean_tag(x) for x in llm_tags) if t]
    niche += FORMATS[fmt]['hashtags']
    extra = NICHE_HASHTAGS[:]
    rng.shuffle(extra)
    broad = [t for t in COMMON_HASHTAGS if t != '#shorts']
    tags = _dedupe(niche[:3] + extra[:1] + broad[:1] + niche[3:] + extra[1:])
    tags = [t for t in tags if t != '#shorts']
    if include_shorts:
        return ['#shorts'] + tags[:limit - 1]
    return tags[:limit]


def build_metadata(fmt: str, hook: str, stats: Dict, llm: Optional[Dict] = None,
                   series_label: str = '', rng: Optional[random.Random] = None) -> Dict:
    rng = rng or random.Random()
    llm = llm or {}
    question = llm.get('question') or DEFAULT_QUESTIONS[fmt]
    caption_line = llm.get('caption') or fill_placeholders(DEFAULT_CAPTIONS[fmt], stats)
    keywords = _dedupe([k.lower() for k in llm.get('keywords', [])] + BASE_KEYWORDS)[:6]
    llm_tags = llm.get('hashtags', [])

    # ---- YouTube
    yt_title = llm.get('youtube_title') or fill_placeholders(hook, stats)
    if series_label and len(yt_title) + len(series_label) + 3 <= 90:
        yt_title = f'{yt_title} | {series_label}'
    yt_title = _truncate(yt_title, LIMITS['youtube_title'] - len(' #shorts')) + ' #shorts'
    yt_tags = choose_hashtags(fmt, llm_tags, MAX_HASHTAGS['youtube'], rng, include_shorts=True)
    yt_description = '\n\n'.join([
        f"{_truncate(caption_line, 1500)} {question}",
        f"Model facts: {stats.get('triangles', 0):,} triangles"
        + (f", {stats['genus']} through-holes" if stats.get('genus') else '')
        + '. Rendered in Blender from an open CAD dataset.',
        'A new CAD model every day. Subscribe so you don\'t miss the next one.',
        'Search terms: ' + ', '.join(keywords),
        ' '.join(yt_tags),
    ])
    tag_list, total = [], 0
    for tag in [k for k in keywords] + [t.lstrip('#') for t in yt_tags]:
        if total + len(tag) + 1 > LIMITS['youtube_tags_chars']:
            break
        tag_list.append(tag)
        total += len(tag) + 1

    # ---- TikTok: search-friendly caption, question, tags
    tt_tags = choose_hashtags(fmt, llm_tags, MAX_HASHTAGS['tiktok'], rng)
    # Trim the free text, never the question or hashtags at the end.
    tt_tail = f" {question} {' '.join(tt_tags)}"
    tiktok_caption = _truncate(caption_line, LIMITS['tiktok_caption'] - len(tt_tail)) + tt_tail

    # ---- Instagram: keyword-rich first line, then question, then tags
    ig_tags = choose_hashtags(fmt, llm_tags, MAX_HASHTAGS['instagram'], rng)
    ig_tail = '\n\n' + '\n\n'.join([question, 'Follow for a new CAD model every day.', ' '.join(ig_tags)])
    instagram_caption = _truncate(caption_line, LIMITS['instagram_caption'] - len(ig_tail)) + ig_tail

    return {
        'format': fmt,
        'hook': hook,
        'object_guess': llm.get('object_guess'),
        'guess_confidence': llm.get('guess_confidence'),
        'copy_source': 'claude' if llm else 'template',
        'youtube': {
            'title': yt_title,
            'description': _truncate(yt_description, LIMITS['youtube_description']),
            'tags': tag_list,
        },
        'tiktok': {'caption': tiktok_caption},
        'instagram': {'caption': instagram_caption},
        'first_comment': question,
        'keywords': keywords,
    }
