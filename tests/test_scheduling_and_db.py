import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from database.db_manager import DatabaseManager
from publishing.scheduler import local_hour, next_slot

NOW = datetime(2026, 3, 2, 10, 0)  # naive UTC


def fill(n, per_day, hours, tz='Europe/London'):
    taken = []
    for _ in range(n):
        taken.append(next_slot(taken, per_day, hours, tz, choose_hour=lambda free: free[0],
                               now_utc=NOW, rng=random.Random(0)))
    return taken


def test_slots_respect_daily_cap_hours_and_future():
    hours = [12, 18, 21]
    slots = fill(10, 2, hours)
    zone = ZoneInfo('Europe/London')
    per_day = {}
    for s in slots:
        local = s.replace(tzinfo=ZoneInfo('UTC')).astimezone(zone)
        assert local.hour in hours
        assert s > NOW
        per_day[local.date()] = per_day.get(local.date(), 0) + 1
    assert max(per_day.values()) <= 2
    assert len(set(slots)) == len(slots)


def test_skips_hours_already_past_today():
    slot = next_slot([], 3, [9, 11, 20], 'UTC', lambda free: free[0], now_utc=NOW)
    assert slot.hour == 11 and slot.date() == NOW.date()


def test_full_calendar_raises():
    taken = [NOW + timedelta(days=d, hours=2) for d in range(3)]
    with pytest.raises(RuntimeError):
        next_slot(taken, 1, [12], 'UTC', lambda f: f[0], now_utc=NOW, horizon_days=3)


def test_local_hour():
    assert local_hour(datetime(2026, 7, 1, 12, 0), 'America/New_York') == 8


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(tmp_path / 'test.db')


def _stl(path, content=b'solid x\nendsolid x\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_same_filename_in_different_folders_are_separate_models(db, tmp_path):
    a = _stl(tmp_path / 'a' / 'part.stl', b'one')
    b = _stl(tmp_path / 'b' / 'part.stl', b'two')
    assert db.add_model(a, 'h1') != db.add_model(b, 'h2')
    assert db.add_model(a, 'h1') == db.get_model_by_path(a)['id']


def test_duplicate_content_detected(db, tmp_path):
    first = db.add_model(_stl(tmp_path / 'x.stl'), 'same')
    second = db.add_model(_stl(tmp_path / 'y.stl'), 'same')
    assert db.find_duplicate(second, 'same') == first
    assert db.find_duplicate(first, 'same') is None


def test_render_queue_orders_by_score_and_retries_failures(db, tmp_path):
    ids = [db.add_model(_stl(tmp_path / f'{i}.stl', bytes([i])), str(i)) for i in range(3)]
    for model_id, score in zip(ids, (10, 90, 50)):
        db.set_model_analysis(model_id, {'triangles': 1}, score, 'pending')
    assert [m['id'] for m in db.get_render_queue()] == [ids[1], ids[2], ids[0]]
    db.set_model_status(ids[1], 'failed', 'boom', count_attempt=True)
    assert ids[1] in [m['id'] for m in db.get_render_queue(max_attempts=2)]
    db.set_model_status(ids[1], 'failed', 'boom', count_attempt=True)
    assert ids[1] not in [m['id'] for m in db.get_render_queue(max_attempts=2)]
    assert len(db.get_render_queue(limit=1)) == 1


def test_post_lifecycle_and_performance_rows(db, tmp_path):
    model = db.add_model(_stl(tmp_path / 'm.stl'), 'm')
    video = db.create_video(model, {'format': 'rate_the_design'})
    db.finish_video(video, tmp_path / 'v.mp4', None, {'youtube': {}}, 12.0)
    assert db.get_videos(status='ready', unscheduled_for='youtube')[0]['id'] == video

    post = db.schedule_post(video, 'youtube', datetime(2020, 1, 1, 12))
    assert db.schedule_post(video, 'youtube', datetime(2020, 1, 2, 12)) is None  # once per platform
    assert not db.get_videos(status='ready', unscheduled_for='youtube')
    assert [p['id'] for p in db.get_due_posts()] == [post]

    db.mark_post(post, 'posted', remote_id='abc', url='https://youtube.com/shorts/abc')
    assert not db.get_due_posts()
    with db.connect() as conn:  # pretend it went out three days ago
        conn.execute("UPDATE posts SET posted_at = datetime('now', '-3 days')")
    db.add_metrics(post, views=10)
    db.add_metrics(post, views=250, likes=12)
    rows = db.get_performance_rows(min_age_hours=48)
    assert len(rows) == 1 and rows[0]['views'] == 250
    assert rows[0]['variant']['format'] == 'rate_the_design'


def test_failed_posts_retry_until_limit(db, tmp_path):
    model = db.add_model(_stl(tmp_path / 'm.stl'), 'm')
    video = db.create_video(model, {})
    post = db.schedule_post(video, 'tiktok', datetime(2020, 1, 1))
    for _ in range(3):
        assert db.get_due_posts(max_attempts=3)
        db.mark_post(post, 'failed', error='network')
    assert not db.get_due_posts(max_attempts=3)
