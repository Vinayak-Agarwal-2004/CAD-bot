"""
Look presets shared by the Blender side and the main process (no bpy import).
"""

# Principled BSDF settings per material look.
MATERIAL_PRESETS = {
    'matte_clay': {'Metallic': 0.0, 'Roughness': 0.65, 'Coat Weight': 0.0},
    'glossy_plastic': {'Metallic': 0.0, 'Roughness': 0.28, 'Coat Weight': 0.3},
    'brushed_metal': {'Metallic': 1.0, 'Roughness': 0.32, 'Coat Weight': 0.0},
    'ceramic': {'Metallic': 0.0, 'Roughness': 0.12, 'Coat Weight': 1.0},
}
