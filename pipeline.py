"""
End-to-end pipeline: models in, scheduled posts and learned preferences out.
"""
import logging
import random
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import config
from content import llm
from content.experiments import ExperimentEngine
from content.formats import FORMATS, cta_for, fill_placeholders, stat_lines
from content.metadata import build_metadata
from content.model_analyzer import evaluate, file_sha256
from database.db_manager import DatabaseManager, utcnow
from publishing.base import Publisher
from publishing.exporter import export_bundle
from publishing.instagram import InstagramPublisher
from publishing.scheduler import local_hour, next_slot
from publishing.tiktok import TikTokPublisher
from publishing.youtube import YouTubePublisher
from rendering.blender_runner import run_render
from rendering.color_generator import ColorGenerator
from rendering.frame_compositor import FrameCompositor, OverlayPlan
from rendering.video_compositor import VideoCompositor, pick_audio

logger = logging.getLogger(__name__)


def build_publishers() -> Dict[str, Publisher]:
    return {
        'youtube': YouTubePublisher(config.YOUTUBE_CLIENT_SECRETS, config.YOUTUBE_TOKEN_FILE,
                                    config.YOUTUBE_PRIVACY, config.YOUTUBE_CATEGORY_ID,
                                    config.YOUTUBE_PLAYLIST_ID),
        'instagram': InstagramPublisher(config.INSTAGRAM_USER_ID, config.INSTAGRAM_ACCESS_TOKEN,
                                        config.GRAPH_API_VERSION, config.GRAPH_API_HOST,
                                        config.PUBLIC_MEDIA_BASE_URL),
        'tiktok': TikTokPublisher(config.TIKTOK_ACCESS_TOKEN, config.TIKTOK_MODE, config.TIKTOK_PRIVACY),
    }


