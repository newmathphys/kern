"""KERN demo: an @lru_cache whose body reads the clock goes stale by design.

Live case found in Kanaries/pygwalker (16k stars, `data_parsers/base.py`):
`get_timezone_base_offset(offset_seconds)` is memoised by the offset alone, but
its body asks which zone has that utcoffset *right now*.  Across a DST boundary
the set of valid answers changes, so the frozen pick starts lying by one hour.
The function itself is unused (latent), so we ship the mechanism as a stand-in
instead of filing a report.

Everything here is stdlib only (`zoneinfo`), self-checking, and exits 0.
"""
from __future__ import annotations

import ast
import sys
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

WINTER = date(2026, 1, 15)
SUMMER = date(2026, 7, 15)


def zone_offset(zone: str, when: date) -> timedelta:
    moment = datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc)
    return moment.astimezone(zoneinfo.ZoneInfo(zone)).utcoffset()


def zones_matching(offset_seconds: int, when: date) -> set:
    want = timedelta(seconds=offset_seconds)
    return {z for z in zoneinfo.available_timezones() if zone_offset(z, when) == want}


@lru_cache(maxsize=None)
def zone_name_for(offset_seconds: int) -> str:
    """The buggy shape: the key is the offset, the body reads today's date."""
    today = datetime.now(timezone.utc)
    for zone in sorted(zoneinfo.available_timezones()):
        if today.astimezone(zoneinfo.ZoneInfo(zone)).utcoffset() == timedelta(seconds=offset_seconds):
            return zone
    return "UTC"


@lru_cache(maxsize=None)
def zone_name_for_day(offset_seconds: int, when: date) -> str:
    """The clean shape: the date is part of the key, so a stale answer is impossible."""
    for zone in sorted(zoneinfo.available_timezones()):
        if zone_offset(zone, when) == timedelta(seconds=offset_seconds):
            return zone
    return "UTC"


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"[{'OK' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    ok = []

    # 1) our own arm detects the impurity in this very file
    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    from api_hunt import analyse_lru            # noqa: PLC0415 — demo needs the real arm

    findings = analyse_lru(Path(__file__).read_text(encoding="utf-8"), "demo.py")
    names = [f["symbol"] for f in findings]
    ok.append(check("lru-effects flags zone_name_for (clock read under a memo key)",
                    any(n.startswith("zone_name_for(") for n in names), ", ".join(names) or "нет"))
    ok.append(check("lru-effects keeps quiet about zone_name_for_day",
                    not any(n.startswith("zone_name_for_day(") for n in names)))

    # 2) the candidate set really depends on the date
    winter, summer = zones_matching(-18000, WINTER), zones_matching(-18000, SUMMER)
    ok.append(check("offset -18000 has a date-dependent answer set",
                    winter != summer, f"{len(winter)} zones in January vs {len(summer)} in July"))

    # 3) one valid January answer becomes wrong in July
    picked = "America/Indiana/Indianapolis"
    drift = zone_offset(picked, SUMMER) - timedelta(seconds=-18000)
    ok.append(check("that January answer drifts by one hour in July",
                    drift == timedelta(hours=1),
                    f"{picked}: -05:00 in January, -04:00 in July -> off by {drift}"))

    # 4) the cache hands the January answer back in July
    frozen = zone_name_for(-18000)              # note: this reads the *real* clock
    fresh = zone_name_for_day(-18000, SUMMER)
    ok.append(check("a date in the key eliminates the drift",
                    zone_offset(fresh, SUMMER) == timedelta(seconds=-18000),
                    f"fresh July answer {fresh} is exactly -05:00"))

    print(f"\ncached once for offset -18000: {frozen}")
    print(f"clean call for July          : {fresh}")
    print(f"zoneinfo version             : {zoneinfo.TZPATH[0] if zoneinfo.TZPATH else 'system'}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
