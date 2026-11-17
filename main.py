"""GTA VI Twitch CCU forecast (make.fun gta6-twitch-ccu-forecast-01).

Forecasts, hour by hour, the concurrent Twitch viewers in the Grand Theft
Auto VI category over the 24 UTC hours of its release day, 2026-11-19, as
five quantiles an hour (levels 0.05, 0.25, 0.5, 0.75, 0.95) for hours 2..24,
from the hour-1 print and the past launches shipped in the case file.

Method (fitted on the case's own comparables at run time, nothing hard-coded
from any one launch):
  1. Pool: past launches whose release day is fully recorded, whose tier is
     "comparable" (not early-access-contaminated, weak, or the target's own
     pre-release history), and whose hour-1 print is at least 5% of its
     release-day peak (an "early" unlock: the game was actually live at
     midnight UTC). A late global unlock (tiny hour 1, 100x ramp later) is a
     different shape and is left out.
  2. Ratio curve: for each launch, log(viewers[h] / viewers[hour 1]) for
     h = 2..24. The median curve is the weighted median across launches
     (console-only launches count double: GTA VI is console-only, rolling
     midnight). Quantiles are the median plus a normal spread whose sigma
     comes from the launches' interquartile range (robust to the skew).
  3. Level effect: launches whose hour-1 print is small ramp much harder
     than launches whose hour-1 print is already huge (the log peak/hour-1
     ratio falls with log hour-1, r ~ -0.8 in the pool). A console-weighted
     least-squares slope of log(peak/hour-1) on log(hour-1) shifts the
     median curve: the shift grows with the median curve's own rise (no
     shift in the small hours, full shift at the evening peak), is
     winsorised to the pool's observed hour-1 range, and may at most halve
     the median ratio (a guardrail against extrapolating a decline).
  4. The five log-quantiles are smoothed with a 3-hour moving average,
     rounded to 2 decimals half-up (as the house baseline rounds), and
     clamped to (0, 1e9], non-decreasing per row.

Deterministic: pure arithmetic over the case file in file order, no
randomness, no network, no clock, no environment reads beyond the input /
output directories. Standard library only. One case runs in well under a
second. If the comparables cannot support the ratio model (too few usable
launches, or any unexpected shape), it falls back to the house persistence
forecast so the case still scores instead of going invalid.
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]
SIGMA_PERSIST = 0.15

# Pool rules.
MIN_PEAK_FRACTION = 0.05   # hour-1 print must be >= 5% of the launch's peak
CONSOLE_WEIGHT = 2.0        # console-only launches count double
MIN_POOL = 5                # fewer usable launches -> fall back to persistence
SPREAD_FLOOR = 0.10         # minimum half-width (log units) of the q05..q95 band
SHIFT_CAP = 0.5             # the level shift may at most halve the median ratio


def round2(x):
    """x rounded to 2 decimals, half up, as JavaScript's Math.round rounds it.

    A whole number comes back as an int, so json.dumps writes 1240 where
    JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def quantile(xs, p):
    """Linear-interpolation empirical quantile."""
    s = sorted(xs)
    n = len(s)
    if n == 1:
        return s[0]
    pos = p * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    f = pos - lo
    return s[lo] * (1 - f) + s[hi] * f


