# GTA VI Twitch CCU forecast

[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/kaffin02/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/kaffin02/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for the [make.fun bounty `gta6-twitch-ccu-forecast-01`](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
("Forecast GTA VI's launch-day Twitch viewers hour by hour"). One file, `main.py`
(Python 3.13, standard library only). No dependencies, no network, no clock, no
randomness — fully deterministic.

## How it works

The program reads the case file (`*.in` in `$MAKEFUN_INPUT_DIR` or `/input/`)
and forecasts hours 2–24 of the release day as five quantiles an hour
(levels 0.05, 0.25, 0.5, 0.75, 0.95), anchored on the hour-1 print and on the
past launches shipped in the case:

1. **Pool.** Past launches with a fully recorded release day, tier
   "comparable", and an hour-1 print at least 5% of the launch's peak (an
   early unlock — the game was actually live at midnight UTC). Late global
   unlocks (tiny hour 1, 100× ramp later) and early-access-contaminated or
   weak launches are left out, as is the GTA VI category's own pre-release
   history.
2. **Ratio curve.** For each launch, `log(viewers[h] / viewers[hour 1])` for
   h = 2..24. The median curve is the weighted median across launches
   (console-only launches count double — GTA VI is console-only, rolling
   midnight). Quantiles are the median plus a normal spread whose sigma comes
   from the launches' interquartile range.
3. **Level effect.** Launches whose hour-1 print is small ramp much harder
   than launches whose hour-1 print is already huge (in the pool, the log
   peak/hour-1 ratio falls with log hour-1, r ≈ −0.8). A console-weighted
   least-squares slope shifts the median curve: the shift grows with the
   median curve's own rise (none in the small hours, full at the evening
   peak), is winsorised to the pool's observed hour-1 range, and may at most
   halve the median ratio.
4. **Smoothing and rounding.** The five log-quantiles get a 3-hour moving
   average, are rounded to 2 decimals half-up (as the house baseline rounds),
   and are clamped to (0, 1e9], non-decreasing per row.

If the comparables cannot support the ratio model (too few usable launches),
it falls back to the house persistence forecast so the case still scores
instead of going invalid.

## Validation (local, leave-one-launch-out)

Each of the 37 fully recorded comparables was turned into a pseudo-case
(cut at its hour 1, forecast hours 2–24, scored with the contest's log-scale
pinball loss against its actual release day):

| set | this model | house baseline (persistence) |
| --- | --- | --- |
| 19 comparable early-unlock launches | **0.2680** | 0.4026 |
| 7 console-only launches of those | **0.1793** | 0.3435 |
| all 37 launches | **0.7038** | 0.9297 |

The house baseline scores ≈ 0.387 on the four sealed practice cases; the
practice truth is sealed, so no practice score can be computed locally — the
pseudo-case scores above are the honest estimate. The model beats the
baseline on 16 of the 19 core pseudo-cases. Runtime is ~0.02 s per case
(limit 8 s), output ~1.5 KB (limit 64 KB), and two runs on the same case are
byte-identical.

## Run it

```sh
MAKEFUN_INPUT_DIR=path/to/cases MAKEFUN_OUTPUT_DIR=path/to/out python3 main.py
```

Writes `/output/<id>.out` (or `$MAKEFUN_OUTPUT_DIR/<id>.out`) per case:
`{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ..., {"hour": 24, "q": [...]}]}`.
