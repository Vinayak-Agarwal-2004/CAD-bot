"""
Blender scene setup and rendering for a single STL.

Runs inside Blender's Python (the `blender` executable or the `bpy` pip
module) via rendering/blender_job.py, never imported by the main process.

The object turns on a turntable in front of a fixed camera and lights, so
highlights sweep across the surface and the last frame flows straight into
the first (seamless loop, which drives re-watches). Frames are rendered
with a transparent background; the background is composited afterwards.
"""
import math
from pathlib import Path
from typing import Dict, Sequence

import bpy
from mathutils import Matrix, Vector

from rendering.presets import MATERIAL_PRESETS

# Normalised size: the model's bounding sphere gets this radius, so camera,
# lights and clipping work the same for a 2 mm screw and a 2 m frame.
MODEL_RADIUS = 1.0



class BlenderRenderer:
    def __init__(self, engine: str = 'CYCLES', samples: int = 32, use_gpu: bool = True,
                 gpu_backend: str = 'AUTO'):
        self.engine = engine
        self.samples = samples
        self.use_gpu = use_gpu
        self.gpu_backend = gpu_backend

    # ------------------------------------------------------------ scene
    def reset_scene(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        if scene.world is None:
            scene.world = bpy.data.worlds.new('World')
        return scene

    def configure_render(self, scene, width: int, height: int):
        scene.render.engine = self.engine
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.use_persistent_data = True
        settings = scene.render.image_settings
        settings.file_format = 'PNG'
        settings.color_mode = 'RGBA'
        settings.color_depth = '8'
        settings.compression = 15

        # AgX (Blender 4+) handles bright highlights better than Filmic.
        view = scene.view_settings
        transforms = {item.identifier for item in view.bl_rna.properties['view_transform'].enum_items}
        view.view_transform = 'AgX' if 'AgX' in transforms else 'Filmic'
        try:
            view.look = 'AgX - Medium High Contrast' if view.view_transform == 'AgX' else 'Medium High Contrast'
        except TypeError:
            view.look = 'None'

        if self.engine == 'CYCLES':
            cycles = scene.cycles
            cycles.samples = self.samples
            cycles.use_adaptive_sampling = True
            cycles.use_denoising = True
            cycles.max_bounces = 6
            cycles.device = 'GPU' if self.use_gpu and self._enable_gpu() else 'CPU'
            print(f'[cadbot] Cycles device: {cycles.device}')

    def _enable_gpu(self) -> bool:
        """Turn on the first GPU backend that has devices. False = use CPU."""
        try:
            prefs = bpy.context.preferences.addons['cycles'].preferences
        except KeyError:
            return False
        backends = ['OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'] if self.gpu_backend == 'AUTO' else [self.gpu_backend]
        for backend in backends:
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue  # backend not compiled into this Blender
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for device in prefs.devices:
                    device.use = device.type == backend
                return True
        return False

    # ------------------------------------------------------------ model
    def import_stl(self, stl_path: Path):
        before = set(bpy.data.objects)
        if hasattr(bpy.ops.wm, 'stl_import'):          # Blender 4.1+
            bpy.ops.wm.stl_import(filepath=str(stl_path))
        else:                                          # Blender <= 4.0
            bpy.ops.import_mesh.stl(filepath=str(stl_path))
        new_objects = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
        if not new_objects:
            raise RuntimeError(f'STL import produced no mesh: {stl_path}')
        obj = new_objects[0]
        bpy.context.view_layer.objects.active = obj
        return obj

    def normalize(self, obj):
        """Centre on the bounding box and scale the bounding sphere to MODEL_RADIUS."""
        mesh = obj.data
        coords = [v.co for v in mesh.vertices]
        lo = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
        hi = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
        center = (lo + hi) / 2
        radius = max((c - center).length for c in coords) or 1.0
        scale = MODEL_RADIUS / radius
        for v in mesh.vertices:
            v.co = (v.co - center) * scale

        # Stand the longest axis upright: the turntable spins around Z, so a
        # tall model fills a 9:16 frame while a wide one would be tiny.
        size = hi - lo
        longest = max(range(3), key=lambda i: size[i])
        if longest == 0:
            mesh.transform(Matrix.Rotation(math.radians(90), 4, 'Y'))
        elif longest == 1:
            mesh.transform(Matrix.Rotation(math.radians(90), 4, 'X'))
        mesh.update()
        obj.location = (0, 0, 0)
        obj.rotation_euler = (0, 0, 0)
        obj.scale = (1, 1, 1)

        # CAD exports are triangle soups: smooth curved areas, keep hard edges.
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        if hasattr(bpy.ops.object, 'shade_smooth_by_angle'):   # 4.1+
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(30))
        else:
            bpy.ops.object.shade_smooth()
            mesh.use_auto_smooth = True
            mesh.auto_smooth_angle = math.radians(30)

    def apply_material(self, obj, color_rgb: Sequence[float], preset: str):
        mat = bpy.data.materials.new(name=f'cadbot_{preset}')
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*color_rgb, 1.0)
        for name, value in MATERIAL_PRESETS.get(preset, MATERIAL_PRESETS['glossy_plastic']).items():
            if name in bsdf.inputs:
                bsdf.inputs[name].default_value = value
        obj.data.materials.clear()
        obj.data.materials.append(mat)

    # ------------------------------------------------------------ camera & light
    def setup_camera(self, scene, obj, width: int, height: int, lens_mm: float,
                     elevation_deg: float, tilt_swing_deg: float, margin: float):
        """Place the camera so the spinning, tilting model fills the frame without clipping.

        Fits the turntable's real footprint (radius in XY, height in Z) rather than
        the bounding sphere, which would waste most of a tall 9:16 frame.
        """
        cam_data = bpy.data.cameras.new('Camera')
        cam_data.lens = lens_mm
        cam_data.sensor_fit = 'AUTO'
        camera = bpy.data.objects.new('Camera', cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

        # With AUTO fit the sensor width maps to the longer side (height in portrait).
        fov_long = 2 * math.atan(cam_data.sensor_width / (2 * lens_mm))
        fov_short = 2 * math.atan(math.tan(fov_long / 2) * min(width, height) / max(width, height))
        fov_h, fov_v = (fov_short, fov_long) if height >= width else (fov_long, fov_short)

        coords = [v.co for v in obj.data.vertices]
        r_xy = max(math.hypot(c.x, c.y) for c in coords) or MODEL_RADIUS
        half_z = max(abs(c.z) for c in coords) or MODEL_RADIUS
        elev = math.radians(elevation_deg)
        swing = math.radians(tilt_swing_deg)
        # Apparent vertical half-size over the whole tilt range.
        half_v = max(half_z * abs(math.cos(a)) + r_xy * abs(math.sin(a)) for a in (elev - swing, elev + swing))
        # A point at radius r seen from distance d spans at most r / sqrt(d^2 - r^2).
        distance = margin * max(r_xy / math.sin(fov_h / 2), half_v / math.sin(fov_v / 2))

        camera.location = (0, -distance * math.cos(elev), distance * math.sin(elev))
        camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        cam_data.clip_start = distance * 0.01
        cam_data.clip_end = distance * 10
        return camera, distance

    def setup_lighting(self, scene):
        """Soft three-point light fixed to the camera side, plus a dim neutral world."""
        def area(name, location, energy, size, color=(1, 1, 1)):
            light = bpy.data.lights.new(name, type='AREA')
            light.energy = energy
            light.size = size
            light.color = color
            obj = bpy.data.objects.new(name, light)
            obj.location = location
            obj.rotation_euler = (Vector((0, 0, 0)) - Vector(location)).to_track_quat('-Z', 'Y').to_euler()
            scene.collection.objects.link(obj)

        area('Key', (-3.5, -4.0, 4.5), 900, 4.0, (1.0, 0.97, 0.92))
        area('Fill', (4.5, -3.0, 1.5), 300, 5.0, (0.92, 0.96, 1.0))
        area('Rim', (0.5, 5.0, 3.5), 700, 3.0)

        world = scene.world
        world.use_nodes = True
        bg = world.node_tree.nodes.get('Background')
        bg.inputs['Color'].default_value = (0.5, 0.5, 0.5, 1.0)
        bg.inputs['Strength'].default_value = 0.35

    # ------------------------------------------------------------ animation
    def animate(self, scene, obj, camera, distance: float, total_frames: int, fps: int,
                motion: str, tilt_swing_deg: float):
        """Keyframe every frame so the motion is exact and loops seamlessly.

        turntable: one full Z turn plus a sine tilt; frame N+1 == frame 1.
        reveal:    same, but the camera starts close on the model and pulls
                   back over the first ~1.2 s (a hook that invites a re-watch).
        """
        scene.frame_start = 1
        scene.frame_end = total_frames
        scene.render.fps = fps

        pivot = bpy.data.objects.new('Pivot', None)
        scene.collection.objects.link(pivot)
        obj.parent = pivot

        base_location = camera.location.copy()
        reveal_frames = int(1.2 * fps)
        swing = math.radians(tilt_swing_deg)

        for frame in range(1, total_frames + 1):
            t = (frame - 1) / total_frames            # 0 <= t < 1
            pivot.rotation_euler = (swing * math.sin(2 * math.pi * t), 0.0, 2 * math.pi * t)
            pivot.keyframe_insert('rotation_euler', frame=frame)
            if motion == 'reveal':
                progress = min(1.0, (frame - 1) / reveal_frames)
                eased = 1 - (1 - progress) ** 3   # ease-out cubic
                camera.location = base_location * (0.45 + 0.55 * eased)
                camera.keyframe_insert('location', frame=frame)

        for anim_obj in (pivot, camera):
            if anim_obj.animation_data and anim_obj.animation_data.action:
                for fcurve in anim_obj.animation_data.action.fcurves:
                    for key in fcurve.keyframe_points:
                        key.interpolation = 'LINEAR'

    # ------------------------------------------------------------ entry point
    def render(self, job: Dict) -> Path:
        output_dir = Path(job['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob('frame_*.png'):
            stale.unlink()

        width, height = job['width'], job['height']
        scene = self.reset_scene()
        self.configure_render(scene, width, height)

        obj = self.import_stl(Path(job['stl_path']))
        self.normalize(obj)
        self.apply_material(obj, job['object_color'], job.get('material', 'glossy_plastic'))

        camera, distance = self.setup_camera(
            scene, obj, width, height, job.get('lens_mm', 50.0), job.get('elevation_deg', 22.0),
            job.get('tilt_swing_deg', 12.0), job.get('distance_margin', 1.1))
        self.setup_lighting(scene)
        self.animate(scene, obj, camera, distance, job['total_frames'], job['fps'],
                     job.get('motion', 'turntable'), job.get('tilt_swing_deg', 12.0))

        scene.render.filepath = str(output_dir / 'frame_')
        bpy.ops.render.render(animation=True)

        rendered = sorted(output_dir.glob('frame_*.png'))
        if len(rendered) != job['total_frames']:
            raise RuntimeError(f"expected {job['total_frames']} frames, got {len(rendered)}")
        return output_dir
