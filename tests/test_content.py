import random

import pytest

from content.experiments import DIMENSIONS, ExperimentEngine, hook_arms, relative_rewards
from content.formats import FORMATS, cta_for, fill_placeholders, stat_lines
from content.metadata import LIMITS, build_metadata
from rendering.color_generator import PALETTE_FAMILIES, ColorGenerator, contrast_ratio, rgb_to_hex

STATS = {'triangles': 48212, 'vertices': 24000, 'watertight': True, 'genus': 3, 'bodies': 1,
         'aspect_ratio': 2.1}


@pytest.mark.parametrize('family', list(PALETTE_FAMILIES))
def test_object_always_stands_out_from_background(family):
    for seed in range(200):
        p = ColorGenerator(seed).get_color_palette(family)
        mid = tuple((a + b) / 2 for a, b in zip(p['background_top'], p['background_bottom']))
        assert contrast_ratio(p['object_rgb'], mid) >= 1.8, (family, seed, p)


def test_rgb_to_hex_clamps():
    assert rgb_to_hex((1.2, 0.5, -0.1)) == '#ff8000'


def test_placeholders_and_stat_lines():
    assert fill_placeholders('This part is {triangles} triangles', STATS) == 'This part is 48,212 triangles'
    assert fill_placeholders('no {unknown} key', STATS) == 'no {unknown} key'
    lines = stat_lines(STATS)
    assert lines[0] == '48,212 triangles' and '3 through-holes' in lines


@pytest.mark.parametrize('fmt', list(FORMATS))
def test_metadata_respects_platform_limits(fmt):
    llm = {'object_guess': 'hinge', 'guess_confidence': 0.9, 'hook': 'x' * 60,
           'youtube_title': 'A very long title ' * 10, 'caption': 'caption ' * 400,
           'question': 'What is it?', 'keywords': ['hinge part', 'cad'], 'hashtags': ['#Hinge!', 'cad', '#x']}
    for copy in (None, llm):
        meta = build_metadata(fmt, FORMATS[fmt]['hooks'][0], STATS, copy, 'CAD Challenge #7', random.Random(1))
        yt = meta['youtube']
        assert len(yt['title']) <= LIMITS['youtube_title']
        assert yt['title'].endswith('#shorts')
        assert len(','.join(yt['tags'])) <= LIMITS['youtube_tags_chars']
        assert len(meta['tiktok']['caption']) <= LIMITS['tiktok_caption']
        assert len(meta['instagram']['caption']) <= LIMITS['instagram_caption']
        for caption in (meta['tiktok']['caption'], meta['instagram']['caption']):
            tags = [w for w in caption.split() if w.startswith('#')]
            assert 3 <= len(tags) <= 5 and len(set(tags)) == len(tags)
        desc_tags = [w for w in yt['description'].split() if w.startswith('#')]
        assert '#shorts' in desc_tags and len(desc_tags) <= 5
        assert meta['copy_source'] == ('claude' if copy else 'template')


def _rows(format_views):
    rows = []
    for fmt, views in format_views.items():
        for v in views:
            rows.append({'platform': 'youtube', 'views': v, 'hour': 12,
                         'variant': {'format': fmt, 'hook_index': 0, 'palette': 'pastel',
                                     'material': 'ceramic', 'text_style': 'pill', 'duration': 7.0}})
    return rows


def test_rewards_are_relative_to_platform_median():
    rows = relative_rewards(_rows({'a': [100, 100, 10000]}))
    assert sorted(round(r['reward'], 3) for r in rows)[:2] == [0.0, 0.0]


def test_engine_learns_the_winning_format():
    rows = _rows({'guess_the_object': [5000, 7000, 6000, 8000, 5500],
                  'satisfying_spin': [100, 120, 90, 150, 80],
                  'rate_the_design': [300, 250, 280, 310, 260],
                  'specs_breakdown': [200, 180, 220, 210, 190]})
    engine = ExperimentEngine(rows, exploration_rate=0.0, rng=random.Random(0))
    picks = [engine.choose_variant()['format'] for _ in range(200)]
    assert picks.count('guess_the_object') > 150
    assert engine.report()['format']['guess_the_object']['mean'] > 0


def test_engine_explores_when_there_is_no_data():
    engine = ExperimentEngine([], exploration_rate=0.0, rng=random.Random(0))
    picks = {engine.choose_variant()['format'] for _ in range(100)}
    assert picks == set(DIMENSIONS['format'])


def test_variant_shape_and_overrides():
    engine = ExperimentEngine([], rng=random.Random(3))
    v = engine.choose_variant({'format': 'rate_the_design', 'hook_index': 1})
    assert v['format'] == 'rate_the_design' and v['hook_index'] == 1
    assert v['motion'] == FORMATS['rate_the_design']['motion']
    assert set(DIMENSIONS) <= set(v)
    llm_picks = {ExperimentEngine([], 0.0, random.Random(s)).choose_variant(
        {'format': 'satisfying_spin'}, include_llm_hook=True)['hook_index'] for s in range(60)}
    assert 'llm' in llm_picks
    assert hook_arms('satisfying_spin', True)[-1] == 'satisfying_spin:llm'


def test_engine_learns_best_hour():
    rows = []
    for hour, views in ((9, 100), (19, 5000)):
        for _ in range(6):
            rows.append({'platform': 'tiktok', 'views': views, 'hour': hour, 'variant': {}})
    engine = ExperimentEngine(rows, exploration_rate=0.0, rng=random.Random(1))
    picks = [engine.choose_hour('tiktok', [9, 19]) for _ in range(100)]
    assert picks.count(19) > 90


@pytest.mark.parametrize('fmt', list(FORMATS))
def test_every_hook_has_a_matching_cta(fmt):
    assert len(FORMATS[fmt]['ctas']) == len(FORMATS[fmt]['hooks'])
    assert cta_for(fmt, 'llm') == FORMATS[fmt]['ctas'][0]
    assert cta_for('rate_the_design', 0) == 'Drop your rating 1-10'


def test_template_caption_does_not_repeat_the_question():
    meta = build_metadata('guess_the_object', 'Can you guess what this is?', STATS, None, '', random.Random(0))
    assert meta['tiktok']['caption'].count('?') == 1
    assert '48,212 triangles' in build_metadata('specs_breakdown', 'x', STATS)['instagram']['caption']
