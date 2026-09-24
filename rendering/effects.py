"""
Timing curves for the animated effects (no bpy import, so they're testable).

Every curve is 0 at the start and back to 0 at the end, so the effect
closes before the turntable loops and the video still repeats seamlessly.
"""
import math
from typing import List, Sequence, Tuple


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def open_hold_close(t: float, duration: float, open_at: float, open_for: float,
                    close_for: float, tail: float = 0.15) -> float:
    """0 -> 1 starting at `open_at`, hold, then 1 -> 0 ending `tail` seconds before the end."""
    close_end = duration - tail
    close_start = close_end - close_for
    if t <= open_at or t >= close_end:
        return 0.0
    if t < open_at + open_for:
        return smoothstep((t - open_at) / open_for)
    if t > close_start:
        return smoothstep((close_end - t) / close_for)
    return 1.0


def cut_amount(t: float, duration: float) -> float:
    """Cross-section: the cut opens right after the hook lands, closes near the end."""
    return open_hold_close(t, duration, open_at=0.9, open_for=1.4, close_for=1.0)


def explode_amount(t: float, duration: float) -> float:
    """Exploded view: parts fly out after a beat, reassemble for the loop."""
    return open_hold_close(t, duration, open_at=1.0, open_for=1.3, close_for=1.1)


def explode_offsets(centers: Sequence[Tuple[float, float, float]], strength: float = 0.55
                    ) -> List[Tuple[float, float, float]]:
    """Direction each part moves when exploded, scaled to the (normalised) model size.

    Parts move away from the model's centre, biased vertically so the exploded
    view uses the tall 9:16 frame instead of spilling off the sides. Parts sitting
    at the centre are spread by their rank in height so none stay stacked.
    """
    if not centers:
        return []
    n = len(centers)
    rank = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: centers[i][2]))}
    offsets = []
    for i, (x, y, z) in enumerate(centers):
        spread = (rank[i] - (n - 1) / 2) / max(1, n - 1)   # -0.5 .. 0.5 by height
        dx, dy, dz = x * 0.6, y * 0.6, z * 1.6 + spread * 1.2
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            dx, dy, dz, length = 0.0, 0.0, 1.0, 1.0
        offsets.append((dx / length * strength, dy / length * strength, dz / length * strength))
    return offsets
