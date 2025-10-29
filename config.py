"""
Configuration file for STL to Video rendering pipeline
"""
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
STL_DIR = DATA_DIR / 'stl_files'
RENDERS_DIR = DATA_DIR / 'renders'
OUTPUT_DIR = DATA_DIR / 'output_videos'
DB_PATH = BASE_DIR / 'models.db'

# Ensure directories exist
for directory in [DATA_DIR, STL_DIR, RENDERS_DIR, OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Video settings
VIDEO_DURATION = 5  # seconds
FPS = 10  # frames per second
TOTAL_FRAMES = VIDEO_DURATION * FPS  # 750 frames
VIDEO_WIDTH = 640
VIDEO_HEIGHT = 740  # Portrait orientation for shorts

# Rendering settings
RENDER_SAMPLES = 128  # Blender render quality
RENDER_ENGINE = 'CYCLES'  # CYCLES or EEVEE
USE_GPU = True  # Use GPU acceleration if available

# Camera settings
CAMERA_ORBIT_AXIS = 'Z'  # Axis to orbit around
CAMERA_ELEVATION_ANGLE = 20  # degrees above horizon
CAMERA_DISTANCE_MULTIPLIER = 2.5  # Distance from object center

# Color settings
SATURATION_RANGE = (0.3, 0.7)  # Soft, eye-soothing colors
VALUE_RANGE = (0.6, 0.9)  # Brightness range
HUE_CATEGORIES = {
    'warm': [(0.0, 0.1), (0.9, 1.0)],  # Reds/oranges
    'cool': [(0.4, 0.7)],  # Blues/greens
    'neutral': [(0.1, 0.2), (0.7, 0.9)]  # Yellows/purples
}

# Lighting settings
HDRI_STRENGTH = 1.0
SUN_STRENGTH = 2.0
AMBIENT_STRENGTH = 0.5

AUDIO_DIR = DATA_DIR / 'audio-assets'
