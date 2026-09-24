"""
Configuration for the CAD-bot shorts pipeline.

Every setting can be overridden with an environment variable of the same
name (or a line in a `.env` file at the project root).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass


def _env(name, default, cast=str):
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    if cast is bool:
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return cast(value)


# ---------------------------------------------------------------- paths
DATA_DIR = Path(_env('DATA_DIR', str(BASE_DIR / 'data')))
STL_DIR = DATA_DIR / 'stl_files'
AUDIO_DIR = DATA_DIR / 'audio-assets'
WORK_DIR = DATA_DIR / 'work'            # per-job scratch: raw + composited frames
OUTPUT_DIR = DATA_DIR / 'output_videos'
EXPORT_DIR = DATA_DIR / 'exports'       # ready-to-upload bundles (manual posting)
LOG_DIR = BASE_DIR / 'logs'
SECRETS_DIR = BASE_DIR / 'secrets'      # OAuth client files / tokens (git-ignored)
DB_PATH = Path(_env('DB_PATH', str(BASE_DIR / 'models.db')))


def ensure_dirs():
    for directory in (DATA_DIR, STL_DIR, AUDIO_DIR, WORK_DIR, OUTPUT_DIR,
                      EXPORT_DIR, LOG_DIR, SECRETS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- video
# 9:16 at 1080x1920 is the native format for Shorts, Reels and TikTok.
VIDEO_WIDTH = _env('VIDEO_WIDTH', 1080, int)
VIDEO_HEIGHT = _env('VIDEO_HEIGHT', 1920, int)
FPS = _env('FPS', 30, int)
# Short, seamlessly looping clips get re-watched, which all three platforms
# reward. The experiment engine tests these lengths (seconds) against each other.
VIDEO_DURATIONS = [float(x) for x in _env('VIDEO_DURATIONS', '7,10').split(',') if x.strip()]
VIDEO_CRF = _env('VIDEO_CRF', 18, int)

# Blender renders at RENDER_SCALE of the final size, then frames are scaled
# up to 1080x1920. 1.0 = full quality; 0.5 = 4x faster previews.
RENDER_SCALE = _env('RENDER_SCALE', 1.0, float)

# ---------------------------------------------------------------- rendering
BLENDER_BIN = _env('BLENDER_BIN', 'blender')
# 'auto' uses the Blender executable if present, else the `bpy` pip module.
BLENDER_MODE = _env('BLENDER_MODE', 'auto')
RENDER_ENGINE = _env('RENDER_ENGINE', 'CYCLES')  # CYCLES or BLENDER_EEVEE_NEXT
RENDER_SAMPLES = _env('RENDER_SAMPLES', 32, int)  # denoised, so 32 looks clean
USE_GPU = _env('USE_GPU', True, bool)
GPU_BACKEND = _env('GPU_BACKEND', 'AUTO')  # AUTO, OPTIX, CUDA, HIP, METAL, ONEAPI
RENDER_TIMEOUT = _env('RENDER_TIMEOUT', 3600, int)
MAX_RENDER_ATTEMPTS = _env('MAX_RENDER_ATTEMPTS', 2, int)
# Raw + composited PNG frames are ~0.5 GB per video; deleted after encoding unless set.
KEEP_FRAMES = _env('KEEP_FRAMES', False, bool)

CAMERA_ELEVATION_ANGLE = _env('CAMERA_ELEVATION_ANGLE', 22.0, float)
CAMERA_ELEVATION_SWING = _env('CAMERA_ELEVATION_SWING', 12.0, float)
# Empty space around the model's bounding sphere (1.0 = touching the frame edge).
CAMERA_FRAMING_MARGIN = _env('CAMERA_FRAMING_MARGIN', 1.1, float)
CAMERA_LENS_MM = _env('CAMERA_LENS_MM', 50.0, float)

# ---------------------------------------------------------------- model curation
# Tiny or trivial meshes (a plain cube, a washer) make boring videos.
MIN_TRIANGLES = _env('MIN_TRIANGLES', 300, int)
MAX_TRIANGLES = _env('MAX_TRIANGLES', 2_000_000, int)

# ---------------------------------------------------------------- overlays
FONT_PATH = _env('FONT_PATH', '')  # empty = auto-detect a bold sans font
BRAND_HANDLE = _env('BRAND_HANDLE', '')  # e.g. "@cadbot" watermark, optional
SERIES_NAME = _env('SERIES_NAME', 'CAD Challenge')

# ---------------------------------------------------------------- audio
AUDIO_VOLUME_DB = _env('AUDIO_VOLUME_DB', -14.0, float)  # platform loudness target
AUDIO_FADE_SECONDS = _env('AUDIO_FADE_SECONDS', 0.6, float)

# ---------------------------------------------------------------- captions / LLM
# Claude writes hooks, titles and captions from the rendered frame and mesh
# stats when an API key is available; otherwise templates are used.
USE_LLM = _env('USE_LLM', True, bool)
LLM_MODEL = _env('LLM_MODEL', 'claude-opus-5')

# ---------------------------------------------------------------- publishing
PLATFORMS = [p.strip() for p in _env('PLATFORMS', 'youtube,instagram,tiktok').split(',') if p.strip()]
TIMEZONE = _env('TIMEZONE', 'UTC')
# Posting often but not spammily is what grows new accounts. YouTube's API
# quota allows ~6 uploads/day on a default project.
POSTS_PER_DAY = {
    'youtube': _env('YOUTUBE_POSTS_PER_DAY', 2, int),
    'instagram': _env('INSTAGRAM_POSTS_PER_DAY', 1, int),
    'tiktok': _env('TIKTOK_POSTS_PER_DAY', 3, int),
}
# Candidate local posting hours. The experiment engine learns which
# slot actually performs best for your audience.
POSTING_HOURS = {
    'youtube': [12, 15, 18, 20],
    'instagram': [9, 12, 17, 19],
    'tiktok': [7, 12, 16, 19, 21],
}

# YouTube (Data API v3, OAuth "Desktop app" client)
YOUTUBE_CLIENT_SECRETS = Path(_env('YOUTUBE_CLIENT_SECRETS', str(SECRETS_DIR / 'youtube_client_secret.json')))
YOUTUBE_TOKEN_FILE = Path(_env('YOUTUBE_TOKEN_FILE', str(SECRETS_DIR / 'youtube_token.json')))
YOUTUBE_PRIVACY = _env('YOUTUBE_PRIVACY', 'public')
YOUTUBE_CATEGORY_ID = _env('YOUTUBE_CATEGORY_ID', '28')  # Science & Technology
YOUTUBE_PLAYLIST_ID = _env('YOUTUBE_PLAYLIST_ID', '')

# Instagram (Graph API, professional account)
INSTAGRAM_USER_ID = _env('INSTAGRAM_USER_ID', '')
INSTAGRAM_ACCESS_TOKEN = _env('INSTAGRAM_ACCESS_TOKEN', '')
GRAPH_API_VERSION = _env('GRAPH_API_VERSION', 'v21.0')
GRAPH_API_HOST = _env('GRAPH_API_HOST', 'graph.facebook.com')
# Optional: if videos are also synced to public hosting (S3, R2, a CDN),
# set the URL prefix and Instagram will fetch from there instead of an upload.
PUBLIC_MEDIA_BASE_URL = _env('PUBLIC_MEDIA_BASE_URL', '')

# TikTok (Content Posting API)
TIKTOK_ACCESS_TOKEN = _env('TIKTOK_ACCESS_TOKEN', '')
# 'draft' sends the video to your TikTok inbox so you can add a trending
# sound in-app before posting (usually the best choice for reach).
# 'direct' posts immediately (needs an audited app to post publicly).
TIKTOK_MODE = _env('TIKTOK_MODE', 'draft')
TIKTOK_PRIVACY = _env('TIKTOK_PRIVACY', 'PUBLIC_TO_EVERYONE')

# Post an engagement question as the first comment after upload.
POST_FIRST_COMMENT = _env('POST_FIRST_COMMENT', True, bool)

# ---------------------------------------------------------------- experiments
# Posts younger than this are too early to judge.
METRICS_MATURITY_HOURS = _env('METRICS_MATURITY_HOURS', 48, int)
# Share of videos that try a random variant instead of the current best.
EXPLORATION_RATE = _env('EXPLORATION_RATE', 0.2, float)
