import shutil
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from publishing.base import PublishError
from publishing.instagram import InstagramPublisher
from publishing.tiktok import MAX_SINGLE_CHUNK, TikTokPublisher, chunk_plan
from rendering.blender_runner import build_command
from rendering.frame_compositor import FrameCompositor, OverlayPlan
from rendering.video_compositor import VideoCompositor, pick_audio

W, H, FPS = 216, 384, 10


def _raw_frames(folder: Path, n: int):
    folder.mkdir(parents=True)
    for i in range(n):
        img = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
        img.paste((200, 80, 80, 255), (20 + i, 40, 80 + i, 150))
        img.save(folder / f'frame_{i + 1:04d}.png')


def test_blender_command_fails_loudly(tmp_path):
    cmd = build_command(tmp_path / 'job.json', 'blender', 'binary')
    assert '--python-exit-code' in cmd and cmd[cmd.index('--python-exit-code') + 1] == '1'
    assert cmd[-2:] == ['--', str(tmp_path / 'job.json')]
    assert build_command(tmp_path / 'job.json', 'blender', 'module')[-1] == str(tmp_path / 'job.json')


def test_compose_all_overlays(tmp_path):
    _raw_frames(tmp_path / 'raw', 40)
    comp = FrameCompositor(W, H, FPS)
    plan = OverlayPlan((0.2, 0.2, 0.3), (0.05, 0.05, 0.1), hook='Can you guess what this is?',
                       cta='Comment your guess', answer='Looks like: a hinge', stat_lines=['1,000 triangles'],
                       blur_reveal=True, text_style='pill', series_label='CAD Challenge #1', handle='@cadbot')
    frames = comp.compose(tmp_path / 'raw', tmp_path / 'out', plan)
    assert len(frames) == 40
    first, last = Image.open(frames[0]), Image.open(frames[-1])
    assert first.size == (W, H) and first.mode == 'RGB'
    assert first.tobytes() != last.tobytes()
    cover = comp.cover(tmp_path / 'raw' / 'frame_0001.png', tmp_path / 'cover.jpg', plan)
    assert Image.open(cover).size == (W, H)


def test_compose_clears_stale_frames(tmp_path):
    _raw_frames(tmp_path / 'raw', 5)
    (tmp_path / 'out').mkdir()
    Image.new('RGB', (W, H)).save(tmp_path / 'out' / 'frame_0099.png')
    FrameCompositor(W, H, FPS).compose(tmp_path / 'raw', tmp_path / 'out', OverlayPlan((0, 0, 0), (1, 1, 1)))
    assert len(list((tmp_path / 'out').glob('frame_*.png'))) == 5


def test_long_text_shrinks_to_fit_safe_zone():
    comp = FrameCompositor(1080, 1920, 30)
    block = comp.text_block('word ' * 40, 92, 'stroke')
    assert block.width <= comp.safe_right - comp.safe_left


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')
def test_encode_with_and_without_audio(tmp_path):
    _raw_frames(tmp_path / 'raw', 20)
    comp = FrameCompositor(W, H, FPS)
    comp.compose(tmp_path / 'raw', tmp_path / 'final', OverlayPlan((0, 0, 0), (1, 1, 1), hook='Hi'))
    audio = tmp_path / 'tone.wav'
    import subprocess
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    str(audio)], check=True)
    enc = VideoCompositor(fps=FPS)
    video = enc.encode(tmp_path / 'final', tmp_path / 'v.mp4', audio, preset='ultrafast')
    info = enc.probe(video)
    kinds = {s['codec_type'] for s in info['streams']}
    assert kinds == {'video', 'audio'}
    assert abs(float(info['format']['duration']) - 2.0) < 0.15   # audio padded to video length
    silent = enc.probe(enc.strip_audio(video, tmp_path / 's.mp4'))
    assert {s['codec_type'] for s in silent['streams']} == {'video'}


def test_pick_audio_avoids_recent(tmp_path):
    for name in ('a.mp3', 'b.mp3', 'notes.txt'):
        (tmp_path / name).write_bytes(b'x')
    assert pick_audio(tmp_path, ['a.mp3']).name == 'b.mp3'
    assert pick_audio(tmp_path / 'missing') is None


def test_tiktok_chunk_plan():
    assert chunk_plan(20_000_000) == (20_000_000, 1)
    size, count = chunk_plan(MAX_SINGLE_CHUNK + 5)
    assert size == 10 * 1024 * 1024 and count == (MAX_SINGLE_CHUNK + 5) // size


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


