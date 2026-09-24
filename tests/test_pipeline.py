"""
Pipeline orchestration with a fake renderer and fake publishers, plus the
Claude copywriter with a mocked client.
"""
import json
import shutil
import types
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

import config
import pipeline as pipeline_module
from content import llm
from database.db_manager import DatabaseManager
from publishing.base import Metrics, PublishResult, Publisher

MESH = Path(__file__).resolve().parents[1] / 'data' / 'stl_files'


class FakePublisher(Publisher):
    def __init__(self, name, status='posted'):
        self.name, self.status = name, status
        self.published, self.comments = [], []

    def configured(self):
        return True, ''

    def publish(self, video_path, cover_path, metadata, cover_time_ms=0):
        assert video_path.exists() and metadata[self.name]
        self.published.append(video_path)
        return PublishResult(self.status, f'{self.name}-{len(self.published)}', f'https://x/{len(self.published)}')

    def post_comment(self, remote_id, text):
        self.comments.append((remote_id, text))

    def fetch_metrics(self, remote_ids):
        return {r: Metrics(views=1000 * (i + 1), likes=10) for i, r in enumerate(remote_ids)}


def fake_render(job, job_dir, *_args):
    result = {'effect': job.get('effect')}
    if job.get('effect') == 'explode':
        result['parts'] = 3
    Path(job_dir).mkdir(parents=True, exist_ok=True)
    (Path(job_dir) / 'job.json').write_text(json.dumps(job))   # as the real runner does
    (Path(job_dir) / 'result.json').write_text(json.dumps(result))
    raw = Path(job['output_dir'])
    raw.mkdir(parents=True, exist_ok=True)
    for i in range(job['total_frames']):
        img = Image.new('RGBA', (job['width'], job['height']), (0, 0, 0, 0))
        img.paste((180, 90, 60, 255), (10 + i, 30, 60 + i, 120))
        img.save(raw / f'frame_{i + 1:04d}.png')
    return raw


@pytest.fixture
def env(tmp_path, monkeypatch):
    stl_dir = tmp_path / 'data' / 'stl_files'
    stl_dir.mkdir(parents=True)
    for i, src in enumerate(sorted(MESH.glob('*.stl'))):
        shutil.copy(src, stl_dir / src.name)
        if i == 0:   # a byte-identical copy in a subfolder must be flagged as a duplicate
            (stl_dir / 'copies').mkdir()
            shutil.copy(src, stl_dir / 'copies' / src.name)
    for name, value in {
        'STL_DIR': stl_dir, 'AUDIO_DIR': tmp_path / 'data' / 'audio', 'WORK_DIR': tmp_path / 'work',
        'OUTPUT_DIR': tmp_path / 'out', 'EXPORT_DIR': tmp_path / 'exports', 'LOG_DIR': tmp_path / 'logs',
        'SECRETS_DIR': tmp_path / 'secrets', 'DATA_DIR': tmp_path / 'data',
        'VIDEO_WIDTH': 108, 'VIDEO_HEIGHT': 192, 'FPS': 10, 'USE_LLM': False,
        'PLATFORMS': ['youtube', 'tiktok'], 'METRICS_MATURITY_HOURS': 0,
    }.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(pipeline_module, 'run_render', fake_render)
    publishers = {'youtube': FakePublisher('youtube'), 'tiktok': FakePublisher('tiktok', 'draft')}
    pipe = pipeline_module.Pipeline(DatabaseManager(tmp_path / 'db.sqlite'), publishers, seed=1)
    return pipe, publishers, tmp_path


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')
def test_full_cycle(env):
    pipe, publishers, tmp = env
    counts = pipe.scan()
    assert counts['duplicate'] == 1 and counts['accepted'] == 2
    assert pipe.scan()['new'] == 0            # rescans are idempotent

    produced = pipe.produce(limit=5, overrides={'duration': 7.0})
    assert len(produced) == 2
    video = pipe.db.get_video(produced[0])
    assert Path(video['video_path']).exists() and Path(video['cover_path']).exists()
    bundle = tmp / 'exports' / f'cadbot_{produced[0]:05d}'
    assert {'video.mp4', 'cover.jpg', 'youtube.txt', 'tiktok.txt', 'instagram.txt',
            'first_comment.txt', 'POSTING_CHECKLIST.txt'} <= {p.name for p in bundle.iterdir()}
    assert json.loads((bundle / 'metadata.json').read_text())['copy_source'] == 'template'
    assert not (tmp / 'work' / f'video_{produced[0]:05d}' / 'raw').exists()   # frames cleaned up
    assert pipe.produce(limit=5) == []        # nothing left to render

    assert pipe.schedule(days_ahead=30) == 4  # 2 videos x 2 platforms
    assert pipe.schedule(days_ahead=30) == 0
    with pipe.db.connect() as conn:           # make everything due now
        conn.execute("UPDATE posts SET scheduled_at = datetime('now', '-1 minute')")
    assert pipe.publish_due() == 4
    assert len(publishers['youtube'].comments) == 2   # first comment on real posts
    assert publishers['tiktok'].comments == []        # not on inbox drafts
    assert pipe.publish_due() == 0

    with pipe.db.connect() as conn:
        conn.execute("UPDATE posts SET posted_at = datetime('now', '-3 days')")
    assert pipe.collect_metrics() == 2        # drafts have no stats until linked
    rows = pipe.performance_rows()
    assert len(rows) == 2 and all('hour' in r for r in rows)
    assert pipe.engine().report()['format']


