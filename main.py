"""
CAD-bot: turn CAD models into shorts and grow an audience on YouTube,
Instagram and TikTok.

    python main.py scan                 # register + score STL files
    python main.py produce -n 3         # render the 3 most interesting models
    python main.py render part.stl      # one-off video for a specific file
    python main.py schedule             # assign posting slots on connected platforms
    python main.py publish              # post whatever is due (run from cron)
    python main.py collect              # pull views/likes/comments
    python main.py report               # what's working, per choice
    python main.py run -n 1             # scan + produce + schedule + publish + collect
    python main.py auth youtube         # one-time OAuth
    python main.py link 12 7301234567   # attach a TikTok draft's final video id to post 12
    python main.py stats
"""
import argparse
import json
import sys
from pathlib import Path

import config
from utils.logger import setup_logger


def cmd_scan(pipeline, args):
    pipeline.scan()


def cmd_produce(pipeline, args):
    overrides = {k: v for k, v in (('format', args.format), ('palette', args.palette),
                                   ('material', args.material)) if v}
    pipeline.produce(limit=args.count, overrides=overrides, preview=args.preview)


def cmd_render(pipeline, args):
    from content.model_analyzer import evaluate, file_sha256
    path = Path(args.stl).resolve()
    if not path.exists():
        sys.exit(f'File not found: {path}')
    model_id = pipeline.db.add_model(path, file_sha256(path))
    stats, score, _ = evaluate(path, 0, 10 ** 9)       # explicit request: don't filter
    pipeline.db.set_model_analysis(model_id, stats, score, 'pending')
    overrides = {k: v for k, v in (('format', args.format),) if v}
    video_id = pipeline.produce_one(pipeline.db.get_model(model_id), pipeline.engine(), overrides, args.preview)
    if not video_id:
        sys.exit(1)


def cmd_schedule(pipeline, args):
    pipeline.schedule(days_ahead=args.days)


def cmd_publish(pipeline, args):
    pipeline.publish_due(dry_run=args.dry_run)


def cmd_collect(pipeline, args):
    pipeline.collect_metrics()


def cmd_report(pipeline, args):
    engine = pipeline.engine()
    if not engine.rows:
        print(f'No posts older than {config.METRICS_MATURITY_HOURS}h with metrics yet. '
              'Publish, wait, then run `collect`.')
        return
    print(f'Based on {len(engine.rows)} matured posts. "lift" = average log-views vs your typical post.\n')
    for dim, arms in engine.report().items():
        if not arms:
            continue
        print(dim.upper())
        for arm, s in arms.items():
            print(f"  {arm:<28} lift {s['mean']:+.2f}  posts {s['n']:<4} median views {s['median_views']:,.0f}")
        print()


def cmd_run(pipeline, args):
    pipeline.scan()
    pipeline.produce(limit=args.count, preview=args.preview)
    pipeline.schedule(days_ahead=args.days)
    pipeline.publish_due()
    pipeline.collect_metrics()


def cmd_auth(pipeline, args):
    if args.platform != 'youtube':
        sys.exit('Only YouTube uses an interactive login; Instagram and TikTok take tokens in .env')
    pipeline.publishers['youtube'].authorize(interactive=True)
    print(f'Saved YouTube token to {config.YOUTUBE_TOKEN_FILE}')


def cmd_link(pipeline, args):
    pipeline.db.mark_post(args.post_id, 'posted', remote_id=args.remote_id, url=args.url)
    print(f'Post {args.post_id} linked to {args.remote_id}')


def cmd_stats(pipeline, args):
    print(json.dumps(pipeline.db.get_statistics(), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='CAD models -> shorts for YouTube, Instagram and TikTok')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('scan', help='register and score STL files').set_defaults(func=cmd_scan)

    produce = sub.add_parser('produce', help='render videos for the best unrendered models')
    produce.add_argument('-n', '--count', type=int, default=1)
    produce.add_argument('--format', choices=_formats())
    produce.add_argument('--palette')
    produce.add_argument('--material')
    produce.add_argument('--preview', action='store_true', help='half resolution, fewer samples')
    produce.set_defaults(func=cmd_produce)

    render = sub.add_parser('render', help='make a video from one STL file')
    render.add_argument('stl')
    render.add_argument('--format', choices=_formats())
    render.add_argument('--preview', action='store_true')
    render.set_defaults(func=cmd_render)

    schedule = sub.add_parser('schedule', help='assign posting times on connected platforms')
    schedule.add_argument('--days', type=int, default=7, help='how far ahead to fill the calendar')
    schedule.set_defaults(func=cmd_schedule)

    publish = sub.add_parser('publish', help='post everything that is due')
    publish.add_argument('--dry-run', action='store_true')
    publish.set_defaults(func=cmd_publish)

    sub.add_parser('collect', help='fetch post metrics').set_defaults(func=cmd_collect)
    sub.add_parser('report', help='show which choices perform best').set_defaults(func=cmd_report)
    sub.add_parser('stats', help='pipeline counts').set_defaults(func=cmd_stats)

    run = sub.add_parser('run', help='scan, produce, schedule, publish and collect (for cron)')
    run.add_argument('-n', '--count', type=int, default=1)
    run.add_argument('--days', type=int, default=7)
    run.add_argument('--preview', action='store_true')
    run.set_defaults(func=cmd_run)

    auth = sub.add_parser('auth', help='one-time platform login')
    auth.add_argument('platform', choices=['youtube'])
    auth.set_defaults(func=cmd_auth)

    link = sub.add_parser('link', help='record the final id of a post finished in the app (TikTok drafts)')
    link.add_argument('post_id', type=int)
    link.add_argument('remote_id')
    link.add_argument('--url')
    link.set_defaults(func=cmd_link)
    return parser


def _formats():
    from content.formats import FORMATS
    return list(FORMATS)


def main(argv=None):
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    setup_logger(config.LOG_DIR)
    from pipeline import Pipeline
    args.func(Pipeline(), args)


if __name__ == '__main__':
    main()