def weighted_median(pairs):
    """pairs: list of (value, weight)."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    acc = 0.0
    for value, weight in ordered:
        acc += weight
        if acc >= total / 2:
            return value
    return ordered[-1][0]


def tier_of(comparable):
    """Tier from the unlock note: 'comparable' unless stated otherwise."""
    text = comparable.get("unlock", "") or ""
    for token in ("early-access-contaminated", "target-history", "weak"):
        if token in text:
            return token
    return "comparable"


def release_day(comparable):
    """{delta hour 0..23 -> viewers} for the launch's UTC release day."""
    try:
        day_start = parse_time(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    out = {}
    for point in comparable.get("hourly", []) or []:
        try:
            viewers = float(point["viewers"])
            delta = (parse_time(point["from"]) - day_start).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= delta < 24 and viewers > 0:
            out[int(delta)] = viewers
    return out


def usable_launches(case):
    """Launches the ratio model may learn from."""
    pool = []
    for comparable in case.get("comparables", []) or []:
        if tier_of(comparable) != "comparable":
            continue
        day = release_day(comparable)
        if len(day) < 24 or 0 not in day:
            continue
        peak = max(day.values())
        if day[0] < MIN_PEAK_FRACTION * peak:
            continue
        platforms = comparable.get("platforms", "") or ""
        pool.append({
            "day": day,
            "p1": day[0],
            "peak": peak,
            "console": ("PC" not in platforms and "Steam" not in platforms),
        })
    return pool


def persistence_quantiles(p1, hour):
    return [round2(p1 * math.exp(z * SIGMA_PERSIST * math.sqrt(hour - 1))) for z in Z]


def ratio_forecast(pool, p1):
    """Five log-quantiles per hour (hours 2..24) from the launch pool."""
    # Per-hour weighted median log-ratio and robust normal spread.
    rows = []
    for delta in range(1, 24):
        pairs = []
        for launch in pool:
            if delta not in launch["day"]:
                continue
            weight = CONSOLE_WEIGHT if launch["console"] else 1.0
            pairs.append((math.log(launch["day"][delta] / launch["p1"]), weight))
        if not pairs:
            rows.append(None)
            continue
        values = [v for v, _ in pairs]
        med = weighted_median(pairs)
        q25 = quantile(values, 0.25)
        q75 = quantile(values, 0.75)
        sigma = max((q75 - q25) / 1.349, 0.05)
        rows.append([med + z * sigma for z in Z])
    # Fill any hour with no launch data by carrying the nearest hour.
    last = None
    for i, row in enumerate(rows):
        if row is None and last is not None:
            rows[i] = list(last)
        elif row is not None:
            last = row
    if rows[0] is None:
        first = next((r for r in rows if r is not None), [0.0] * 5)
        for i, row in enumerate(rows):
            if row is None:
                rows[i] = list(first)
    # Spread floor: the q05..q95 band is at least 2 * SPREAD_FLOOR wide.
    for row in rows:
        if row[4] - row[0] < 2 * SPREAD_FLOOR:
            mid = 0.5 * (row[4] + row[0])
            row[0] = mid - SPREAD_FLOOR
            row[4] = mid + SPREAD_FLOOR
            row[1] = min(row[1], row[2])
            row[3] = max(row[3], row[2])
    return rows


def level_shift(pool, p1, log_rows):
    """Shift the median curve by the hour-1 level effect (see module docstring)."""
    xs = [math.log(launch["p1"]) for launch in pool]
    ys = [math.log(launch["peak"] / launch["p1"]) for launch in pool]
    ws = [CONSOLE_WEIGHT if launch["console"] else 1.0 for launch in pool]
    total_w = sum(ws)
    mx = sum(x * w for x, w in zip(xs, ws)) / total_w
    my = sum(y * w for y, w in zip(ys, ws)) / total_w
    denom = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws))
    beta = 0.0
    if denom > 0:
        beta = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws)) / denom
    dlogp1 = math.log(p1) - mx
    dlogp1 = max(min(xs) - mx, min(max(xs) - mx, dlogp1))
    medians = [row[2] for row in log_rows]
    peak = max(medians) if medians else 0.0
    shifted = []
    for i, row in enumerate(log_rows):
        weight = (medians[i] / peak) if peak > 0 else 0.0
        weight = max(0.0, min(1.0, weight))
        shift = beta * dlogp1 * weight
        new_med = medians[i] + shift
        # Guardrail: the shift may at most halve the median ratio.
        new_med = max(new_med, medians[i] + math.log(SHIFT_CAP))
        moved = new_med - medians[i]
        shifted.append([q + moved for q in row])
    return shifted


def smooth_log_rows(log_rows):
    """3-hour moving average over each quantile level (log space)."""
    out = [list(row) for row in log_rows]
    for level in range(5):
        col = [row[level] for row in log_rows]
        for i in range(len(col)):
            lo = max(0, i - 1)
            hi = min(len(col), i + 2)
            out[i][level] = sum(col[lo:hi]) / (hi - lo)
    return out


def forecast_case(case, name):
    first = next((k for k in case.get("known", []) if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    hours = sorted({int(row["hour"]) for row in case.get("forecast", [])})
    if not hours:
        hours = list(range(2, 25))
    pool = usable_launches(case)
    try:
        if len(pool) < MIN_POOL:
            raise ValueError("pool too small")
        log_rows = ratio_forecast(pool, p1)
        log_rows = level_shift(pool, p1, log_rows)
        log_rows = smooth_log_rows(log_rows)
        rows = []
        for i, hour in enumerate(hours):
            idx = hour - 2
            if idx < 0 or idx >= len(log_rows):
                break
            qs = [round2(p1 * math.exp(q)) for q in log_rows[idx]]
            qs = sorted(max(1.0, min(1e9, q)) for q in qs)
            rows.append({"hour": hour, "q": qs})
    except Exception:
        rows = [
            {"hour": hour, "q": sorted(max(1.0, v) for v in persistence_quantiles(p1, hour))}
            for hour in hours
        ]
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
