"""
Frame sequence -> MP4 using the ffmpeg CLI.

Output matches what Shorts, Reels and TikTok ingest without re-compressing
badly: H.264 High profile, yuv420p, 30 fps, 1080x1920, AAC 48 kHz, faststart,
loudness normalised to about -14 LUFS.
"""
import json
import logging
import random
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')


class EncodeError(RuntimeError):
    pass


def _run(cmd: List[str]):
    if shutil.which(cmd[0]) is None:
        raise EncodeError(f'{cmd[0]} not found; install ffmpeg')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise EncodeError(f'{cmd[0]} failed:\n' + '\n'.join(result.stderr.strip().splitlines()[-15:]))
    return result


def list_audio(audio_dir: Path) -> List[Path]:
    if not audio_dir.exists():
        return []
    return sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)


def pick_audio(audio_dir: Path, recently_used: Iterable[str] = (), rng: Optional[random.Random] = None) -> Optional[Path]:
    """Random track, avoiding the ones used most recently so the feed doesn't repeat."""
    rng = rng or random.Random()
    tracks = list_audio(audio_dir)
    if not tracks:
        return None
    recent = set(recently_used)
    fresh = [t for t in tracks if t.name not in recent]
    return rng.choice(fresh or tracks)


class VideoCompositor:
    def __init__(self, fps: int = 30, crf: int = 18, loudness_lufs: float = -14.0,
                 fade_seconds: float = 0.6):
        self.fps = fps
        self.crf = crf
        self.loudness = loudness_lufs
        self.fade = fade_seconds

    def encode(self, frames_dir: Path, output_path: Path, audio: Optional[Path] = None,
               preset: str = 'medium') -> Path:
        frames = sorted(frames_dir.glob('frame_*.png'))
        if not frames:
            raise EncodeError(f'no frames in {frames_dir}')
        duration = len(frames) / self.fps
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
               '-framerate', str(self.fps), '-start_number', '1',
               '-i', str(frames_dir / 'frame_%04d.png')]
        if audio:
            fade_out_start = max(0.0, duration - self.fade)
            cmd += ['-i', str(audio), '-filter_complex',
                    f'[1:a]apad,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,'
                    f'afade=t=in:d=0.25,afade=t=out:st={fade_out_start:.3f}:d={self.fade:.3f},'
                    f'loudnorm=I={self.loudness}:TP=-1.5:LRA=11,aresample=48000[a]',
                    '-map', '0:v', '-map', '[a]', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000']
        cmd += ['-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                '-crf', str(self.crf), '-preset', preset, '-r', str(self.fps),
                '-g', str(self.fps), '-movflags', '+faststart',
                '-t', f'{duration:.3f}', str(output_path)]
        _run(cmd)
        logger.info('Encoded %s (%.1fs%s)', output_path.name, duration,
                    f', audio: {audio.name}' if audio else ', silent')
        return output_path

    @staticmethod
    def strip_audio(video_path: Path, output_path: Path) -> Path:
        """Silent copy, for adding a trending sound inside the TikTok/Instagram app."""
        _run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video_path),
              '-c:v', 'copy', '-an', '-movflags', '+faststart', str(output_path)])
        return output_path

    @staticmethod
    def probe(video_path: Path) -> dict:
        result = _run(['ffprobe', '-v', 'error', '-show_entries',
                       'format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate',
                       '-of', 'json', str(video_path)])
        return json.loads(result.stdout)
