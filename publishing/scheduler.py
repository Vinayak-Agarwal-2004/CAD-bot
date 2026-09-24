"""
Assigns posting slots: a steady daily cadence per platform, at hours the
experiment engine has learned work (or is still testing).
"""
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo


def to_utc_naive(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def local_hour(utc_naive: datetime, tz: str) -> int:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).hour


def next_slot(existing_utc: Sequence[datetime], posts_per_day: int, hours: Sequence[int],
              tz: str, choose_hour: Callable[[List[int]], int], now_utc: Optional[datetime] = None,
              rng: Optional[random.Random] = None, horizon_days: int = 60) -> datetime:
    """First day (from today) with a free slot; returns a naive UTC datetime."""
    if posts_per_day <= 0:
        raise ValueError('posts_per_day must be positive')
    rng = rng or random.Random()
    zone = ZoneInfo(tz)
    now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(zone)
    earliest = now_local + timedelta(minutes=10)

    taken_by_day: Dict = {}
    for when in existing_utc:
        local = when.replace(tzinfo=timezone.utc).astimezone(zone)
        taken_by_day.setdefault(local.date(), set()).add(local.hour)

    for offset in range(horizon_days):
        day = (now_local + timedelta(days=offset)).date()
        taken = taken_by_day.get(day, set())
        if len(taken) >= posts_per_day:
            continue
        free = [h for h in hours if h not in taken
                and datetime(day.year, day.month, day.day, h, 59, tzinfo=zone) > earliest]
        if not free:
            continue
        hour = choose_hour(free)
        # A few minutes of jitter so posts don't all land exactly on the hour.
        minute = rng.randint(0, 14)
        slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if slot < earliest:
            slot = earliest
        return to_utc_naive(slot)
    raise RuntimeError(f'no free slot in the next {horizon_days} days')
