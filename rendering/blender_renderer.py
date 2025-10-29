"""
Blender-based 3D rendering engine for STL files
This script must be run with Blender's Python interpreter
"""
import bpy
import math
import sys
from pathlib import Path
from typing import Tuple, Optional

class BlenderRenderer:
    def __init__(self, render_samples: int = 128, use_gpu: bool = True):
        self.render_samples = render_samples
        self.use_gpu = use_gpu
        self.setup_blender()

    def setup_blender(self):
        """Configure Blender rendering settings"""
        scene = bpy.context.scene

        # Set render engine
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = self.render_samples
        scene.cycles.use_denoising = False

        # GPU settings
        if self.use_gpu:
            scene.cycles.device = 'GPU'
            prefs = bpy.context.preferences.addons['cycles'].preferences
            prefs.compute_device_type = 'CUDA'  # or 'OPTIX' for RTX cards
            prefs.get_devices()
            for device in prefs.devices:
                device.use = True

        # Color management
        scene.view_settings.view_transform = 'Filmic'
        scene.view_settings.look = 'Medium High Contrast'

        # Output settings
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGB'
        scene.render.image_settings.color_depth = '8'

    def clear_scene(self):
        """Remove all objects, cameras, and lights from scene"""
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

        # Clear orphaned data
        for block in bpy.data.meshes:
            if block.users == 0:
                bpy.data.meshes.remove(block)

        for block in bpy.data.materials:
            if block.users == 0:
                bpy.data.materials.remove(block)

    def import_stl(self, stl_path: Path) -> bpy.types.Object:
        """Import STL file and return the object"""
        # Import STL (Blender 4.0+ syntax)
        bpy.ops.wm.stl_import(filepath=str(stl_path))

        # Get the imported object (most recent)
        obj = bpy.context.selected_objects[0]

        # Center the object at world origin
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        obj.location = (0, 0, 0)

        return obj

    def apply_material(self, obj: bpy.types.Object, 
                       color_rgb: Tuple[float, float, float]):
        """Apply solid color material to object"""
        # Create material
        mat = bpy.data.materials.new(name="ObjectMaterial")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()

        # Create shader nodes
        node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
        node_bsdf.location = (0, 0)
        node_bsdf.inputs['Base Color'].default_value = (*color_rgb, 1.0)
        node_bsdf.inputs['Metallic'].default_value = 0.1
        node_bsdf.inputs['Roughness'].default_value = 0.3
        node_bsdf.inputs['Specular IOR Level'].default_value = 0.5

        node_output = nodes.new(type='ShaderNodeOutputMaterial')
        node_output.location = (200, 0)

        # Link nodes
        links = mat.node_tree.links
        links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])

        # Assign material to object
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

    def setup_world_background(self, background_rgb: Tuple[float, float, float]):
        """Setup world background color"""
        world = bpy.context.scene.world
        world.use_nodes = True
        nodes = world.node_tree.nodes

        # Get background node
        bg_node = nodes.get('Background')
        if bg_node:
            bg_node.inputs['Color'].default_value = (*background_rgb, 1.0)
            bg_node.inputs['Strength'].default_value = 1.0

    def setup_camera(self, obj: bpy.types.Object, 
                     distance_multiplier: float = 2.5,
                     elevation_angle: float = 20) -> bpy.types.Object:
        """
        Setup camera with orbit around object

        Args:
            obj: Target object
            distance_multiplier: Distance from object (multiplier of object size)
            elevation_angle: Camera elevation in degrees

        Returns:
            Camera object
        """
        # Calculate object dimensions
        dimensions = obj.dimensions
        max_dim = max(dimensions)

        # Calculate camera distance
        distance = max_dim * distance_multiplier

        # Create camera
        bpy.ops.object.camera_add()
        camera = bpy.context.active_object
        camera.name = 'RenderCamera'

        # Set camera as active
        bpy.context.scene.camera = camera

        # Position camera
        elevation_rad = math.radians(elevation_angle)
        camera.location.x = distance * math.cos(elevation_rad)
        camera.location.y = 0
        camera.location.z = distance * math.sin(elevation_rad)

        # Point camera at object
        direction = obj.location - camera.location
        rot_quat = direction.to_track_quat('-Z', 'Y')
        camera.rotation_euler = rot_quat.to_euler()

        # Create empty at object center for orbit parent
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=obj.location)
        empty = bpy.context.active_object
        empty.name = 'OrbitEmpty'

        # Parent camera to empty
        camera.parent = empty

        # Camera settings
        camera.data.lens = 50  # 50mm lens
        camera.data.sensor_width = 36  # Full frame sensor
        camera.data.clip_end = distance * 10

        return camera

    def setup_lighting(self):
        """Setup three-point lighting for object"""
        # Key light (main light)
        bpy.ops.object.light_add(type='AREA', location=(5, -5, 8))
        key_light = bpy.context.active_object
        key_light.name = 'KeyLight'
        key_light.data.energy = 300
        key_light.data.size = 5
        key_light.rotation_euler = (math.radians(45), 0, math.radians(45))

        # Fill light (softer, opposite side)
        bpy.ops.object.light_add(type='AREA', location=(-5, 5, 5))
        fill_light = bpy.context.active_object
        fill_light.name = 'FillLight'
        fill_light.data.energy = 150
        fill_light.data.size = 5
        fill_light.rotation_euler = (math.radians(45), 0, math.radians(-135))

        # Rim light (back light for edge definition)
        bpy.ops.object.light_add(type='AREA', location=(0, 6, 6))
        rim_light = bpy.context.active_object
        rim_light.name = 'RimLight'
        rim_light.data.energy = 200
        rim_light.data.size = 4
        rim_light.rotation_euler = (math.radians(60), 0, 0)

    def animate_camera_orbit(self, total_frames: int,
                            fps: int = 30,
                            axis: str = 'Z'):
        """
        Simple camera orbit through all axes, returning to start

        Path: Z → XZ → X → XY → Y → YZ → back to Z

        This creates a smooth loop showing the model from all angles
        and ends at the same orientation it started.

        Args:
            total_frames: Total number of frames (e.g., 300 for 10 seconds @ 30fps)
            fps: Frames per second
            axis: Ignored (kept for compatibility)
        """
        # Setup scene animation parameters
        scene = bpy.context.scene
        scene.frame_start = 1
        scene.frame_end = total_frames
        scene.render.fps = fps

        # Get the empty object that controls camera rotation
        # The camera is parented to this empty, so rotating the empty rotates the camera
        empty = bpy.data.objects.get('OrbitEmpty')
        if not empty:
            raise ValueError("OrbitEmpty not found. Setup camera first.")

        # We will divide the animation into 6 equal segments
        # Each segment shows a different view of the model
        num_segments = 6
        frames_per_segment = total_frames // num_segments

        # Rotation amounts for each axis (in radians)
        # We'll rotate 60 degrees per segment to complete 360 degrees total
        rotation_amount = math.radians(60)  # 60 degrees

        # SEGMENT 0: Starting position (frame 1)
        # No rotation yet - model shown from initial angle
        frame_number = 1
        x_rotation = 0.0
        y_rotation = 0.0
        z_rotation = 0.0

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: Start position (0°, 0°, 0°)")

        # SEGMENT 1: Rotate around Z axis
        # This shows the model spinning horizontally
        frame_number = frames_per_segment * 1
        z_rotation += rotation_amount  # Add 60° to Z

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: Z axis rotation")

        # SEGMENT 2: Rotate around X and Z axes (XZ plane)
        # This adds vertical tilt while continuing horizontal spin
        frame_number = frames_per_segment * 2
        x_rotation += rotation_amount  # Add 60° to X
        z_rotation += rotation_amount  # Add 60° to Z

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: XZ plane rotation")

        # SEGMENT 3: Rotate around X axis
        # This continues the vertical tilt
        frame_number = frames_per_segment * 3
        x_rotation += rotation_amount  # Add 60° to X

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: X axis rotation")

        # SEGMENT 4: Rotate around X and Y axes (XY plane)
        # This adds side-to-side rotation
        frame_number = frames_per_segment * 4
        x_rotation += rotation_amount  # Add 60° to X
        y_rotation += rotation_amount  # Add 60° to Y

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: XY plane rotation")

        # SEGMENT 5: Rotate around Y axis
        # This continues the side-to-side motion
        frame_number = frames_per_segment * 5
        y_rotation += rotation_amount  # Add 60° to Y

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: Y axis rotation")

        # SEGMENT 6: Rotate around Y and Z axes (YZ plane)
        # This brings us back toward the starting position
        frame_number = frames_per_segment * 6
        y_rotation += rotation_amount  # Add 60° to Y
        z_rotation += rotation_amount  # Add 60° to Z

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: YZ plane rotation")

        # FINAL POSITION: Complete the loop
        # Return to starting orientation (360° = 0°)
        # We've rotated 360° total, so we're back at the start
        frame_number = total_frames
        x_rotation = math.radians(360)  # Full rotation = back to start
        y_rotation = math.radians(360)  # Full rotation = back to start  
        z_rotation = math.radians(360)  # Full rotation = back to start

        empty.rotation_euler = (x_rotation, y_rotation, z_rotation)
        empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)
        print(f"Frame {frame_number}: Back to start (360°, 360°, 360°)")

        # Set all keyframes to use linear interpolation
        # This means the rotation speed is constant (no acceleration/deceleration)
        for fcurve in empty.animation_data.action.fcurves:
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = 'LINEAR'

        print(f"Camera animation complete: {num_segments} segments, {total_frames} frames")

    def render_frame_sequence(self, output_dir: Path, 
                            width: int = 1080, 
                            height: int = 1920):
        """
        Render complete frame sequence

        Args:
            output_dir: Directory to save frames
            width: Frame width in pixels
            height: Frame height in pixels
        """
        scene = bpy.context.scene
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100

        # Set output path with frame number placeholder
        output_dir.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output_dir / 'frame_')

        # Render animation
        bpy.ops.render.render(animation=True, write_still=True)

    def render_video(self, stl_path: Path, 
                    output_dir: Path,
                    object_color: Tuple[float, float, float],
                    background_color: Tuple[float, float, float],
                    total_frames: int = 750,
                    fps: int = 30,
                    width: int = 1080,
                    height: int = 1920) -> Path:
        """
        Complete rendering pipeline

        Returns:
            Path to render output directory
        """
        # Clear scene
        self.clear_scene()

        # Import STL
        obj = self.import_stl(stl_path)

        # Apply colors
        self.apply_material(obj, object_color)
        self.setup_world_background(background_color)

        # Setup camera and lighting
        self.setup_camera(obj)
        self.setup_lighting()

        # Animate
        self.animate_camera_orbit(total_frames, fps, axis='Z')

        # Render
        self.render_frame_sequence(output_dir, width, height)

        return output_dir
