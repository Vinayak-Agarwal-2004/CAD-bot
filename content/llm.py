"""
Claude-written hooks, titles and captions.

Claude looks at a still of the model plus the mesh stats and returns
structured copy. Optional: without an API key (or on any error) the
pipeline falls back to templates in content/metadata.py.
"""
import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

COPY_SCHEMA = {
    'type': 'object',
    'properties': {
        'object_guess': {'type': 'string', 'description': 'What the object most likely is, 1-5 words.'},
        'guess_confidence': {'type': 'number', 'description': '0 to 1.'},
        'hook': {'type': 'string', 'description': 'On-screen hook, max 42 characters.'},
        'youtube_title': {'type': 'string', 'description': 'Max 70 characters, no hashtags.'},
        'caption': {'type': 'string', 'description': '1-2 sentences for TikTok/Instagram, no hashtags.'},
        'question': {'type': 'string', 'description': 'One question inviting comments.'},
        'keywords': {'type': 'array', 'items': {'type': 'string'},
                     'description': '3-6 search phrases people type, lowercase.'},
        'hashtags': {'type': 'array', 'items': {'type': 'string'},
                     'description': '3-5 niche hashtags including the #.'},
    },
    'required': ['object_guess', 'guess_confidence', 'hook', 'youtube_title', 'caption',
                 'question', 'keywords', 'hashtags'],
    'additionalProperties': False,
}

SYSTEM_PROMPT = """You write copy for short vertical videos (YouTube Shorts, Instagram Reels, TikTok) \
that show a 3D CAD model spinning on a turntable. The audience is engineers, makers, 3D-printing \
hobbyists and people who like satisfying visuals.

Write copy that makes someone stop scrolling and comment, while staying true to what the video \
shows. Specific beats generic ("this bracket has 6 holes" beats "cool part"). Don't invent facts, \
statistics or claims about the object's origin or use that you can't see. If you're unsure what \
the object is, say so through a question rather than stating a guess as fact. Plain language, no \
emojis in the hook, no ALL CAPS."""

FALLBACK_MODELS = {'claude-opus-5', 'claude-fable-5-1'}


def llm_available() -> bool:
    has_credentials = (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')
                       or os.environ.get('ANTHROPIC_PROFILE')
                       or (Path.home() / '.config' / 'anthropic').exists())  # `ant auth login`
    if not has_credentials:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def generate_copy(image_path: Path, stats: Dict, fmt: str, example_hooks: List[str],
                  model: str = 'claude-opus-5') -> Optional[Dict]:
    """Return a dict matching COPY_SCHEMA, or None if Claude is unavailable or declines."""
    if not llm_available():
        return None
    import anthropic

    image_b64 = base64.standard_b64encode(Path(image_path).read_bytes()).decode()
    facts = {k: stats.get(k) for k in ('triangles', 'watertight', 'genus', 'bodies', 'aspect_ratio')}
    prompt = (
        f'Video format: {fmt}\n'
        f'Example hooks for this format (match the style, do not copy): {json.dumps(example_hooks)}\n'
        f'Mesh facts (true, usable in copy): {json.dumps(facts)}\n'
        '"genus" is the number of through-holes/handles. The source is an open CAD dataset, '
        'so the part name is unknown - identify it from the image if you can.'
    )
    request = dict(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': COPY_SCHEMA}},
        messages=[{'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': image_b64}},
            {'type': 'text', 'text': prompt},
        ]}],
    )
    client = anthropic.Anthropic()
    try:
        if model in FALLBACK_MODELS:
            # If a safety classifier declines, the API retries on a fallback model.
            response = client.beta.messages.create(
                betas=['server-side-fallback-2026-07-01'], fallbacks='default', **request)
        else:
            response = client.messages.create(**request)
    except anthropic.RateLimitError:
        logger.warning('Claude rate-limited; using template copy')
        return None
    except anthropic.APIStatusError as exc:
        logger.warning('Claude API error %s; using template copy', exc.status_code)
        return None
    except anthropic.APIConnectionError:
        logger.warning('Could not reach the Claude API; using template copy')
        return None

    if response.stop_reason in ('refusal', 'max_tokens'):
        logger.warning('Claude stopped with %s; using template copy', response.stop_reason)
        return None
    text = next((b.text for b in response.content if b.type == 'text'), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning('Claude returned invalid JSON; using template copy')
        return None
