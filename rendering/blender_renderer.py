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
from typing import Callable, Dict, List, Optional, Sequence

import bpy
from mathutils import Matrix, Vector

from rendering.effects import cut_amount, explode_amount, explode_offsets
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
        return mat, bsdf

    # ------------------------------------------------------------ effects
    def add_cross_section(self, mat, bsdf, interior_rgb: Sequence[float]):
        """Turn the material into a cutaway. Everything on the camera side of a plane
        (world y < limit) is invisible, so as the part spins we always look into it,
        and the inside walls (back faces) show in a contrasting colour.
        Returns the limit socket to animate."""
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        output = nodes.get('Material Output')

        inside = nodes.new('ShaderNodeBsdfPrincipled')
        inside.inputs['Base Color'].default_value = (*interior_rgb, 1.0)
        inside.inputs['Roughness'].default_value = 0.55
        geometry = nodes.new('ShaderNodeNewGeometry')
        faces = nodes.new('ShaderNodeMixShader')           # front faces / back faces
        links.new(geometry.outputs['Backfacing'], faces.inputs['Fac'])
        links.new(bsdf.outputs['BSDF'], faces.inputs[1])
        links.new(inside.outputs['BSDF'], faces.inputs[2])

        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(geometry.outputs['Position'], split.inputs['Vector'])   # world space
        limit = nodes.new('ShaderNodeValue')
        limit.outputs[0].default_value = -10.0
        in_front = nodes.new('ShaderNodeMath')
        in_front.operation = 'LESS_THAN'
        links.new(split.outputs['Y'], in_front.inputs[0])      # the camera looks along +y
        links.new(limit.outputs[0], in_front.inputs[1])

        transparent = nodes.new('ShaderNodeBsdfTransparent')
        clip = nodes.new('ShaderNodeMixShader')
        links.new(in_front.outputs[0], clip.inputs['Fac'])
        links.new(faces.outputs['Shader'], clip.inputs[1])
        links.new(transparent.outputs['BSDF'], clip.inputs[2])
        links.new(clip.outputs['Shader'], output.inputs['Surface'])
        return limit.outputs[0]

    def fix_normals(self, obj):
        """Point normals outwards so the cutaway's inside/outside colouring is right."""
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

    def split_parts(self, obj, max_parts: int = 40) -> List:
        """Separate into loose parts (each disconnected body), origins at their centres."""
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=1e-6)   # STL is a triangle soup
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
        parts = [o for o in bpy.context.selected_objects if o.type == 'MESH']
        if len(parts) < 2:
            raise RuntimeError('model is a single piece; nothing to explode')
        if len(parts) > max_parts:
            raise RuntimeError(f'{len(parts)} loose parts; too many for an exploded view')
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        return parts

    # ------------------------------------------------------------ camera & light
    def setup_camera(self, scene, coords: Sequence[Vector], width: int, height: int, lens_mm: float,
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
    def animate(self, scene, objects: List, camera, total_frames: int, fps: int,
                motion: str, tilt_swing_deg: float,
                per_frame: Optional[Callable[[int, float], None]] = None):
        """Keyframe every frame so the motion is exact and loops seamlessly.

        turntable: one full Z turn plus a sine tilt; frame N+1 == frame 1.
        reveal:    same, but the camera starts close on the model and pulls
                   back over the first ~1.2 s (a hook that invites a re-watch).
        per_frame(frame, seconds) keyframes effect state (cut plane, exploded parts).
        """
        scene.frame_start = 1
        scene.frame_end = total_frames
        scene.render.fps = fps

        pivot = bpy.data.objects.new('Pivot', None)
        scene.collection.objects.link(pivot)
        for obj in objects:
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
            if per_frame:
                per_frame(frame, (frame - 1) / fps)

        for anim_obj in (pivot, camera):
            if anim_obj.animation_data and anim_obj.animation_data.action:
                for fcurve in anim_obj.animation_data.action.fcurves:
                    for key in fcurve.keyframe_points:
                        key.interpolation = 'LINEAR'

    # ------------------------------------------------------------ entry point
    def render(self, job: Dict) -> Dict:
        output_dir = Path(job['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob('frame_*.png'):
            stale.unlink()

        width, height = job['width'], job['height']
        scene = self.reset_scene()
        self.configure_render(scene, width, height)

        obj = self.import_stl(Path(job['stl_path']))
        self.normalize(obj)
        effect = job.get('effect')
        total, fps = job['total_frames'], job['fps']
        duration = total / fps
        result: Dict = {'effect': effect}

        if effect == 'cross_section':
            self.fix_normals(obj)
        mat, bsdf = self.apply_material(obj, job['object_color'], job.get('material', 'glossy_plastic'))
        objects = [obj]
        coords = [v.co.copy() for v in obj.data.vertices]
        per_frame = None

        if effect == 'cross_section':
            limit = self.add_cross_section(mat, bsdf, job.get('interior_color', (0.95, 0.35, 0.1)))
            closed = max(c.length for c in coords) + 0.05   # plane in front of the model = nothing cut

            def animate_cut(frame, seconds):
                # Slides from in front of the model to its centre, then back.
                limit.default_value = -closed * (1 - cut_amount(seconds, duration))
                limit.keyframe_insert('default_value', frame=frame)
            per_frame = animate_cut

        elif effect == 'explode':
            objects = self.split_parts(obj)
            result['parts'] = len(objects)
            homes = [o.location.copy() for o in objects]
            offsets = [Vector(v) for v in explode_offsets([tuple(h) for h in homes])]
            # Frame the camera on the exploded state so nothing flies out of shot.
            coords = [v.co + h + off for o, h, off in zip(objects, homes, offsets) for v in o.data.vertices]
            coords += [v.co + h for o, h in zip(objects, homes) for v in o.data.vertices]

            def animate_explode(frame, seconds):
                amount = explode_amount(seconds, duration)
                for part, home, off in zip(objects, homes, offsets):
                    part.location = home + off * amount
                    part.keyframe_insert('location', frame=frame)
            per_frame = animate_explode

        camera, _ = self.setup_camera(
            scene, coords, width, height, job.get('lens_mm', 50.0), job.get('elevation_deg', 22.0),
            job.get('tilt_swing_deg', 12.0), job.get('distance_margin', 1.1))
        self.setup_lighting(scene)
        self.animate(scene, objects, camera, total, fps, job.get('motion', 'turntable'),
                     job.get('tilt_swing_deg', 12.0), per_frame)

        scene.render.filepath = str(output_dir / 'frame_')
        bpy.ops.render.render(animation=True)

        rendered = sorted(output_dir.glob('frame_*.png'))
        if len(rendered) != job['total_frames']:
            raise RuntimeError(f"expected {job['total_frames']} frames, got {len(rendered)}")
        return result
