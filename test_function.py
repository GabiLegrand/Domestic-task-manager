from __future__ import annotations
from datetime import datetime, timedelta, time, date
import re
import os
from typing import List, Optional, Tuple, Dict, Set
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# Timezone config
# -----------------------------------------------------------------------------
load_dotenv()
TZ = os.getenv("TIMEZONE", "Europe/Helsinki")
TIMEZONE = ZoneInfo(TZ)

# -----------------------------------------------------------------------------
# Constants & parsing
# -----------------------------------------------------------------------------
DAY_MAP: Dict[str, int] = {
    "Lundi": 0,
    "Mardi": 1,
    "Mercredi": 2,
    "Jeudi": 3,
    "Vendredi": 4,
    "Samedi": 5,
    "Dimanche": 6,
}
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

class TimePatternService:
    def __init__(self):
        self.DAY_MAP = DAY_MAP
        self.TIMEZONE = TIMEZONE

    def _parse_preference(self, pref: str) -> Tuple[Optional[int], Optional[time]]:
        """Parse a single preference string.
        Returns (weekday, time) where weekday is int [0..6] or None; time is datetime.time or None.
        Accepted formats:
          - "<Day> <HH:MM:SS>"
          - "<Day>"
          - "<HH:MM:SS>"
        """
        parts = pref.split()
        if len(parts) == 2:
            day_str, t_str = parts
            if day_str not in self.DAY_MAP:
                raise ValueError(f"Unknown day in preference: {day_str}")
            return self.DAY_MAP[day_str], datetime.strptime(t_str, "%H:%M:%S").time()
        if _TIME_RE.match(pref):
            return None, datetime.strptime(pref, "%H:%M:%S").time()
        if pref in self.DAY_MAP:
            return self.DAY_MAP[pref], None
        raise ValueError(f"Invalid preference format: {pref}")

    # -----------------------------------------------------------------------------
    # Pattern building (recurrences)
    # -----------------------------------------------------------------------------
    def _build_patterns(self, start_preferences: List[str]) -> Set[Tuple[int, time]]:
        """Build canonical weekly patterns from user prefs, enforcing day restrictions."""
        parsed = [self._parse_preference(p) for p in start_preferences]
        day_time_by_day: Dict[int, List[time]] = {}
        day_only_days: Set[int] = set()
        times_only: List[time] = []
        for d, t in parsed:
            if d is not None and t is not None:
                day_time_by_day.setdefault(d, []).append(t)
            elif d is not None and t is None:
                day_only_days.add(d)
            elif d is None and t is not None:
                times_only.append(t)
        for d in day_time_by_day:
            day_time_by_day[d].sort()
        times_only.sort()
        allowed_days: Set[int] = set(day_time_by_day.keys()) | set(day_only_days)
        patterns: Set[Tuple[int, time]] = set()
        # Case 1: At least one day-based entry → restrict to those days only
        if allowed_days:
            # explicit day+time
            for d, times_list in day_time_by_day.items():
                for t in times_list:
                    patterns.add((d, t))
            # day-only → assign earliest from times_only or 00:00
            smallest_time = times_only[0] if times_only else time(0, 0, 0)
            for d in day_only_days:
                if d not in day_time_by_day:
                    patterns.add((d, smallest_time))
            # time-only values → apply only to allowed days without explicit time
            for d in allowed_days:
                if d not in day_time_by_day and d not in day_only_days and times_only:
                    for t in times_only:
                        patterns.add((d, t))
        # Case 2: No days specified → apply times-only to all days
        else:
            if times_only:
                for d in range(7):
                    for t in times_only:
                        patterns.add((d, t))
            else:
                for d in range(7):
                    patterns.add((d, time(0, 0, 0)))
        return patterns

    # -----------------------------------------------------------------------------
    # Occurrence helpers
    # -----------------------------------------------------------------------------
    def _combine(self, dt_date: date, t: time) -> datetime:
        return datetime.combine(dt_date, t, self.TIMEZONE)

    def _next_occurrence_after(self, moment: datetime, weekday: int, at_time: time) -> datetime:
        days_ahead = (weekday - moment.weekday()) % 7
        candidate_date = moment.date() + timedelta(days=days_ahead)
        candidate = self._combine(candidate_date, at_time)
        if candidate <= moment:
            candidate += timedelta(days=7)
        return candidate

    def _nearest_occurrence_to(self, anchor: datetime, weekday: int, at_time: time) -> Tuple[datetime, timedelta]:
        days_ahead = (weekday - anchor.weekday()) % 7
        next_date = anchor.date() + timedelta(days=days_ahead)
        next_occ = self._combine(next_date, at_time)
        if next_occ < anchor:
            next_occ += timedelta(days=7)
        prev_occ = next_occ - timedelta(days=7)
        delta_next = abs(next_occ - anchor)
        delta_prev = abs(anchor - prev_occ)
        if delta_prev <= delta_next:
            return prev_occ, delta_prev
        return next_occ, delta_next

    # -----------------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------------
    def find_start_datetime(
        self,
        start_preferences: List[str],
        end_date: Optional[datetime] = None,
        nb_days: Optional[int] = None
    ) -> datetime:
        now = datetime.now(self.TIMEZONE)
        if end_date is not None and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=self.TIMEZONE)
        patterns = self._build_patterns(start_preferences)
        if nb_days is None or end_date is None:
            candidates: List[datetime] = []
            for wd, t in patterns:
                candidates.append(self._next_occurrence_after(now, wd, t))
            return min(candidates) if candidates else now

        target = end_date - timedelta(days=nb_days)
        best_dt: Optional[datetime] = None
        best_score: Optional[timedelta] = None
        for wd, t in patterns:
            candidate, delta = self._nearest_occurrence_to(target, wd, t)
            if candidate > end_date:
                while candidate > end_date:
                    candidate -= timedelta(days=7)
                delta = abs(candidate - target)
            score = delta
            if best_score is None or score < best_score or (score == best_score and candidate < (best_dt or candidate)):
                best_score = score
                best_dt = candidate
        if best_dt is not None:
            return best_dt
        candidates = [self._next_occurrence_after(now, wd, t) for wd, t in patterns]
        return min(candidates) if candidates else now

# -----------------------------------------------------------------------------
# Example usage
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    service = TimePatternService()
    prefs1 = ["Vendredi", "06:00:00"]
    print("Case A ->", service.find_start_datetime(prefs1))
    example_end = datetime(2025, 8, 30, 12, 0, tzinfo=TIMEZONE)
    print("Case B ->", service.find_start_datetime(prefs1, end_date=example_end, nb_days=14))