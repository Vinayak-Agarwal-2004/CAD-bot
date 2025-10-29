#!/usr/bin/env python3
"""
Cross-platform setup script for STL to Video Rendering Pipeline
"""
import os
import sys
from pathlib import Path

def create_directory_structure():
    """Create the project directory structure"""
    print("="*50)
    print("STL to Video Pipeline - Setup Script")
    print("="*50)
    print()

    # Project directory
    project_dir = Path("stl_to_video")
    print(f"Creating project directory: {project_dir}")
    project_dir.mkdir(exist_ok=True)

    # Subdirectories
    subdirs = [
        "database",
        "rendering",
        "utils",
        "data/stl_files",
        "data/renders",
        "data/output_videos",
        "logs"
    ]

    print("Creating directory structure...")
    for subdir in subdirs:
        dir_path = project_dir / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {subdir}/")

    # Create __init__.py files
    print("\nCreating package initializers...")
    init_files = {
        "database/__init__.py": '"""Database package for STL file tracking and render job management"""',
        "rendering/__init__.py": '"""Rendering package for color generation, 3D rendering, and video composition"""',
        "utils/__init__.py": '"""Utilities package for logging and helper functions"""'
    }

    for file_path, content in init_files.items():
        full_path = project_dir / file_path
        with open(full_path, 'w') as f:
            f.write(content)
        print(f"  ✓ {file_path}")

    print()
    print("✓ Directory structure created successfully!")
    print()
    print("="*50)
    print("NEXT STEPS")
    print("="*50)
    print()
    print("1. Copy the following files to stl_to_video/:")
    print("   - requirements.txt")
    print("   - config.py")
    print("   - main.py")
    print("   - README.md")
    print()
    print("2. Copy module files:")
    print("   - database_db_manager.py → database/db_manager.py")
    print("   - rendering_color_generator.py → rendering/color_generator.py")
    print("   - rendering_blender_renderer.py → rendering/blender_renderer.py")
    print("   - rendering_video_compositor.py → rendering/video_compositor.py")
    print("   - utils_logger.py → utils/logger.py")
    print()
    print("3. Install dependencies:")
    print("   cd stl_to_video")
    print("   pip install -r requirements.txt")
    print()
    print("4. Add STL files to data/stl_files/")
    print()
    print("5. Run the pipeline:")
    print("   python main.py all")
    print()
    print("="*50)

if __name__ == "__main__":
    try:
        create_directory_structure()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