class Pipeline:
    def __init__(self, db: Optional[DatabaseManager] = None, publishers: Optional[Dict[str, Publisher]] = None,
                 seed: Optional[int] = None):
        config.ensure_dirs()
        self.db = db or DatabaseManager(config.DB_PATH)
        self.rng = random.Random(seed)
        self._publishers = publishers

    @property
    def publishers(self) -> Dict[str, Publisher]:
        if self._publishers is None:
            self._publishers = build_publishers()
        return self._publishers

    # ------------------------------------------------------------ ingest
    def scan(self) -> Dict[str, int]:
        """Register every STL under STL_DIR, drop duplicates, score the rest."""
        paths = sorted({p.resolve() for p in config.STL_DIR.rglob('*') if p.suffix.lower() == '.stl'})
        logger.info('Found %d STL files in %s', len(paths), config.STL_DIR)
        counts = {'new': 0, 'duplicate': 0, 'rejected': 0, 'accepted': 0, 'error': 0}
        for path in paths:
            existing = self.db.get_model_by_path(path)
            # Unreadable files are retried (a missing dependency shouldn't reject them forever).
            if existing and (existing['stats'] is not None or existing['status'] == 'duplicate'):
                continue
            sha = file_sha256(path)
            model_id = self.db.add_model(path, sha)
            counts['new'] += 1
            if self.db.find_duplicate(model_id, sha):
                self.db.set_model_status(model_id, 'duplicate')
                counts['duplicate'] += 1
                continue
            try:
                stats, score, status = evaluate(path, config.MIN_TRIANGLES, config.MAX_TRIANGLES)
            except Exception as exc:
                logger.warning('Cannot read %s: %s', path.name, exc)
                self.db.set_model_status(model_id, 'rejected', f'unreadable: {exc}')
                counts['error'] += 1
                continue
            self.db.set_model_analysis(model_id, stats, score, status)
            counts['rejected' if status == 'rejected' else 'accepted'] += 1
            if status == 'rejected':
                logger.info('Skipping %s: %s', path.name, '; '.join(stats['reject_reasons']))
        logger.info('Scan: %s', counts)
        return counts

    # ------------------------------------------------------------ learning
    def performance_rows(self) -> List[Dict]:
        rows = self.db.get_performance_rows(config.METRICS_MATURITY_HOURS)
        for row in rows:
            posted = row.get('posted_at')
            if posted:
                row['hour'] = local_hour(datetime.strptime(posted, '%Y-%m-%d %H:%M:%S'), config.TIMEZONE)
        return rows

    def engine(self) -> ExperimentEngine:
        return ExperimentEngine(self.performance_rows(), config.EXPLORATION_RATE, self.rng)

    # ------------------------------------------------------------ production
    def produce(self, limit: int = 1, overrides: Optional[Dict] = None, preview: bool = False) -> List[int]:
        self.db.fail_stale_videos(int(config.RENDER_TIMEOUT * 1.5))
        queue = self.db.get_render_queue(limit=limit, max_attempts=config.MAX_RENDER_ATTEMPTS)
        if not queue:
            logger.info('Nothing to render: run `scan` or add STL files to %s', config.STL_DIR)
            return []
        engine = self.engine()
        produced = []
        for model in queue:
            video_id = self.produce_one(model, engine, overrides, preview)
            if video_id:
                produced.append(video_id)
        logger.info('Produced %d/%d videos', len(produced), len(queue))
        return produced

    def produce_one(self, model: Dict, engine: ExperimentEngine, overrides: Optional[Dict] = None,
                    preview: bool = False) -> Optional[int]:
        started = time.time()
        use_llm = config.USE_LLM and llm.llm_available()
        variant = engine.choose_variant(overrides, include_llm_hook=use_llm)
        palette = ColorGenerator(self.rng.randrange(1 << 30)).get_color_palette(variant['palette'])
        recent_audio = [v['variant'].get('audio') for v in self.db.get_videos()[-8:]]
        audio = pick_audio(config.AUDIO_DIR, recent_audio, self.rng)
        variant.update({'object_hex': palette['object_hex'], 'background_hex': palette['background_hex'],
                        'audio': audio.name if audio else None})

        video_id = self.db.create_video(model['id'], variant)
        work = config.WORK_DIR / f'video_{video_id:05d}'
        logger.info('Video %d: %s | %s', video_id, Path(model['filepath']).name,
                    ', '.join(f'{k}={variant[k]}' for k in ('format', 'hook_index', 'palette', 'material')))
        try:
            fps = config.FPS
            total_frames = int(round(variant['duration'] * fps))
            scale = 0.5 if preview else config.RENDER_SCALE
            render_w = int(config.VIDEO_WIDTH * scale) // 2 * 2
            render_h = int(config.VIDEO_HEIGHT * scale) // 2 * 2
            job = {
                'project_dir': str(config.BASE_DIR),
                'stl_path': model['filepath'],
                'output_dir': str(work / 'raw'),
                'width': render_w, 'height': render_h,
                'total_frames': total_frames, 'fps': fps,
                'engine': config.RENDER_ENGINE,
                'samples': 12 if preview else config.RENDER_SAMPLES,
                'use_gpu': config.USE_GPU, 'gpu_backend': config.GPU_BACKEND,
                'object_color': list(palette['object_rgb']),
                'material': variant['material'],
                'motion': variant['motion'],
                'lens_mm': config.CAMERA_LENS_MM,
                'elevation_deg': config.CAMERA_ELEVATION_ANGLE,
                'tilt_swing_deg': config.CAMERA_ELEVATION_SWING,
                'distance_margin': config.CAMERA_FRAMING_MARGIN,
            }
            raw_dir = run_render(job, work, config.BLENDER_BIN, config.BLENDER_MODE, config.RENDER_TIMEOUT)
            raw_frames = sorted(raw_dir.glob('frame_*.png'))

            fmt = FORMATS[variant['format']]
            compositor = FrameCompositor(config.VIDEO_WIDTH, config.VIDEO_HEIGHT, fps, config.FONT_PATH)
            base_plan = OverlayPlan(palette['background_top'], palette['background_bottom'])
            hero_frame = raw_frames[len(raw_frames) // 8]

            copy = None
            if use_llm:
                still = compositor.preview_still(hero_frame, work / 'still.jpg', base_plan)
                copy = llm.generate_copy(still, model['stats'], variant['format'], fmt['hooks'], config.LLM_MODEL)
            if variant['hook_index'] == 'llm' and not (copy and copy.get('hook')):
                variant['hook_index'] = 0          # Claude unavailable: fall back to a template hook
            hook = copy['hook'] if variant['hook_index'] == 'llm' else \
                fill_placeholders(fmt['hooks'][int(variant['hook_index'])], model['stats'])

            answer = ''
            if fmt.get('show_answer') and copy and (copy.get('guess_confidence') or 0) >= 0.7:
                answer = f"Looks like: {copy['object_guess']}"
            plan = OverlayPlan(
                palette['background_top'], palette['background_bottom'],
                hook=hook, hook_seconds=fmt.get('hook_seconds', 2.8),
                cta=cta_for(variant['format'], variant['hook_index']), answer=answer,
                stat_lines=stat_lines(model['stats']) if fmt.get('stat_cards') else [],
                blur_reveal=fmt.get('blur_reveal', False), text_style=variant['text_style'],
                series_label=f'{config.SERIES_NAME} #{video_id}' if config.SERIES_NAME else '',
                handle=config.BRAND_HANDLE)
            compositor.compose(raw_dir, work / 'final', plan)

            video_path = config.OUTPUT_DIR / f'cadbot_{video_id:05d}.mp4'
            encoder = VideoCompositor(fps, config.VIDEO_CRF, config.AUDIO_VOLUME_DB, config.AUDIO_FADE_SECONDS)
            encoder.encode(work / 'final', video_path, audio, preset='veryfast' if preview else 'medium')
            cover_path = compositor.cover(hero_frame, config.OUTPUT_DIR / f'cadbot_{video_id:05d}_cover.jpg', plan)

            cover_seconds = len(raw_frames) // 8 / fps
            if plan.blur_reveal:
                cover_seconds = max(cover_seconds, plan.reveal_seconds + 0.3)
            metadata = build_metadata(variant['format'], hook, model['stats'], copy, plan.series_label, self.rng)
            metadata.update({'cover_time_ms': int(cover_seconds * 1000), 'audio': variant['audio'],
                             'variant': variant, 'model_file': Path(model['filepath']).name})

            silent = encoder.strip_audio(video_path, work / 'silent.mp4') if audio else video_path
            export_bundle(config.EXPORT_DIR / f'cadbot_{video_id:05d}', video_path, silent, cover_path, metadata)
            self.db.update_video_variant(video_id, variant)   # hook may have fallen back
            self.db.finish_video(video_id, video_path, cover_path, metadata, time.time() - started)
            self.db.set_model_status(model['id'], 'rendered', count_attempt=True)
            logger.info('Video %d ready in %.0fs: %s', video_id, time.time() - started, video_path)
            return video_id
        except Exception as exc:
            logger.error('Video %d failed: %s', video_id, exc)
            self.db.fail_video(video_id, str(exc))
            self.db.set_model_status(model['id'], 'failed', str(exc)[:2000], count_attempt=True)
            return None
        finally:
            if not config.KEEP_FRAMES:
                for sub in ('raw', 'final'):
                    shutil.rmtree(work / sub, ignore_errors=True)

    # ------------------------------------------------------------ scheduling & publishing
    def ready_platforms(self) -> Dict[str, Publisher]:
        ready = {}
        for name in config.PLATFORMS:
            publisher = self.publishers.get(name)
            if publisher is None:
                logger.warning('Unknown platform %r in PLATFORMS', name)
                continue
            ok, reason = publisher.configured()
            if ok:
                ready[name] = publisher
            else:
                logger.info('%s not set up (%s); videos stay in %s for manual posting',
                            name, reason, config.EXPORT_DIR)
        return ready

    def schedule(self, days_ahead: int = 7) -> int:
        engine = self.engine()
        scheduled = 0
        for platform in self.ready_platforms():
            per_day = config.POSTS_PER_DAY.get(platform, 1)
            hours = config.POSTING_HOURS.get(platform, [12, 18])
            for video in self.db.get_videos(status='ready', unscheduled_for=platform):
                existing = self.db.get_scheduled_times(platform, utcnow() - timedelta(days=1))
                try:
                    slot = next_slot(existing, per_day, hours, config.TIMEZONE,
                                     lambda free, p=platform: engine.choose_hour(p, free),
                                     rng=self.rng, horizon_days=days_ahead)
                except RuntimeError:
                    break   # calendar full for this window; the rest waits for the next run
                if self.db.schedule_post(video['id'], platform, slot):
                    scheduled += 1
                    logger.info('Scheduled video %d on %s at %s UTC', video['id'], platform, slot)
        return scheduled

    def publish_due(self, dry_run: bool = False) -> int:
        ready = self.ready_platforms()
        done = 0
        for post in self.db.get_due_posts():
            publisher = ready.get(post['platform'])
            if publisher is None:
                continue
            video = self.db.get_video(post['video_id'])
            if dry_run:
                logger.info('[dry run] would post video %d to %s', video['id'], post['platform'])
                continue
            try:
                result = publisher.publish(Path(video['video_path']),
                                           Path(video['cover_path']) if video['cover_path'] else None,
                                           video['metadata'], video['metadata'].get('cover_time_ms', 0))
            except Exception as exc:
                logger.error('Posting video %d to %s failed: %s', video['id'], post['platform'], exc)
                self.db.mark_post(post['id'], 'failed', error=str(exc)[:2000])
                continue
            self.db.mark_post(post['id'], result.status, result.remote_id, result.url)
            done += 1
            logger.info('Posted video %d to %s: %s', video['id'], post['platform'], result.url or result.remote_id)
            if config.POST_FIRST_COMMENT and result.status == 'posted' and video['metadata'].get('first_comment'):
                try:
                    publisher.post_comment(result.remote_id, video['metadata']['first_comment'])
                except Exception as exc:   # a missing comment must never fail the post
                    logger.warning('First comment on %s failed: %s', post['platform'], exc)
        return done

    def collect_metrics(self) -> int:
        collected = 0
        for platform, publisher in self.ready_platforms().items():
            posts = self.db.get_posts(platform)
            by_remote = {p['remote_id']: p for p in posts if p['remote_id']}
            if not by_remote:
                continue
            try:
                metrics = publisher.fetch_metrics(list(by_remote))
            except Exception as exc:
                logger.warning('Could not fetch %s metrics: %s', platform, exc)
                continue
            for remote_id, m in metrics.items():
                post = by_remote.get(remote_id)
                if post:
                    self.db.add_metrics(post['id'], m.views, m.likes, m.comments, m.shares, m.saves, m.raw)
                    collected += 1
        logger.info('Collected metrics for %d posts', collected)
        return collected
