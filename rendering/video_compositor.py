"""
Video composition from rendered frame sequences using FFmpeg
"""
import ffmpeg
import logging
import random
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class VideoCompositor:
    def __init__(self, fps: int = 30):
        self.fps = fps

    def create_video_from_frames(
        self,
        frames_dir: Path,
        output_path: Path,
        width: int = 1080,
        height: int = 1920,
        crf: int = 18,
        preset: str = 'medium'
    ) -> Path:
        """
        Create MP4 video from a sequence of PNG frames.

        Args:
            frames_dir: Directory containing frame_XXXX.png files.
            output_path: Path for the output video.
            width: Video width.
            height: Video height.
            crf: Constant Rate Factor (18-28, lower is better quality).
            preset: Encoding speed preset (e.g., 'medium', 'fast').

        Returns:
            Path to the created video.
        """
        try:
            input_pattern = str(frames_dir / 'frame_%04d.png')
            logger.info(f"Creating video from frames in {frames_dir}")
            logger.info(f"Output: {output_path}")

            output_path.parent.mkdir(parents=True, exist_ok=True)

            stream = (
                ffmpeg
                .input(input_pattern, framerate=self.fps)
                .filter('scale', width, height)
                .output(
                    str(output_path),
                    vcodec='libx264',
                    pix_fmt='yuv420p',
                    crf=crf,
                    preset=preset,
                    movflags='+faststart'
                )
                .overwrite_output()
            )
            
            ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
            logger.info(f"Video created successfully: {output_path}")
            return output_path
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error creating video: {e.stderr.decode()}")
            raise
        except Exception as e:
            logger.error(f"Error creating video: {str(e)}")
            raise

    def add_random_audio(
        self,
        video_path: Path,
        output_path: Path,
        audio_dir: Path
    ) -> Path:
        """
        Adds a random audio file from a directory to a video.

        Args:
            video_path: Path to the input video.
            output_path: Path for the output video with audio.
            audio_dir: Directory containing audio files (.mp3, .wav, .m4a).

        Returns:
            Path to the final video.
        """
        try:
            audio_files = list(audio_dir.glob('*.mp3'))
            audio_files += list(audio_dir.glob('*.wav'))
            audio_files += list(audio_dir.glob('*.m4a'))

            if not audio_files:
                logger.warning(f"No audio files found in {audio_dir}. Copying video without adding audio.")
                shutil.copy(video_path, output_path)
                return output_path

            selected_audio = random.choice(audio_files)
            logger.info(f"Selected random audio: {selected_audio.name}")

            video_input = ffmpeg.input(str(video_path))
            audio_input = ffmpeg.input(str(selected_audio))

            stream = (
                ffmpeg
                .output(
                    video_input.video,
                    audio_input.audio,
                    str(output_path),
                    vcodec='copy',
                    acodec='aac',
                    audio_bitrate='192k',
                    shortest=None
                )
                .overwrite_output()
            )
            
            ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
            logger.info(f"Audio added successfully: {output_path}")
            return output_path
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error adding audio: {e.stderr.decode()}")
            raise
        except Exception as e:
            logger.error(f"Error adding random audio: {str(e)}")
            raise

    def create_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        timestamp: str = '00:00:05'
    ) -> Path:
        """
        Extract a thumbnail from a video at a specific timestamp.

        Args:
            video_path: Path to the input video.
            output_path: Path for the output thumbnail image.
            timestamp: Timestamp in HH:MM:SS format.

        Returns:
            Path to the created thumbnail.
        """
        try:
            stream = (
                ffmpeg
                .input(str(video_path), ss=timestamp)
                .output(str(output_path), vframes=1)
                .overwrite_output()
            )

            ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
            logger.info(f"Thumbnail created: {output_path}")
            return output_path
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error creating thumbnail: {e.stderr.decode()}")
            raise
