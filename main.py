"""
Main controller for STL to Video rendering pipeline
"""
import sys
import time
import logging
from pathlib import Path
from typing import Optional
import random

# Import project modules
from config import *
from database.db_manager import DatabaseManager
from rendering.color_generator import ColorGenerator
from rendering.video_compositor import VideoCompositor
from utils.logger import setup_logger

# Setup logging
logger = setup_logger(BASE_DIR / 'logs')

class RenderPipeline:
    def __init__(self):
        self.db = DatabaseManager(DB_PATH)
        self.color_gen = ColorGenerator()
        self.compositor = VideoCompositor(fps=FPS)

    def scan_stl_directory(self):
        """Scan STL directory and add files to database"""
        logger.info(f"Scanning {STL_DIR} for STL files...")

        stl_files = list(STL_DIR.glob('**/*.stl'))
        logger.info(f"Found {len(stl_files)} STL files")

        added_count = 0
        for stl_file in stl_files:
            file_id = self.db.add_stl_file(stl_file)
            if file_id:
                added_count += 1

        logger.info(f"Added {added_count} new files to database")

    def render_single_file(self, stl_path: Path) -> Optional[Path]:
        """
        Render a single STL file to video

        Args:
            stl_path: Path to STL file

        Returns:
            Path to output video or None if failed
        """
        start_time = time.time()

        try:
            logger.info(f"Processing: {stl_path.name}")

            # Generate colors
            palette = self.color_gen.get_color_palette()
            logger.info(f"Object color: {palette['object_hex']}")
            logger.info(f"Background color: {palette['background_hex']}")

            # Get or create database entry
            file_id = self.db.add_stl_file(stl_path)
            job_id = self.db.create_render_job(
                file_id,
                palette['object_rgb'],
                palette['background_rgb']
            )

            # Create output directories
            render_dir = RENDERS_DIR / stl_path.stem
            render_dir.mkdir(parents=True, exist_ok=True)

            output_video = OUTPUT_DIR / f"{stl_path.stem}.mp4"

            # Call Blender renderer using subprocess
            # This must be done via subprocess to use Blender's Python
            blender_script = self._generate_blender_script(
                stl_path,
                render_dir,
                palette['object_rgb'],
                palette['background_rgb']
            )

            # Save temporary Blender script
            temp_script = BASE_DIR / 'temp_render_script.py'
            with open(temp_script, 'w') as f:
                f.write(blender_script)

            # Run Blender in background mode
            import subprocess
            blender_cmd = [
                'blender',  # or full path to Blender executable
                '--background',
                '--python', str(temp_script)
            ]

            logger.info("Running Blender render...")
            result = subprocess.run(
                blender_cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )

            if result.returncode != 0:
                raise RuntimeError(f"Blender render failed: {result.stderr}")

            logger.info("Blender render completed")

            # Compose video from frames (without audio first)
            logger.info("Creating video from frames...")
            temp_video = OUTPUT_DIR / f"{stl_path.stem}_temp.mp4"

            self.compositor.create_video_from_frames(
                render_dir,
                temp_video,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT
            )

            # Add random audio from audio-assets folder
            logger.info("Adding audio to video...")
            output_video = self.compositor.add_random_audio(
                temp_video,
                OUTPUT_DIR / f"{stl_path.stem}.mp4",
                AUDIO_DIR
            )

            # Clean up temporary video without audio
            if temp_video.exists():
                temp_video.unlink()


            # Update database
            render_duration = time.time() - start_time
            self.db.update_render_job(
                job_id,
                status='completed',
                output_path=str(output_video),
                render_duration=render_duration
            )

            logger.info(f"✓ Completed in {render_duration:.2f}s: {output_video}")

            # Clean up temporary files
            temp_script.unlink()

            # Optionally clean up frame files to save space
            # for frame in render_dir.glob('*.png'):
            #     frame.unlink()

            return output_video

        except Exception as e:
            logger.error(f"✗ Error rendering {stl_path.name}: {str(e)}")

            # Update database with error
            if 'job_id' in locals():
                self.db.update_render_job(
                    job_id,
                    status='failed',
                    error_message=str(e)
                )

            return None

    def _generate_blender_script(self, stl_path: Path, output_dir: Path,
                                object_color: tuple, background_color: tuple) -> str:
        """Generate Python script for Blender to execute"""
        return f'''
import sys
sys.path.append(r"{BASE_DIR}")

from rendering.blender_renderer import BlenderRenderer
from pathlib import Path

# Initialize renderer
renderer = BlenderRenderer(
    render_samples={RENDER_SAMPLES},
    use_gpu={USE_GPU}
)

# Render video frames
renderer.render_video(
    stl_path=Path(r"{stl_path}"),
    output_dir=Path(r"{output_dir}"),
    object_color={object_color},
    background_color={background_color},
    total_frames={TOTAL_FRAMES},
    fps={FPS},
    width={VIDEO_WIDTH},
    height={VIDEO_HEIGHT}
)
'''

    def process_queue(self, limit: Optional[int] = None):
        """
        Process pending files from database

        Args:
            limit: Maximum number of files to process (None = all)
        """
        pending_files = self.db.get_pending_files(limit=limit)

        if not pending_files:
            logger.info("No pending files to process")
            return

        logger.info(f"Processing {len(pending_files)} files...")

        success_count = 0
        for file_data in pending_files:
            stl_path = Path(file_data['filepath'])
            result = self.render_single_file(stl_path)
            if result:
                success_count += 1

        logger.info(f"Completed: {success_count}/{len(pending_files)} successful")

        # Print statistics
        stats = self.db.get_statistics()
        logger.info(f"Statistics: {stats}")

    def process_all(self):
        """Scan directory and process all files"""
        self.scan_stl_directory()
        self.process_queue()


def main():
    """Main entry point"""
    logger.info("="*60)
    logger.info("STL to Video Rendering Pipeline")
    logger.info("="*60)

    pipeline = RenderPipeline()

    # Check command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'scan':
            # Just scan and add to database
            pipeline.scan_stl_directory()

        elif command == 'process':
            # Process queue
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
            pipeline.process_queue(limit=limit)

        elif command == 'render':
            # Render specific file
            if len(sys.argv) < 3:
                logger.error("Usage: python main.py render <stl_file_path>")
                sys.exit(1)

            stl_path = Path(sys.argv[2])
            if not stl_path.exists():
                logger.error(f"File not found: {stl_path}")
                sys.exit(1)

            pipeline.render_single_file(stl_path)

        elif command == 'all':
            # Scan and process everything
            pipeline.process_all()

        else:
            logger.error(f"Unknown command: {command}")
            logger.info("Available commands: scan, process, render, all")
            sys.exit(1)
    else:
        # Default: process all
        pipeline.process_all()

    logger.info("Pipeline finished")


if __name__ == '__main__':
    main()
