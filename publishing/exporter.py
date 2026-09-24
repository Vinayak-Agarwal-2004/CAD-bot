"""
Ready-to-post bundle per video, for manual posting or for platforms that
aren't connected: the video, a silent copy (to add a trending sound in-app),
the cover, and copy-paste text for each platform.
"""
import json
import shutil
from pathlib import Path
from typing import Dict, Optional


def export_bundle(folder: Path, video: Path, silent_video: Optional[Path], cover: Optional[Path],
                  metadata: Dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, folder / 'video.mp4')
    if silent_video and silent_video != video:
        shutil.copy2(silent_video, folder / 'video_no_music.mp4')
    if cover:
        shutil.copy2(cover, folder / 'cover.jpg')

    yt = metadata['youtube']
    (folder / 'youtube.txt').write_text(
        f"TITLE\n{yt['title']}\n\nDESCRIPTION\n{yt['description']}\n\nTAGS\n{', '.join(yt['tags'])}\n")
    (folder / 'tiktok.txt').write_text(metadata['tiktok']['caption'] + '\n')
    (folder / 'instagram.txt').write_text(metadata['instagram']['caption'] + '\n')
    (folder / 'first_comment.txt').write_text(metadata['first_comment'] + '\n')
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2, default=str))
    (folder / 'POSTING_CHECKLIST.txt').write_text(CHECKLIST.format(
        cover_s=metadata.get('cover_time_ms', 0) / 1000))
    return folder


CHECKLIST = """Posting checklist
=================
1. TikTok / Reels: upload video_no_music.mp4 and pick a TRENDING sound in the
   app (keep it quiet, ~10-20%). Trending audio is one of the biggest reach
   levers and can't be added through the APIs. If you'd rather keep the
   bundled music, upload video.mp4.
2. Set the cover to the frame at ~{cover_s:.1f}s (or upload cover.jpg on Instagram).
3. Paste the caption for that platform (tiktok.txt / instagram.txt / youtube.txt).
4. Post first_comment.txt as the first comment and pin it.
5. Reply to every comment in the first hour. Replies count as engagement
   and early engagement decides how far a short gets pushed.
6. On Instagram, share the reel to your story. On TikTok, reply to good
   comments with a video reply using the next model.
"""
