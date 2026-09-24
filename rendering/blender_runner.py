"""
Launches a Blender render in a separate process and checks the result.
"""
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

JOB_SCRIPT = Path(__file__).resolve().parent / 'blender_job.py'


class RenderError(RuntimeError):
    pass


def build_command(job_file: Path, blender_bin: str, mode: str) -> List[str]:
    """mode: 'binary', 'module' or 'auto' (binary if found, else the bpy module)."""
    if mode == 'auto':
        mode = 'binary' if shutil.which(blender_bin) else 'module'
    if mode == 'binary':
        # --python-exit-code makes Blender exit non-zero when the script raises;
        # without it a crashed render still returns 0.
        return [blender_bin, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', str(JOB_SCRIPT), '--', str(job_file)]
    if mode == 'module':
        return [sys.executable, str(JOB_SCRIPT), str(job_file)]
    raise ValueError(f'unknown BLENDER_MODE {mode!r}')


def run_render(job: Dict, job_dir: Path, blender_bin: str, mode: str, timeout: int) -> Path:
    """Write the job spec next to its frames (so parallel jobs never collide) and run it."""
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / 'job.json'
    job_file.write_text(json.dumps(job, indent=2))

    cmd = build_command(job_file, blender_bin, mode)
    logger.info('Blender: %s', ' '.join(cmd[:2]) + ' ...')
    log_file = job_dir / 'blender.log'
    try:
        with open(log_file, 'w') as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    except FileNotFoundError as exc:
        raise RenderError(f'Blender not found ({exc}). Install Blender 4.2+ or `pip install bpy`.') from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f'Blender timed out after {timeout}s; see {log_file}') from exc

    if result.returncode != 0:
        tail = log_file.read_text(errors='replace').strip().splitlines()[-25:]
        raise RenderError(f'Blender exited with {result.returncode}:\n' + '\n'.join(tail))

    frames = sorted(Path(job['output_dir']).glob('frame_*.png'))
    if len(frames) != job['total_frames']:
        raise RenderError(f"Blender produced {len(frames)} of {job['total_frames']} frames; see {log_file}")
    return Path(job['output_dir'])
