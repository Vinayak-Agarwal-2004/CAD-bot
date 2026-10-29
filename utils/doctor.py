"""
`python main.py doctor`: checks that everything the pipeline needs is installed
and working, and with --render-test makes a tiny real video end to end.
"""
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import config

OK, WARN, FAIL = 'ok', 'warn', 'FAIL'
MARK = {OK: '  ✓', WARN: '  !', FAIL: '  ✗'}

# Measured peak Blender memory (MB) on one core for the lava-lamp sample
# (README "Small servers"), keyed by (render height, denoise mode).
MEMORY_TABLE = {(960, 'off'): 350, (960, 'fast'): 510, (960, 'accurate'): 765,
                (1280, 'fast'): 670, (1280, 'accurate'): 1075, (1920, 'accurate'): 1970}


class Report:
    def __init__(self):
        self.results: List[Tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = ''):
        self.results.append((status, name, detail))
        print(f'{MARK[status]} {name}' + (f': {detail}' if detail else ''), flush=True)

    @property
    def failed(self) -> bool:
        return any(s == FAIL for s, _, _ in self.results)


def _run(cmd: List[str], timeout: int = 120) -> Tuple[int, str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout + out.stderr
    except (FileNotFoundError, PermissionError) as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, f'timed out after {timeout}s'


def check_python(report: Report):
    v = sys.version_info
    status = OK if v >= (3, 10) else FAIL
    report.add(status, 'Python', f'{v.major}.{v.minor}.{v.micro}' + ('' if status == OK else ' (need 3.10+)'))
    for module, required in (('numpy', True), ('scipy', True), ('trimesh', True), ('PIL', True),
                             ('requests', True), ('dotenv', False), ('anthropic', False),
                             ('googleapiclient', False), ('google_auth_oauthlib', False)):
        try:
            importlib.import_module(module)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:   # noqa: BLE001 - incl. PyO3 panics from broken system packages
            report.add(FAIL if required else WARN, f'Python package {module}',
                       f'{exc.__class__.__name__}: {exc}; run ./install.sh')


def blender_version() -> Tuple[Optional[str], str]:
    """(version string or None, how Blender is reached / error)."""
    mode = config.BLENDER_MODE
    if mode == 'auto':
        mode = 'binary' if shutil.which(config.BLENDER_BIN) else 'module'
    probe = 'import bpy; print("BLENDER_VERSION", bpy.app.version_string)'
    if mode == 'binary':
        code, out = _run([config.BLENDER_BIN, '--background', '--factory-startup', '--python-expr', probe])
        where = config.BLENDER_BIN
    else:
        code, out = _run([sys.executable, '-c', probe])
        where = 'bpy Python module'
    match = re.search(r'BLENDER_VERSION (\S+)', out)
    if code != 0 or not match:
        tail = ' '.join(out.strip().splitlines()[-3:])[:300]
        return None, f'{where} not usable ({tail or "no output"})'
    return match.group(1), where


def check_blender(report: Report):
    version, where = blender_version()
    if version is None:
        report.add(FAIL, 'Blender', f'{where}. Run ./install.sh or set BLENDER_BIN')
        return
    major_minor = tuple(int(x) for x in re.findall(r'\d+', version)[:2])
    if major_minor < (4, 0) or major_minor >= (5, 0):
        report.add(FAIL, 'Blender', f'{version} at {where}; this project needs Blender 4.x (4.2 LTS tested)')
    elif major_minor != (4, 2):
        report.add(WARN, 'Blender', f'{version} at {where}; 4.2 LTS is the tested version')
    else:
        report.add(OK, 'Blender', f'{version} ({where})')


def check_ffmpeg(report: Report):
    code, out = _run([config.FFMPEG_BIN, '-hide_banner', '-encoders'])
    if code != 0:
        report.add(FAIL, 'ffmpeg', f'{config.FFMPEG_BIN} not usable; run ./install.sh or set FFMPEG_BIN')
        return
    missing = [enc for enc in ('libx264', 'aac') if not re.search(rf'\s{enc}\s', out)]
    if missing:
        report.add(FAIL, 'ffmpeg', f"{config.FFMPEG_BIN} lacks encoders: {', '.join(missing)}")
    else:
        version = _run([config.FFMPEG_BIN, '-version'])[1].split('\n')[0]
        report.add(OK, 'ffmpeg', version[:60])
    if _run([config.FFPROBE_BIN, '-version'])[0] != 0:
        report.add(FAIL, 'ffprobe', f'{config.FFPROBE_BIN} not usable; set FFPROBE_BIN')


def check_font(report: Report):
    from rendering.frame_compositor import find_font
    try:
        report.add(OK, 'Font', find_font(config.FONT_PATH))
    except FileNotFoundError as exc:
        report.add(FAIL, 'Font', str(exc))


def _meminfo() -> Tuple[int, int]:
    """(total RAM MB, total swap MB) from /proc/meminfo."""
    values = {}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, rest = line.split(':', 1)
            values[key] = int(rest.split()[0]) // 1024
    except (OSError, ValueError):
        return 0, 0
    ram = values.get('MemTotal', 0)
    # Containers: the real limit is in the cgroup.
    for limit_file in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        try:
            limit = Path(limit_file).read_text().strip()
        except OSError:
            continue
        if limit.isdigit():
            ram = min(ram, int(limit) // (1024 * 1024))
    return ram, values.get('SwapTotal', 0)


def estimated_render_memory_mb() -> int:
    height = int(config.VIDEO_HEIGHT * config.RENDER_SCALE)
    mode = config.RENDER_DENOISE if config.RENDER_DENOISE in ('off', 'fast', 'accurate') else 'accurate'
    rows = sorted((h, mb) for (h, m), mb in MEMORY_TABLE.items() if m == mode)
    if not rows:
        return MEMORY_TABLE[(1920, 'accurate')]
    for h, mb in rows:
        if height <= h:
            return mb
    return int(rows[-1][1] * (height / rows[-1][0]) ** 2)


def check_resources(report: Report):
    ram, swap = _meminfo()
    need = estimated_render_memory_mb() + 350   # + Python pipeline, ffmpeg headroom, OS
    detail = (f'{ram} MB RAM + {swap} MB swap; current render settings need ~{need} MB '
              f'(scale {config.RENDER_SCALE}, denoise {config.RENDER_DENOISE})')
    if ram == 0:
        report.add(WARN, 'Memory', 'could not read /proc/meminfo')
    elif need <= ram:
        report.add(OK, 'Memory', detail)
    elif need <= ram + swap:
        report.add(WARN, 'Memory', detail + '; will use swap (slow). See README "Small servers"')
    else:
        report.add(FAIL, 'Memory', detail + '. Use RENDER_SCALE=0.5 RENDER_SAMPLES=12 RENDER_DENOISE=fast, '
                   'or add swap (./install.sh does both on small machines)')

    config.ensure_dirs()
    free_gb = shutil.disk_usage(config.DATA_DIR).free / 1e9
    report.add(OK if free_gb >= 3 else WARN, 'Disk', f'{free_gb:.1f} GB free in {config.DATA_DIR}'
               + ('' if free_gb >= 3 else ' (each video needs ~0.5 GB of temporary frames)'))
    for directory in (config.DATA_DIR, config.WORK_DIR, config.OUTPUT_DIR, config.LOG_DIR):
        if not os.access(directory, os.W_OK):
            report.add(FAIL, 'Permissions', f'{directory} is not writable')


def check_content(report: Report):
    stls = [p for p in config.STL_DIR.rglob('*') if p.suffix.lower() == '.stl'] if config.STL_DIR.exists() else []
    report.add(OK if stls else WARN, 'Models', f'{len(stls)} STL files in {config.STL_DIR}'
               + ('' if stls else ' (add some, e.g. from the ABC dataset)'))
    from rendering.video_compositor import list_audio
    tracks = list_audio(config.AUDIO_DIR)
    report.add(OK if tracks else WARN, 'Music', f'{len(tracks)} tracks in {config.AUDIO_DIR}'
               + ('' if tracks else ' (videos will be silent)'))


def check_services(report: Report):
    from content import llm
    report.add(OK if llm.llm_available() else WARN, 'Claude captions',
               'API key found' if llm.llm_available() else 'no ANTHROPIC_API_KEY; template captions will be used')
    from pipeline import build_publishers
    for name, publisher in build_publishers().items():
        ok, reason = publisher.configured()
        report.add(OK if ok else WARN, f'{name.capitalize()} publishing',
                   'connected' if ok else f'not set up ({reason}); videos go to data/exports for manual posting')


def render_test(report: Report):
    """Tiny real render + composite + encode with the configured settings."""
    from rendering.blender_runner import run_render
    from rendering.frame_compositor import FrameCompositor, OverlayPlan
    from rendering.video_compositor import VideoCompositor, pick_audio

    stls = sorted(p for p in config.STL_DIR.rglob('*') if p.suffix.lower() == '.stl') if config.STL_DIR.exists() else []
    if not stls:
        report.add(FAIL, 'Render test', f'no STL file in {config.STL_DIR} to test with')
        return
    started = time.time()
    with tempfile.TemporaryDirectory(prefix='cadbot-doctor-') as tmp:
        tmp = Path(tmp)
        job = {
            'project_dir': str(config.BASE_DIR), 'stl_path': str(min(stls, key=lambda p: p.stat().st_size)),
            'output_dir': str(tmp / 'raw'), 'width': 108, 'height': 192, 'total_frames': 6, 'fps': 6,
            'engine': config.RENDER_ENGINE, 'samples': 4, 'use_gpu': config.USE_GPU,
            'gpu_backend': config.GPU_BACKEND, 'threads': config.RENDER_THREADS,
            'denoise': config.RENDER_DENOISE, 'object_color': [0.4, 0.6, 0.9],
            'interior_color': [1.0, 0.4, 0.1], 'material': 'glossy_plastic', 'motion': 'turntable',
            'effect': None,
        }
        try:
            run_render(job, tmp, config.BLENDER_BIN, config.BLENDER_MODE, 900)
            compositor = FrameCompositor(216, 384, 6, config.FONT_PATH)
            compositor.compose(tmp / 'raw', tmp / 'final', OverlayPlan(
                (0.2, 0.2, 0.3), (0.05, 0.05, 0.1), hook='Render test', cta='It works'))
            encoder = VideoCompositor(6, threads=config.RENDER_THREADS,
                                      ffmpeg_bin=config.FFMPEG_BIN, ffprobe_bin=config.FFPROBE_BIN)
            video = encoder.encode(tmp / 'final', tmp / 'test.mp4', pick_audio(config.AUDIO_DIR), preset='veryfast')
            streams = {s['codec_type'] for s in encoder.probe(video)['streams']}
        except Exception as exc:   # noqa: BLE001 - report whatever broke
            report.add(FAIL, 'Render test', f'{exc.__class__.__name__}: {str(exc)[-400:]}')
            return
    report.add(OK, 'Render test', f"Blender → frames → MP4 ({'+'.join(sorted(streams))}) in {time.time() - started:.0f}s")


def run(render: bool = False) -> int:
    print('CAD-bot doctor\n')
    report = Report()
    check_python(report)
    check_blender(report)
    check_ffmpeg(report)
    check_font(report)
    check_resources(report)
    check_content(report)
    if not report.failed:
        check_services(report)
    if render and not report.failed:
        render_test(report)
    print()
    if report.failed:
        print('Problems found (✗). Fix them, then run `python main.py doctor` again.')
        return 1
    print('Ready.' + ('' if render else ' Run `python main.py doctor --render-test` for a real test render.'))
    return 0
