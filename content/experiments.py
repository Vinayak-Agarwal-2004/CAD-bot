"""
Learns what gets views on this account and steers new videos towards it.

Every video is a combination of choices (format, hook, palette, material,
text style, length) and every post has a posting hour. Once posts are old
enough (METRICS_MATURITY_HOURS), each choice is scored by how far its posts'
views sit above or below the account's typical post on that platform, in
log space so one viral hit doesn't drown out everything else.

Choices are picked with Thompson sampling: options that are doing well get
used more, untried or uncertain options still get tried. A small random
share (exploration_rate) keeps checking old options, since what works drifts.
"""
import math
import random
import statistics
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

import config
from content.formats import FORMATS, TEXT_STYLES
from rendering.color_generator import PALETTE_FAMILIES
from rendering.presets import MATERIAL_PRESETS

DIMENSIONS: Dict[str, List] = {
    'format': list(FORMATS),
    'palette': list(PALETTE_FAMILIES),
    'material': list(MATERIAL_PRESETS),
    'text_style': list(TEXT_STYLES),
    'duration': list(config.VIDEO_DURATIONS),
}

PRIOR_SD = 1.0     # prior uncertainty for an arm, in log-views units


def hook_arms(fmt: str, include_llm: bool = False) -> List[str]:
    """Template hooks by index, plus 'llm' (a hook Claude writes for that specific video)."""
    arms = [f'{fmt}:{i}' for i in range(len(FORMATS[fmt]['hooks']))]
    return arms + [f'{fmt}:llm'] if include_llm else arms


def relative_rewards(rows: Sequence[Dict]) -> List[Dict]:
    """Attach 'reward' = log1p(views) minus the platform median of log1p(views)."""
    by_platform = defaultdict(list)
    for row in rows:
        if row.get('views') is not None:
            by_platform[row['platform']].append(math.log1p(row['views']))
    medians = {p: statistics.median(v) for p, v in by_platform.items() if v}
    out = []
    for row in rows:
        if row.get('views') is None or row['platform'] not in medians:
            continue
        out.append({**row, 'reward': math.log1p(row['views']) - medians[row['platform']]})
    return out


class ExperimentEngine:
    def __init__(self, performance_rows: Sequence[Dict], exploration_rate: float = 0.2,
                 rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.exploration_rate = exploration_rate
        self.rows = relative_rewards(performance_rows)
        rewards = [r['reward'] for r in self.rows]
        self.noise_sd = max(0.5, statistics.pstdev(rewards)) if len(rewards) > 1 else 1.0

    # ------------------------------------------------------------ statistics
    def arm_stats(self, dimension: str, platform: Optional[str] = None) -> Dict[str, Dict]:
        stats: Dict[str, Dict] = defaultdict(lambda: {'n': 0, 'sum': 0.0, 'views': []})
        for row in self.rows:
            if platform and row['platform'] != platform:
                continue
            if dimension == 'hour':
                key = row.get('hour')
            elif dimension == 'hook':
                key = f"{row['variant'].get('format')}:{row['variant'].get('hook_index')}"
            else:
                key = row['variant'].get(dimension)
            if key is None:
                continue
            s = stats[str(key)]
            s['n'] += 1
            s['sum'] += row['reward']
            s['views'].append(row['views'])
        return {k: {'n': v['n'], 'mean': v['sum'] / v['n'],
                    'median_views': statistics.median(v['views'])} for k, v in stats.items()}

    def _sample(self, arms: Sequence, stats: Dict[str, Dict]):
        if self.rng.random() < self.exploration_rate:
            return self.rng.choice(list(arms))
        best, best_draw = None, -math.inf
        for arm in arms:
            s = stats.get(str(arm))
            if s:
                # Normal posterior with a zero-mean prior (= "an average post").
                precision = 1 / PRIOR_SD ** 2 + s['n'] / self.noise_sd ** 2
                mean = (s['mean'] * s['n'] / self.noise_sd ** 2) / precision
                draw = self.rng.gauss(mean, 1 / math.sqrt(precision))
            else:
                draw = self.rng.gauss(0.0, PRIOR_SD)
            if draw > best_draw:
                best, best_draw = arm, draw
        return best

    # ------------------------------------------------------------ choices
    def choose_variant(self, overrides: Optional[Dict] = None, include_llm_hook: bool = False) -> Dict:
        overrides = overrides or {}
        variant = {}
        for dim, arms in DIMENSIONS.items():
            variant[dim] = overrides.get(dim) or self._sample(arms, self.arm_stats(dim))
        hook_key = self._sample(hook_arms(variant['format'], include_llm_hook), self.arm_stats('hook'))
        hook_index = str(overrides.get('hook_index', hook_key.split(':')[1]))
        variant['hook_index'] = int(hook_index) if hook_index.isdigit() else hook_index
        variant['motion'] = FORMATS[variant['format']]['motion']
        return variant

    def choose_hour(self, platform: str, hours: Sequence[int]) -> int:
        return int(self._sample(list(hours), self.arm_stats('hour', platform)))

    # ------------------------------------------------------------ reporting
    def report(self) -> Dict[str, Dict[str, Dict]]:
        dims = list(DIMENSIONS) + ['hook', 'hour']
        return {dim: dict(sorted(self.arm_stats(dim).items(), key=lambda kv: -kv[1]['mean']))
                for dim in dims}
