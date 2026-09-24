"""
Entry point executed inside Blender's Python.

    blender --background --factory-startup --python-exit-code 1 \
            --python rendering/blender_job.py -- job.json
    python rendering/blender_job.py job.json        # with the `bpy` pip module

Any exception exits non-zero so the pipeline sees the failure.
"""
import json
import sys
from pathlib import Path


def main():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    if not args:
        raise SystemExit('usage: blender_job.py <job.json>')
    job = json.loads(Path(args[0]).read_text())

    sys.path.insert(0, job['project_dir'])
    from rendering.blender_renderer import BlenderRenderer

    renderer = BlenderRenderer(
        engine=job.get('engine', 'CYCLES'),
        samples=job.get('samples', 32),
        use_gpu=job.get('use_gpu', True),
        gpu_backend=job.get('gpu_backend', 'AUTO'),
    )
    result = renderer.render(job)
    # Facts the video can state (e.g. the real part count), read back by the pipeline.
    (Path(job['output_dir']).parent / 'result.json').write_text(json.dumps(result))
    print('[cadbot] render finished')


if __name__ == '__main__':
    main()
