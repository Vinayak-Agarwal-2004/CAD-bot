import math
import random

import pytest
from PIL import Image

from content.experiments import ExperimentEngine
from content.formats import FORMATS, eligible_formats
from rendering.color_generator import accent_color
from rendering.effects import cut_amount, explode_amount, explode_offsets
from rendering.frame_compositor import FrameCompositor, OverlayPlan

CHUNKY_MULTIPART = {'aspect_ratio': 2.6, 'bodies': 4, 'triangles': 1000}
THIN_SINGLE = {'aspect_ratio': 4.8, 'bodies': 1, 'triangles': 1000}


@pytest.mark.parametrize('curve', [cut_amount, explode_amount])
@pytest.mark.parametrize('duration', [7.0, 10.0])
def test_effect_curves_close_before_the_loop(curve, duration):
    assert curve(0.0, duration) == 0.0
    assert curve(duration - 1 / 30, duration) == 0.0      # last frame matches the first
    assert curve(duration / 2, duration) == 1.0            # fully open mid-video
    samples = [curve(i / 30, duration) for i in range(int(duration * 30))]
    assert all(0.0 <= v <= 1.0 for v in samples)
    # opens once and closes once (no flicker)
    rises = sum(1 for a, b in zip(samples, samples[1:]) if a == 0.0 < b)
    assert rises == 1


def test_explode_offsets_are_even_and_vertical():
    centers = [(0, 0, 0.5), (0, 0, -0.5), (0.3, 0, 0), (0, 0, 0)]
    offsets = explode_offsets(centers, strength=0.5)
    for off in offsets:
        assert math.isclose(math.sqrt(sum(c * c for c in off)), 0.5, rel_tol=1e-6)
    assert offsets[0][2] > 0 and offsets[1][2] < 0          # top goes up, bottom goes down
    assert explode_offsets([]) == []


def test_eligibility():
    assert {'whats_inside', 'how_many_parts'} <= set(eligible_formats(CHUNKY_MULTIPART))
    thin = eligible_formats(THIN_SINGLE)
    assert 'whats_inside' not in thin and 'how_many_parts' not in thin
    assert 'guess_the_object' in thin and 'silhouette_guess' in thin
    assert eligible_formats(None) == list(FORMATS)


def test_engine_only_picks_suitable_formats():
    engine = ExperimentEngine([], exploration_rate=0.5, rng=random.Random(0))
    picks = {engine.choose_variant(stats=THIN_SINGLE)['format'] for _ in range(300)}
    assert picks == set(eligible_formats(THIN_SINGLE))
    assert {engine.choose_variant(stats=CHUNKY_MULTIPART)['format'] for _ in range(300)} == set(FORMATS)


def test_accent_colour_contrasts():
    assert accent_color((0.9, 0.9, 0.9))[0] > 0.9            # grey -> orange
    r, g, b = accent_color((0.2, 0.4, 0.9))                    # blue -> warm
    assert r > b


def test_silhouette_then_render(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    for i in range(40):
        img = Image.new('RGBA', (108, 192), (0, 0, 0, 0))
        img.paste((200, 30, 30, 255), (30, 60, 80, 140))
        img.save(raw / f'frame_{i + 1:04d}.png')
    comp = FrameCompositor(216, 384, 10)
    plan = OverlayPlan((0.1, 0.1, 0.15), (0.05, 0.05, 0.08), silhouette_seconds=2.0)
    frames = comp.compose(raw, tmp_path / 'out', plan)
    early = Image.open(frames[5]).getpixel((110, 200))
    late = Image.open(frames[-1]).getpixel((110, 200))
    assert early[0] > 230 and early[1] > 230                   # white outline on a dark background
    assert late[0] > 150 and late[1] < 80                      # real red render
    cover = comp.cover(raw / 'frame_0001.png', tmp_path / 'c.jpg', plan)
    assert Image.open(cover).getpixel((110, 200))[1] > 200     # cover keeps the outline, no spoiler
