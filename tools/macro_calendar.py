#!/usr/bin/env python3
"""
Macro Release Calendar — Blackout Window Detection (Phase 4 partial)

Identifies high-impact macro releases (FOMC, CPI, NFP, PCE) and mega-cap earnings
to block ES entries in a configurable window around them. Reads from the
sister macro_2 repo for earnings_calendar.csv and computes statistically-based
release dates for the regular indicators (BLS/BEA publish on a known cadence).

Usage:
    from tools.macro_calendar import MacroCalendar
    cal = MacroCalendar()
    if cal.is_blackout_window(ts, lookback_min=30, lookahead_min=60):
        skip_trade()

Or as a CLI:
    python tools/macro_calendar.py --next 7      # Show next 7 days of releases
    python tools/macro_calendar.py --check NOW   # Is now in a blackout?

Release schedule (US Eastern, when applicable):
    FOMC          — 2:00 PM ET on FOMC days (8 per year, scheduled)
    CPI           — 8:30 AM ET, 2nd Tuesday of month
    NFP           — 8:30 AM ET, 1st Friday of month
    PCE           — 8:30 AM ET, last Friday of month
    GDP           — 8:30 AM ET, last Thursday of month (advance/2nd/3rd estimates)
    Retail Sales  — 8:30 AM ET, ~mid-month
    ISM PMI       — 10:00 AM ET, 1st business day of month
    Earnings      — Per earnings_calendar.csv (after-close or pre-market)
"""
from __future__ import annotations

import argparse
import csv
import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dt_time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Default to ~/Github/macro_2 (local Mac convention); fall back to /root/macro_2 (VPS).
# Override via env var MACRO_DATA_DIR or CLI --earnings-csv.
import os
_MACRO_DIR = Path(os.environ.get(
    "MACRO_DATA_DIR",
    str(Path.home() / "Github" / "macro_2" / "historical_data"),
))
EARNINGS_CSV = _MACRO_DIR / "earnings_calendar.csv"
EARNINGS_CSV_VPS = Path("/root/macro_2/historical_data/earnings_calendar.csv")

# US Eastern offset (EDT/EST handled implicitly — use UTC throughout, convert when comparing)
ET_UTC_OFFSET_HOURS = -4  # EDT (Apr-Nov); -5 in EST winter. Good enough for blackout windows.


@dataclass
class Release:
    name: str          # e.g. "CPI", "FOMC", "AAPL_earnings"
    impact: str        # "HIGH" / "MEDIUM" / "LOW"
    ts_utc: datetime   # Release timestamp in UTC
    note: str = ""


def _to_utc(dt_local: datetime, offset_hours: int = ET_UTC_OFFSET_HOURS) -> datetime:
    return (dt_local - timedelta(hours=offset_hours)).replace(tzinfo=timezone.utc)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[datetime]:
    """Return the date of the n-th occurrence of `weekday` (0=Mon..6=Sun) in given month."""
    count = 0
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        d = datetime(year, month, day)
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
    return None


def _last_weekday_of_month(year: int, month: int, weekday: int) -> Optional[datetime]:
    last_day = calendar.monthrange(year, month)[1]
    for day in range(last_day, 0, -1):
        d = datetime(year, month, day)
        if d.weekday() == weekday:
            return d
    return None


def _first_business_day_of_month(year: int, month: int) -> datetime:
    for day in range(1, 8):
        d = datetime(year, month, day)
        if d.weekday() < 5:
            return d
    return datetime(year, month, 1)


# Hardcoded FOMC 2026 dates (8 meetings; from Fed published schedule). Update yearly.
FOMC_2026_DATES = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]
FOMC_2025_DATES = [
    "2025-01-29", "2025-03-19", "2025-04-30", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
]

# Approximate release times (US Eastern)
RELEASE_TIME_8_30 = dt_time(8, 30)   # CPI / NFP / PCE / GDP / Retail Sales
RELEASE_TIME_10_00 = dt_time(10, 0)  # ISM PMI / JOLTS
RELEASE_TIME_FOMC = dt_time(14, 0)   # 2 PM ET press release


