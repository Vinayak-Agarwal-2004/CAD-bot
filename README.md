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
git clone https://github.com/Vinayak-Agarwal-2004/CAD-bot.git && cd CAD-bot
./install.sh                    # everything below, then a real test render
source .venv/bin/activate
python main.py scan             # register + score everything in data/stl_files
python main.py produce -n 1 --preview   # fast half-res test video
python main.py produce -n 5     # full quality
```

`install.sh` is safe to re-run and only uses `sudo` for system packages and
swap. Run it as your normal user. It:

- installs system packages with apt (Ubuntu 22.04+, Debian 12+) or dnf
  (Oracle Linux / RHEL / Rocky / Alma 8-9, Fedora);
- finds Python 3.10+, installing Python 3.11 on Oracle Linux 9, where the default is 3.9;
- downloads Blender 4.2.3 LTS from blender.org and verifies its SHA-256;
- uses the system ffmpeg if it has H.264 and AAC, otherwise a checksum-verified
  static build (Oracle Linux has no ffmpeg package);
- installs the Python packages into `.venv`, isolated from system packages;
- writes `.env` with the Blender/ffmpeg paths, GPU on/off, and low-memory
  settings plus a 2 GB swap file on machines under 3 GB of RAM (your own
  `.env` values are never overwritten);
- finishes with `python main.py doctor --render-test`, a tiny real
  Blender → frames → MP4 run.

Options: `--cron` (schedule posting and nightly rendering), `--low-memory` /
`--full-quality` (override the RAM-based choice), `--no-swap`,
`--blender PATH` (use your own Blender 4.x), `--skip-test`.

It was tested on clean Ubuntu 22.04, Ubuntu 24.04 and Oracle Linux 9 (as root,
and as a sudo user under a 1 GB / 1 CPU limit). `python main.py doctor`
re-checks the setup at any time.

Finished videos land in `data/output_videos/`. Each one also gets a bundle in
`data/exports/cadbot_NNNNN/` with the video, a no-music copy, the cover,
per-platform captions, the first comment and a posting checklist. That's
enough to post by hand without connecting any API.

The code targets Blender 4.2 LTS, which `install.sh` downloads from blender.org.
The `bpy` pip module also works if you can get a 4.2 build of it
(`BLENDER_MODE=auto` picks whichever is available), but PyPI now only offers
bpy 5.x, which this project hasn't been tested with.

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

## Small servers (1 vCPU / 1 GB RAM)

Rendering is the only heavy step. Compositing takes about 0.14 s a frame and
encoding about 20 s per video, both on one core. Measured on one pinned CPU
core with Blender 4.2.3, for the lava-lamp sample model:

| Setting | Blender peak memory | Time per frame | 7 s video (210 frames) |
|---|---|---|---|
| Full: 1080×1920, 32 samples, accurate denoise | ~1970 MB | ~90 s | ~5 h |
| 720×1280, 16 samples, accurate denoise | ~1075 MB | ~25 s | ~1.5 h |
| 540×960, 12 samples, accurate denoise | ~765 MB | ~12 s | ~45 min |
| **540×960, 12 samples, fast denoise** | **~510 MB** | **~4 s** | **~15 min** |

Most of Blender's memory goes to the denoiser, not the image. Smaller render
tiles don't help, but the denoiser's fast mode does. Turning the denoiser off
saves more (~350 MB) but leaves the image visibly grainy. The 540×960 frames
are upscaled to 1080×1920; on a phone screen they look nearly identical, just
slightly softer.

The last row is a real end-to-end run: one complete 7-second "how many
parts" video on one core in 15 minutes, with every process together
(Python, Blender, ffmpeg) peaking at 725 MB. In a second test, a fresh
`./install.sh` on Oracle Linux 9 inside a hard 1 GB RAM / 1 CPU limit with
no swap detected the small machine on its own, and then made a full
10-second video in about 22 minutes.

`install.sh` applies these settings automatically on machines under 3 GB of
RAM, and adds a 2 GB swap file as a safety net:

```bash
RENDER_SCALE=0.5
RENDER_SAMPLES=12
RENDER_DENOISE=fast
RENDER_THREADS=1
USE_GPU=false
```

Render one video at a time (`produce -n 1`) and let cron do it overnight
(`./install.sh --cron` renders one video a night on small machines).

**Oracle Cloud's Always Free AMD micro instance** has 1 GB of RAM but only
1/8 of a CPU as its guaranteed baseline. It can burst higher briefly, but a
long render will probably fall back towards the baseline and take several
times longer than the table above. The Always Free **Ampere A1** shape (up to
4 cores and 24 GB) has far more headroom, but it's ARM. Check that a Blender
4.2 build runs on it before relying on it; I haven't tested that.

## Running it on autopilot

`./install.sh --cron` adds these (re-running replaces them; `flock` stops a
slow render from overlapping the next one):

```cron
# every 15 min: post whatever is due
*/15 * * * *  cd /path/to/CAD-bot && flock -n /tmp/cadbot-publish.lock .venv/bin/python main.py publish >> logs/cron.log 2>&1
# nightly: render new videos (1 on small machines, 3 otherwise), fill the calendar, pull stats
30 1 * * *    cd /path/to/CAD-bot && flock -n /tmp/cadbot-produce.lock sh -c '... scan && ... produce -n 3 && ... schedule && ... collect' >> logs/cron.log 2>&1
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
| `doctor [--render-test]` | Check Blender, ffmpeg, fonts, packages, memory vs settings, and connected platforms; optionally make a tiny real video |

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
- `RENDER_SCALE`, `RENDER_DENOISE`, `RENDER_THREADS`: resolution, memory and CPU use (see *Small servers*).
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