META = {'tiktok': {'caption': 'cap #cad'}, 'instagram': {'caption': 'cap'}, 'first_comment': 'q?'}


def test_tiktok_draft_flow(tmp_path):
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'0' * 1000)
    pub = TikTokPublisher('token', mode='draft', poll_interval=0)
    pub.http = mock.Mock()
    pub.http.post.side_effect = [
        FakeResponse({'data': {'publish_id': 'p1', 'upload_url': 'https://up'}, 'error': {'code': 'ok'}}),
        FakeResponse({'data': {'status': 'PROCESSING_UPLOAD'}, 'error': {'code': 'ok'}}),
        FakeResponse({'data': {'status': 'SEND_TO_USER_INBOX'}, 'error': {'code': 'ok'}}),
    ]
    pub.http.put.return_value = FakeResponse({}, 201)
    result = pub.publish(video, None, META)
    assert result.status == 'draft' and result.remote_id == 'p1'
    assert pub.http.post.call_args_list[0].args[0].endswith('/post/publish/inbox/video/init/')
    headers = pub.http.put.call_args.kwargs['headers']
    assert headers['Content-Range'] == 'bytes 0-999/1000'


def test_tiktok_direct_falls_back_to_allowed_privacy(tmp_path):
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'0' * 10)
    pub = TikTokPublisher('token', mode='direct', poll_interval=0)
    pub.http = mock.Mock()
    pub.http.post.side_effect = [
        FakeResponse({'data': {'privacy_level_options': ['SELF_ONLY']}, 'error': {'code': 'ok'}}),
        FakeResponse({'data': {'publish_id': 'p2', 'upload_url': 'https://up'}, 'error': {'code': 'ok'}}),
        FakeResponse({'data': {'status': 'PUBLISH_COMPLETE', 'publicaly_available_post_id': [7301]},
                      'error': {'code': 'ok'}}),
    ]
    pub.http.put.return_value = FakeResponse({}, 201)
    result = pub.publish(video, None, META)
    assert result.status == 'posted' and result.remote_id == '7301'
    init_payload = pub.http.post.call_args_list[1].kwargs['json']
    assert init_payload['post_info']['privacy_level'] == 'SELF_ONLY'


def test_tiktok_api_error_raises(tmp_path):
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'0')
    pub = TikTokPublisher('token')
    pub.http = mock.Mock()
    pub.http.post.return_value = FakeResponse({'error': {'code': 'access_token_invalid', 'message': 'bad'}}, 401)
    with pytest.raises(PublishError):
        pub.publish(video, None, META)


def test_instagram_resumable_flow(tmp_path):
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'0' * 50)
    pub = InstagramPublisher('123', 'tok', poll_interval=0)
    pub.http = mock.Mock()
    pub.http.post.side_effect = [
        FakeResponse({'id': 'c1', 'uri': 'https://rupload.facebook.com/ig-api-upload/v21.0/c1'}),
        FakeResponse({'success': True}),
        FakeResponse({'id': 'm1'}),
    ]
    pub.http.get.side_effect = [
        FakeResponse({'status_code': 'IN_PROGRESS'}),
        FakeResponse({'status_code': 'FINISHED'}),
        FakeResponse({'permalink': 'https://instagram.com/reel/x'}),
    ]
    result = pub.publish(video, None, META, cover_time_ms=1500)
    assert result.remote_id == 'm1' and result.url.endswith('/reel/x')
    create = pub.http.post.call_args_list[0].kwargs['data']
    assert create['media_type'] == 'REELS' and create['upload_type'] == 'resumable'
    assert create['thumb_offset'] == '1500'
    upload_headers = pub.http.post.call_args_list[1].kwargs['headers']
    assert upload_headers['file_size'] == '50' and upload_headers['Authorization'] == 'OAuth tok'


def test_instagram_metrics_parse_total_value():
    pub = InstagramPublisher('123', 'tok')
    pub.http = mock.Mock()
    pub.http.get.return_value = FakeResponse({'data': [
        {'name': 'views', 'total_value': {'value': 900}},
        {'name': 'likes', 'values': [{'value': 40}]},
        {'name': 'saved', 'total_value': {'value': 7}}]})
    m = pub.fetch_metrics(['m1'])['m1']
    assert (m.views, m.likes, m.saves) == (900, 40, 7)
