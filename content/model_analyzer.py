"""
Mesh analysis: facts for captions and an "interest" score for picking
which models are worth turning into videos.

A plain cube or a flat washer gets scrolled past. Parts with holes, varied
curvature and a balanced silhouette hold attention, so they render first.
"""
import hashlib
import math
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import trimesh


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(str(path), force='mesh', process=True)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f'{path.name}: no triangles found')
    return mesh


def analyze_mesh(mesh: trimesh.Trimesh) -> Dict:
    extents = np.asarray(mesh.extents, dtype=float)
    ordered = np.sort(extents)[::-1]  # longest first
    longest = float(ordered[0]) or 1.0

    # Holes/handles: genus from the Euler characteristic of a closed surface.
    genus = None
    if mesh.is_watertight:
        genus = max(0, int(round((2 - mesh.euler_number) / 2)))

    # How much of the surface bends: share of edges with a noticeable fold.
    try:
        angles = mesh.face_adjacency_angles
        sharp_fraction = float(np.mean(angles > math.radians(20))) if len(angles) else 0.0
        curved_fraction = float(np.mean((angles > math.radians(1)) & (angles <= math.radians(20)))) if len(angles) else 0.0
    except Exception:
        sharp_fraction = curved_fraction = 0.0

    volume = float(mesh.volume) if mesh.is_watertight else None
    bbox_volume = float(np.prod(extents)) or 1.0
    solidity = abs(volume) / bbox_volume if volume else None

    return {
        'triangles': int(len(mesh.faces)),
        'vertices': int(len(mesh.vertices)),
        'extents': [round(float(e), 4) for e in extents],
        'aspect_ratio': round(longest / max(float(ordered[-1]), 1e-9), 2),
        'watertight': bool(mesh.is_watertight),
        'genus': genus,
        'bodies': int(mesh.body_count),
        'surface_area': round(float(mesh.area), 4),
        'volume': round(volume, 4) if volume is not None else None,
        'solidity': round(solidity, 3) if solidity is not None else None,
        'sharp_edge_fraction': round(sharp_fraction, 3),
        'curved_edge_fraction': round(curved_fraction, 3),
    }


def interest_score(stats: Dict) -> float:
    """0-100. Rewards visual complexity and balanced proportions."""
    score = 0.0
    # Detail: diminishing returns on triangle count (log scale, caps ~200k).
    score += min(30.0, 6.0 * math.log10(max(stats['triangles'], 1)) - 6.0)
    # Curved surfaces catch highlights nicely in a turntable.
    score += 25.0 * min(1.0, stats['curved_edge_fraction'] * 2.5)
    # Some crisp features read well, a wall of them is noise.
    sharp = stats['sharp_edge_fraction']
    score += 10.0 * (1.0 - abs(sharp - 0.15) / 0.85)
    # Holes and handles make people wonder what the part is for.
    if stats['genus']:
        score += min(15.0, 5.0 * stats['genus'])
    # Needle-thin or pancake-flat parts look bad in a 9:16 frame.
    aspect = stats['aspect_ratio']
    score += 15.0 if aspect <= 4 else max(0.0, 15.0 - 3.0 * (aspect - 4))
    # Low solidity = interesting silhouette (brackets, frames) vs a block.
    if stats['solidity'] is not None:
        score += 5.0 * (1.0 - min(1.0, stats['solidity']))
    return round(max(0.0, min(100.0, score)), 2)


def evaluate(path: Path, min_triangles: int, max_triangles: int) -> Tuple[Dict, float, str]:
    """Return (stats, score, status) where status is 'pending' or 'rejected'."""
    stats = analyze_mesh(load_mesh(path))
    score = interest_score(stats)
    reasons = []
    if stats['triangles'] < min_triangles:
        reasons.append(f"too simple ({stats['triangles']} triangles)")
    if stats['triangles'] > max_triangles:
        reasons.append(f"too heavy ({stats['triangles']} triangles)")
    if stats['aspect_ratio'] > 25:
        reasons.append(f"degenerate proportions (aspect {stats['aspect_ratio']})")
    stats['reject_reasons'] = reasons
    return stats, score, 'rejected' if reasons else 'pending'