def test_render_failure_is_recorded_and_retried(env, monkeypatch):
    pipe, _, _ = env
    pipe.scan()

    def broken(*_a, **_k):
        raise RuntimeError('Blender exited with 1')
    monkeypatch.setattr(pipeline_module, 'run_render', broken)
    assert pipe.produce(limit=1) == []
    failed = pipe.db.get_models('failed')
    assert len(failed) == 1 and 'Blender' in failed[0]['last_error']
    assert pipe.db.get_statistics()['videos_failed'] == 1
    assert failed[0]['id'] in [m['id'] for m in pipe.db.get_render_queue(max_attempts=2)]


def _fake_anthropic(response):
    client = mock.Mock()
    client.beta.messages.create.return_value = response
    client.messages.create.return_value = response
    module = types.SimpleNamespace(
        Anthropic=mock.Mock(return_value=client),
        RateLimitError=type('RateLimitError', (Exception,), {}),
        APIStatusError=type('APIStatusError', (Exception,), {}),
        APIConnectionError=type('APIConnectionError', (Exception,), {}))
    return module, client


def test_claude_copy_request_and_parse(tmp_path, monkeypatch):
    image = tmp_path / 'still.jpg'
    Image.new('RGB', (20, 30)).save(image)
    copy = {'object_guess': 'hinge', 'guess_confidence': 0.8, 'hook': 'Guess this hinge part',
            'youtube_title': 't', 'caption': 'c', 'question': 'q?', 'keywords': ['k'], 'hashtags': ['#h']}
    response = types.SimpleNamespace(stop_reason='end_turn',
                                     content=[types.SimpleNamespace(type='text', text=json.dumps(copy))])
    module, client = _fake_anthropic(response)
    monkeypatch.setitem(__import__('sys').modules, 'anthropic', module)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')

    assert llm.generate_copy(image, {'triangles': 10}, 'guess_the_object', ['a'], 'claude-opus-5') == copy
    kwargs = client.beta.messages.create.call_args.kwargs
    assert kwargs['model'] == 'claude-opus-5' and kwargs['fallbacks'] == 'default'
    assert kwargs['output_config']['format']['schema'] == llm.COPY_SCHEMA
    assert kwargs['messages'][0]['content'][0]['type'] == 'image'

    llm.generate_copy(image, {}, 'guess_the_object', [], 'claude-sonnet-5')
    assert 'fallbacks' not in client.messages.create.call_args.kwargs

    response.stop_reason = 'refusal'
    assert llm.generate_copy(image, {}, 'guess_the_object', [], 'claude-opus-5') is None


def test_claude_skipped_without_credentials(monkeypatch, tmp_path):
    for var in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_PROFILE'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))
    assert llm.llm_available() is False
    assert llm.generate_copy(tmp_path / 'x.jpg', {}, 'guess_the_object', []) is None


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')
def test_effect_formats_pass_render_facts_through(env):
    pipe, _, tmp = env
    pipe.scan()
    lamp = next(m for m in pipe.db.get_models('pending') if m['stats']['bodies'] >= 2)
    video_id = pipe.produce_one(lamp, pipe.engine(), {'format': 'how_many_parts', 'duration': 7.0})
    video = pipe.db.get_video(video_id)
    job = json.loads((tmp / 'work' / f'video_{video_id:05d}' / 'job.json').read_text())
    assert job['effect'] == 'explode' and len(job['interior_color']) == 3
    assert video['metadata']['on_screen_answer'] == 'Answer: 3 parts'   # Blender's count, not trimesh's
    assert video['metadata']['render_facts']['parts'] == 3


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')
def test_unsuitable_forced_format_falls_back(env):
    pipe, _, _ = env
    pipe.scan()
    arc = next(m for m in pipe.db.get_models('pending') if m['stats']['aspect_ratio'] > 3.5)
    video_id = pipe.produce_one(arc, pipe.engine(), {'format': 'whats_inside', 'duration': 7.0})
    assert pipe.db.get_video(video_id)['variant']['format'] != 'whats_inside'
