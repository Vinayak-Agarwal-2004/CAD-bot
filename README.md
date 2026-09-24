# CAD-bot

Turns CAD models (STL) into looping 9:16 shorts and publishes them to
**YouTube Shorts, Instagram Reels and TikTok**. It then measures what gets
views and steers future videos towards it.

```
STL files ──► scan & score ──► pick a variant ──► Blender render ──► Claude writes copy
                                  ▲                                        │
                                  │                            overlays, music, encode
                                  │                                        │
                        learn what works ◄── collect metrics ◄── schedule & publish
```

## What it does for reach

| Lever | How it's implemented |
|---|---|
| **Native format** | 1080×1920, 30 fps, H.264 High + AAC 48 kHz, faststart, loudness normalised to −14 LUFS: what all three platforms ingest cleanly. |
| **Re-watches** | The model turns on a turntable with a sine tilt; the last frame flows into the first, so the video loops seamlessly. Clips are 7–10 s. |
| **A hook in the first second** | Big on-screen hook with a pop-in animation, and a camera pull-back ("reveal") or blur-to-sharp start depending on the format. |
| **Comments** | Every format ends with a call to action matched to its hook ("Rate this design 1-10" → "Drop your rating 1-10"). The same question goes in the caption and is posted as the first comment. |
| **Picking good models** | Meshes are scored for visual interest (detail, curvature, holes, proportions). Trivial, broken or duplicate files are skipped. |
| **Filling the frame** | Every model is stood on its longest axis and the camera is fitted to the spinning footprint, so it fills the 9:16 frame. |
| **Nothing hidden under the UI** | All text stays out of the zones covered by each app's buttons and captions. |
| **Search** | Keyword-rich captions and YouTube tags (TikTok and Instagram are used as search engines); 3–5 niche-first hashtags, rotated. |
| **Specific copy** | Optional: Claude looks at the render and mesh facts and writes the hook, title and caption, told not to invent claims. |
| **Consistency** | A steady daily cadence per platform, plus a numbered series label ("CAD Challenge #12") that gives people a reason to follow. |
| **Trending sounds** | TikTok defaults to *draft* mode: the video lands in your inbox so you can add a trending sound in-app (the API can't). Every export also includes a no-music copy for the same reason on Reels. |
| **Learning** | Each video's choices (format, hook, palette, material, text style, length, posting hour) are logged. Once posts are 48 h old, Thompson sampling favours what beats your typical post, while still testing alternatives. |

Things it deliberately does **not** do: buy views, run bot accounts, auto-like,
follow/unfollow, or repost other people's content. Those get accounts
suppressed or banned, and they break each platform's terms of service.

## Quick start

```bash
./Setup.sh                      # ffmpeg, fonts, Blender 4.2 LTS, Python venv
. .venv/bin/activate
python main.py scan             # register + score everything in data/stl_files
python main.py produce -n 1 --preview   # fast half-res test video
python main.py produce -n 5     # full quality
```

Finished videos land in `data/output_videos/`. Each one also gets a bundle in
`data/exports/cadbot_NNNNN/` with the video, a no-music copy, the cover,
per-platform captions, the first comment and a posting checklist. That's
enough to post by hand without connecting any API.

No Blender install? On Python 3.11, `pip install bpy==4.2.0` works too
(`BLENDER_MODE=auto` picks whichever is available).

### Getting models

`data/stl_files/` is scanned recursively. The [ABC dataset](https://deep-geometry.github.io/abc-dataset/)
has a million CAD models. Download a chunk of its STL archive and extract it there.

### Music

Put royalty-free tracks in `data/audio-assets/` (mp3/wav/m4a/aac/ogg/flac).
A random track is used per video, avoiding the last 8 used. **Check the
licence of every track.** "No copyright" YouTube uploads often still need
attribution, or get Content ID claims on monetised channels.

## Connecting platforms

Copy `.env.example` to `.env` and fill in what you use. Unconnected platforms
are skipped and their videos stay in `data/exports/` for manual posting.

**YouTube.** In Google Cloud, enable *YouTube Data API v3*, create an OAuth
client of type *Desktop app*, and save its JSON as
`secrets/youtube_client_secret.json`. Then run `python main.py auth youtube`.
Each upload uses ~1,600 of the default 10,000 daily quota units (about 6
uploads a day).

**Instagram.** Needs a Business or Creator account linked to a Meta app with
`instagram_content_publish`, `instagram_manage_comments` and
`instagram_manage_insights`. Set `INSTAGRAM_USER_ID` and a long-lived
`INSTAGRAM_ACCESS_TOKEN` (use `GRAPH_API_HOST=graph.instagram.com` for
Instagram-Login tokens). Videos are uploaded directly; set
`PUBLIC_MEDIA_BASE_URL` if you'd rather have Instagram fetch them from your
own hosting.

**TikTok.** Create an app on developers.tiktok.com with the Content Posting
API (`video.upload`, `video.publish`, `video.list`) and set
`TIKTOK_ACCESS_TOKEN`. `TIKTOK_MODE=draft` sends videos to your inbox so you
can finish them in-app (recommended). `direct` posts immediately, but
unaudited apps can only post privately. After finishing a draft, run
`python main.py link <post_id> <tiktok_video_id>` so its stats get collected.

## Running it on autopilot

```cron
# every 15 min: post whatever is due
*/15 * * * *  cd /path/to/CAD-bot && .venv/bin/python main.py publish
# nightly: render tomorrow's videos, fill the calendar, pull stats
0 2 * * *     cd /path/to/CAD-bot && .venv/bin/python main.py produce -n 6 && .venv/bin/python main.py schedule && .venv/bin/python main.py collect
```

`python main.py report` shows each choice's lift over your typical post:

```
FORMAT
  guess_the_object     lift +0.84  posts 12   median views 2,310
  rate_the_design      lift +0.12  posts 9    median views 1,020
  ...
```

## Commands

| Command | What it does |
|---|---|
| `scan` | Register STL files, drop duplicates (by content hash), score the rest |
| `produce -n N [--format F] [--preview]` | Render the N most interesting unrendered models |
| `render FILE.stl [--format F]` | One-off video for a specific file |
| `schedule [--days 7]` | Give ready videos posting slots on connected platforms |
| `publish [--dry-run]` | Post everything that's due, then post the first comment |
| `collect` | Pull views, likes, comments, shares and saves |
| `report` | What's working, per choice |
| `run` | scan → produce → schedule → publish → collect |
| `auth youtube` | One-time OAuth login |
| `link POST_ID REMOTE_ID` | Attach a TikTok draft's final video id |
| `stats` | Pipeline counts |

## Formats

| Format | Why it works |
|---|---|
| `guess_the_object` | Blurred silhouette sharpens over 2.4 s. People stay to see it and comment guesses. If Claude is confident, the answer shows at the end. |
| `satisfying_spin` | Minimal text, built purely for the loop. |
| `rate_the_design` | Asking for a number is the easiest comment to leave. |
| `specs_breakdown` | Real mesh facts (triangle count, holes, watertight) appear as cards. They give the engineering crowd something to argue about. |
| `whats_inside` | A cutting plane opens the part mid-spin, and the inside walls show in a contrasting colour. The cut always faces the camera, so you look straight in, then it closes before the loop. Only used on chunky parts (aspect ratio ≤ 3.5); thin ones would be sliced into fragments. |
| `how_many_parts` | Exploded view: the separate bodies fly apart (mostly vertically, to use the tall frame), then snap back together. The part count Blender actually found is shown as the answer at the end. Only used on models with 2–40 separate bodies. |
| `silhouette_guess` | The part spins as a flat outline for 2.6 s, then fades into the full render. A harder guessing game with a strong payoff moment. |

The experiment engine only picks formats that suit each model. If you force
one with `--format` on a model it doesn't suit, another is picked. Covers for
the guessing formats stay blurred or show only the outline, so the thumbnail
doesn't give the answer away.

Add your own in `content/formats.py`. Hooks must be true for every video they
can be used on. Blender-side animations go in `rendering/effects.py`
(timing) and `rendering/blender_renderer.py` (scene).

## Configuration

Every setting in `config.py` can be overridden via an environment variable or
`.env`. The main ones:

- `RENDER_SAMPLES` (32, denoised) and `USE_GPU`/`GPU_BACKEND`: CPU rendering works but is slow; a GPU is 10–50× faster.
- `POSTS_PER_DAY` per platform (`YOUTUBE_POSTS_PER_DAY`, …), `TIMEZONE`, and `POSTING_HOURS` (the candidates the scheduler learns between).
- `VIDEO_DURATIONS` (`7,10`): clip lengths the engine tests against each other.
- `USE_LLM`, `LLM_MODEL`: Claude copywriting (needs `ANTHROPIC_API_KEY`).
- `BRAND_HANDLE`, `SERIES_NAME`: watermark and series label.
- `METRICS_MATURITY_HOURS` (48), `EXPLORATION_RATE` (0.2): learning behaviour.

## Development

```bash
python -m pytest        # 60+ tests; ffmpeg tests skip if ffmpeg is missing
RUN_BLENDER_TESTS=1 python -m pytest tests/test_blender_effects.py   # real Blender renders of each effect
```

Layout: `rendering/` (Blender scene, frame compositing, encoding),
`content/` (mesh analysis, formats, copy, experiments), `publishing/`
(per-platform APIs, scheduler, export bundles), `database/` (SQLite),
`pipeline.py` (orchestration), `main.py` (CLI).