# ─── Calendar generation ─────────────────────────────────────

class MacroCalendar:
    def __init__(self, earnings_csv: Optional[Path] = None,
                 fomc_dates: Optional[list[str]] = None,
                 mega_caps: Optional[list[str]] = None):
        # Pick whichever earnings CSV exists (local Mac path or VPS path)
        self.earnings_csv = earnings_csv or (EARNINGS_CSV if EARNINGS_CSV.exists() else EARNINGS_CSV_VPS)
        self.fomc_dates = fomc_dates or (FOMC_2025_DATES + FOMC_2026_DATES)
        # MAG7 + a few high-impact others (any can move ES via index weight)
        self.mega_caps = mega_caps or ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
        self._releases_cache: dict[str, list[Release]] = {}  # keyed by yyyy-mm

    # -- public API ------------------------------------------------------
    def releases_in_window(self, start_utc: datetime, end_utc: datetime) -> list[Release]:
        """All releases (HIGH+MEDIUM impact) between start and end UTC, sorted by time."""
        result = []
        cur = start_utc.replace(day=1)
        while cur <= end_utc:
            key = cur.strftime("%Y-%m")
            if key not in self._releases_cache:
                self._releases_cache[key] = self._build_month(cur.year, cur.month)
            for r in self._releases_cache[key]:
                if start_utc <= r.ts_utc <= end_utc:
                    result.append(r)
            # Step to next month
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        return sorted(result, key=lambda r: r.ts_utc)

    def is_blackout_window(self, ts_utc: datetime,
                           lookback_min: int = 30, lookahead_min: int = 60,
                           min_impact: str = "HIGH") -> tuple[bool, Optional[Release]]:
        """Return (True, Release) if any release of given impact falls in
        [ts - lookback, ts + lookahead]. Lookback catches "release just happened",
        lookahead catches "release coming up — don't enter ahead of news"."""
        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.replace(tzinfo=timezone.utc)
        impact_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        threshold = impact_rank.get(min_impact, 3)
        # Build releases for the day +/- a buffer
        start = ts_utc - timedelta(minutes=lookback_min, hours=2)
        end = ts_utc + timedelta(minutes=lookahead_min, hours=2)
        for r in self.releases_in_window(start, end):
            if impact_rank.get(r.impact, 0) < threshold:
                continue
            window_start = r.ts_utc - timedelta(minutes=lookahead_min)
            window_end = r.ts_utc + timedelta(minutes=lookback_min)
            if window_start <= ts_utc <= window_end:
                return True, r
        return False, None

    def next_releases(self, n: int = 10, from_ts: Optional[datetime] = None) -> list[Release]:
        from_ts = from_ts or datetime.now(timezone.utc)
        return self.releases_in_window(from_ts, from_ts + timedelta(days=30))[:n]

    # -- internals -------------------------------------------------------
    def _build_month(self, year: int, month: int) -> list[Release]:
        rels: list[Release] = []

        # FOMC — fixed schedule
        for date_str in self.fomc_dates:
            yy, mm, dd = map(int, date_str.split("-"))
            if yy == year and mm == month:
                local = datetime(yy, mm, dd, RELEASE_TIME_FOMC.hour, RELEASE_TIME_FOMC.minute)
                rels.append(Release("FOMC", "HIGH", _to_utc(local), "Fed rate decision + statement"))

        # NFP — 1st Friday 8:30 AM ET
        d = _nth_weekday_of_month(year, month, weekday=4, n=1)
        if d:
            local = datetime(d.year, d.month, d.day, RELEASE_TIME_8_30.hour, RELEASE_TIME_8_30.minute)
            rels.append(Release("NFP", "HIGH", _to_utc(local), "Nonfarm Payrolls + unemployment rate"))

        # CPI — 2nd Tuesday 8:30 AM ET (BLS publishes ~10-15 of month; 2nd Tue is a fair approximation)
        d = _nth_weekday_of_month(year, month, weekday=1, n=2)
        if d:
            local = datetime(d.year, d.month, d.day, RELEASE_TIME_8_30.hour, RELEASE_TIME_8_30.minute)
            rels.append(Release("CPI", "HIGH", _to_utc(local), "Consumer Price Index — headline + core"))

        # PCE — last Friday 8:30 AM ET (BEA publishes ~25-30 of month)
        d = _last_weekday_of_month(year, month, weekday=4)
        if d:
            local = datetime(d.year, d.month, d.day, RELEASE_TIME_8_30.hour, RELEASE_TIME_8_30.minute)
            rels.append(Release("PCE", "HIGH", _to_utc(local), "Core PCE — Fed's preferred inflation gauge"))

        # GDP — last Thursday 8:30 AM ET (BEA, quarterly but tracks monthly via estimates)
        d = _last_weekday_of_month(year, month, weekday=3)
        if d:
            local = datetime(d.year, d.month, d.day, RELEASE_TIME_8_30.hour, RELEASE_TIME_8_30.minute)
            rels.append(Release("GDP", "MEDIUM", _to_utc(local), "GDP estimate"))

        # ISM PMI — 1st business day, 10 AM ET
        d = _first_business_day_of_month(year, month)
        local = datetime(d.year, d.month, d.day, RELEASE_TIME_10_00.hour, RELEASE_TIME_10_00.minute)
        rels.append(Release("ISM_PMI", "MEDIUM", _to_utc(local), "ISM Manufacturing PMI"))

        # Mega-cap earnings — from CSV (treat 4 PM ET = post-close release)
        # CSV may have duplicate (symbol, date) rows from multiple extractions; dedupe.
        if self.earnings_csv.exists():
            try:
                seen: set[tuple[str, str]] = set()
                with self.earnings_csv.open() as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sym = (row.get("symbol") or "").upper()
                        if sym not in self.mega_caps:
                            continue
                        date_str = row.get("date", "")
                        if (sym, date_str) in seen:
                            continue
                        seen.add((sym, date_str))
                        try:
                            yy, mm, dd = map(int, date_str.split("-"))
                        except (ValueError, AttributeError):
                            continue
                        if yy == year and mm == month:
                            local = datetime(yy, mm, dd, 16, 0)  # 4 PM ET — post-close
                            rels.append(Release(
                                f"{sym}_earnings", "HIGH",
                                _to_utc(local),
                                f"{sym} earnings (post-close)",
                            ))
            except Exception:
                pass

        return sorted(rels, key=lambda r: r.ts_utc)


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Macro release calendar / blackout check")
    parser.add_argument("--next", type=int, default=None,
                        help="Show next N releases")
    parser.add_argument("--check", type=str, default=None,
                        help="Check if a UTC timestamp (or 'NOW') is in a blackout window")
    parser.add_argument("--lookback", type=int, default=30,
                        help="Blackout lookback in minutes (default 30)")
    parser.add_argument("--lookahead", type=int, default=60,
                        help="Blackout lookahead in minutes (default 60)")
    parser.add_argument("--impact", default="HIGH", choices=["HIGH", "MEDIUM", "LOW"])
    parser.add_argument("--earnings-csv", default=None)
    args = parser.parse_args()

    cal = MacroCalendar(earnings_csv=Path(args.earnings_csv) if args.earnings_csv else None)

    if args.next is not None:
        for r in cal.next_releases(args.next):
            print(f"{r.ts_utc.isoformat()}  [{r.impact:6}]  {r.name:18}  {r.note}")
        return

    if args.check:
        if args.check.upper() == "NOW":
            ts = datetime.now(timezone.utc)
        else:
            ts = datetime.fromisoformat(args.check).replace(tzinfo=timezone.utc)
        is_black, release = cal.is_blackout_window(
            ts, lookback_min=args.lookback, lookahead_min=args.lookahead,
            min_impact=args.impact,
        )
        if is_black:
            print(f"BLACKOUT — {release.name} at {release.ts_utc.isoformat()} ({release.note})")
        else:
            print(f"CLEAR — no {args.impact}+ releases within "
                  f"-{args.lookback}m / +{args.lookahead}m of {ts.isoformat()}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
