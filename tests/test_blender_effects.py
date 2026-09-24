"""
Real Blender renders of every effect, a few tiny frames each.

Slow-ish (~30 s), so opt-in:  RUN_BLENDER_TESTS=1 python -m pytest tests/test_blender_effects.py
Needs Blender 4.2+ on PATH or the `bpy` pip module.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import config
from rendering.blender_runner import run_render

pytestmark = pytest.mark.skipif(os.environ.get('RUN_BLENDER_TESTS') != '1',
                                reason='set RUN_BLENDER_TESTS=1 to render with Blender')

LAMP = sorted((Path(config.BASE_DIR) / 'data' / 'stl_files').glob('*.stl'))[0]


@pytest.mark.parametrize('effect', [None, 'cross_section', 'explode'])
def test_effect_renders(tmp_path, effect):
    job = {
        'project_dir': str(config.BASE_DIR), 'stl_path': str(LAMP),
        'output_dir': str(tmp_path / 'raw'), 'width': 72, 'height': 128,
        'total_frames': 20, 'fps': 4, 'samples': 2, 'use_gpu': False,
        'object_color': [0.3, 0.6, 0.9], 'interior_color': [1.0, 0.4, 0.1],
        'material': 'glossy_plastic', 'motion': 'turntable', 'effect': effect,
    }
    run_render(job, tmp_path, config.BLENDER_BIN, config.BLENDER_MODE, 600)
    result = json.loads((tmp_path / 'result.json').read_text())
    frames = sorted((tmp_path / 'raw').glob('frame_*.png'))
    assert len(frames) == 20

    def coverage(path):
        alpha = Image.open(path).getchannel('A')
        return int((np.asarray(alpha) > 0).sum())

    first, middle = coverage(frames[0]), coverage(frames[10])
    assert first > 0
    if effect == 'explode':
        assert result['parts'] >= 2
    if effect == 'cross_section':
        assert middle < first * 0.95          # the front half is cut away mid-video
