# Using TideClock

Three commands, one job each. Everything below runs offline; there is no account, no
configuration, and no server.

- [`tideclock tide`](#tideclock-tide) — hourly tide heights
- [`tideclock moon`](#tideclock-moon) — phase, illumination, 7-day outlook
- [`tideclock harbor`](#tideclock-harbor) — safe harbor windows for a draft
- [Scripting with `--json`](#scripting-with---json)
- [Errors, streams, and exit codes](#errors-streams-and-exit-codes)

All examples assume `tideclock` is on your `PATH`; if it is not, replace `tideclock` with
`python3 tideclock.py`.

---

## `tideclock tide`

```bash
tideclock tide --station "Cape May, NJ" --date 2025-06-01
```

```
 Time     Height  Profile                 Trend
──────────────────────────────────────────────────────────────────────────────
 00:00    0.59 m  ████████████████████    falling
 01:00    0.48 m  ██████████████████··    falling
 ...
 12:00    0.60 m  ████████████████████    rising
 ...
 23:00    0.45 m  ██████████████████··    rising
──────────────────────────────────────────────────────────────────────────────
 Low 05:36 -0.64 · High 12:17 +0.61 · Low 18:04 -0.66
 heights in m · 24 hourly rows · station local time · offline harmonic model
 profile bar scaled to the day's range (-0.66 to 0.60 m)
```

- 24 rows, one per hour of the requested local day.
- `Trend` is the slope of the tide **around** the hour (central difference), so the hour either
  side of a high or low reads correctly.
- The trailing lines list the day's turning points (highs/lows found at 1-minute resolution) and
  the day's height range used to scale the bar.
- Required: `--station`, `--date`. The date must be strict `YYYY-MM-DD`.

**Unknown station** — the error lists everything embedded:

```bash
$ tideclock tide --station "Cape May" --date 2025-06-01     # missing ", NJ"
error: unknown station 'Cape May'
hint: embedded stations: Bar Harbor, ME · Cape May, NJ · Charleston, SC · Key West, FL · San Francisco, CA · Seattle, WA
       quote names that contain spaces, for example --station "Cape May, NJ"
$ echo $?
2
```

**Malformed date** — message on stderr, nothing on stdout, exit 2:

```bash
$ tideclock tide --station "Cape May, NJ" --date 2025-6-1
error: invalid date '2025-6-1': expected strict ISO format YYYY-MM-DD (for example 2025-06-01)
```

---

## `tideclock moon`

Works out the phase for any date; `--date` defaults to **today**.

```bash
tideclock moon --date 2025-06-01
```

```
 Phase        Waxing Crescent
 Illumination  27.0 %  █████···············
 Age            5.1 days into a 29.5-day lunation
 Trend        waxing
 Next full    2025-06-11
 Next new     2025-06-25
 Outlook      Moonlight building; range still small, so high-tide depths stay
               modest.

─── 7-day outlook ────────────────────────────────────────────────────────────
 Date       Phase              Illum  Profile
──────────────────────────────────────────────────────────────────────────────
 2025-06-01 Waxing Crescent    27.0%  █████···············
 2025-06-02 Waxing Crescent    36.9%  ███████·············
 2025-06-03 First Quarter      47.4%  █████████···········
 2025-06-04 Waxing Gibbous     58.0%  ████████████········
 2025-06-05 Waxing Gibbous     68.2%  ██████████████······
 2025-06-06 Waxing Gibbous     77.6%  ████████████████····
 2025-06-07 Waxing Gibbous     85.8%  █████████████████···
──────────────────────────────────────────────────────────────────────────────
 illumination and phase are approximate — a planning aid, not an ephemeris
```

- Illumination is derived from the moon's age in a mean lunation (29.53 days).
- Principal phases (New, First Quarter, Full, Last Quarter) are claimed only within ±0.6 day of
  their instant, so the outlook does not print "First Quarter" for four days in a row.
- The outlook text also mentions the spring/neap tidal range, because the same lunar forcing
  drives both the tide table and the phase.
- No ephemeris precision, no time-zone conversion, no moonrise/moonset — by design.

---

## `tideclock harbor`

```bash
tideclock harbor --station "Cape May, NJ" --date 2025-06-01 --draft 2.0 --margin 0.5
```

```
 Start  End    Duration  Min depth     Peak  Verdict  Note
──────────────────────────────────────────────────────────────────────────────
 06:00† 06:50  0h 50m      2.37 m  2.48 m  UNSAFE   floats, below margin
 06:55  16:45  9h 50m      2.50 m  3.61 m  SAFE     clears draft + margin
 16:50  19:25  2h 35m      2.34 m  2.50 m  UNSAFE   floats, below margin
 19:30  20:00† 0h 30m      2.51 m  2.64 m  SAFE     clears draft + margin
──────────────────────────────────────────────────────────────────────────────
 4 candidate window(s) · 2 SAFE · 2 UNSAFE
 † edge is the daylight limit, not a depth crossing
 best bet: 06:55–16:45 on 2025-06-01, minimum 2.50 m
```

How to read it:

1. Depth = the station's chart depth + predicted tide height.
2. Daylight (06:00–20:00 station local time) is sampled every 5 minutes, giving a contiguous
   stretch where the vessel floats at all (depth ≥ draft) — a **candidate window**.
3. A window is **SAFE** only if its minimum depth also clears `draft + margin`; otherwise it is
   **UNSAFE** — the boat floats, but with no spare water. Both verdicts are printed as words, so
   the output is readable without colour.
4. `Peak` is the deepest water in the window (how much spare you actually get).
5. `†` marks an edge that is the daylight limit rather than a tide crossing — the window may be
   longer outside daylight hours.

**Nothing qualifies** — a plain all-day message, exit code 0:

```bash
$ tideclock harbor --station "Cape May, NJ" --date 2025-06-01 --draft 99 --margin 0.5
 ! No safe harbor windows for Cape May, NJ on 2025-06-01: predicted daylight
    depth peaks at 3.61 m at 12:15, below the required 99.50 m (draft 99.00 m
    + margin 0.50 m).
 suggest: a later date, a shallower draft, or a station with more water
```

**Validation** — draft and margin must be positive numbers; the message is on stderr, exit 2:

```bash
$ tideclock harbor --station "Cape May, NJ" --date 2025-06-01 --draft 0 --margin 0.5
tideclock harbor: error: argument --draft: draft must be a positive number (got '0')

$ tideclock harbor --station "Cape May, NJ" --date 2025-06-01 --draft 2.0 --margin abc
tideclock harbor: error: argument --margin: margin must be a positive number (got 'abc')
```

---

## Scripting with `--json`

Every command accepts `--json` and writes one JSON object to stdout (never coloured):

```bash
tideclock harbor --station "Cape May, NJ" --date 2025-06-01 --draft 2 --margin 0.5 --json
```

```json
{
  "station": "Cape May, NJ",
  "date": "2025-06-01",
  "draft_m": 2.0,
  "margin_m": 0.5,
  "required_depth_m": 2.5,
  "daylight": { "start": "06:00", "end": "20:00" },
  "sample_step_minutes": 5,
  "windows": [
    {
      "start_local": "06:00", "end_local": "06:50", "duration_minutes": 50,
      "min_depth_m": 2.37, "max_depth_m": 2.48, "margin_m": -0.13,
      "is_safe": false, "verdict": "UNSAFE", "touches_daylight_edge": true
    },
    {
      "start_local": "06:55", "end_local": "16:45", "duration_minutes": 590,
      "min_depth_m": 2.5, "max_depth_m": 3.61, "margin_m": 0.0,
      "is_safe": true, "verdict": "SAFE", "touches_daylight_edge": false
    }
  ],
  "safe_window_count": 2,
  "all_day_message": null
}
```

Handy one-liners:

```bash
# just the SAFE start times
tideclock harbor --station "Bar Harbor, ME" --date 2025-09-20 --draft 2 --margin 0.4 --json \
  | python3 -c 'import json,sys;[print(w["start_local"], "-", w["end_local"]) for w in json.load(sys.stdin)["windows"] if w["is_safe"]]'

# illumination today
tideclock moon --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["illumination_pct"])'
```

---

## Errors, streams, and exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success — including the "no safe harbor windows" all-day answer. |
| `2` | Invalid input: malformed date, unknown station, non-positive/non-numeric draft or margin. |

- Results → **stdout**; errors, hints, and usage → **stderr**, so `tideclock … | grep SAFE` and
  `… > file` behave as expected.
- Colour: automatic on a TTY, off when piped or when `NO_COLOR` is set, and forceable off with
  `--no-color`. The accent colour marks the header and the `SAFE` verdict; `UNSAFE` is a word,
  never a colour alone.
- `tideclock --help` also lists every embedded station; `tideclock --version` prints the version.

## Copy-paste day plan

A 2.0 m draft, 0.5 m margin, Bar Harbor in late September:

```bash
tideclock moon  --date 2025-09-20
tideclock tide  --station "Bar Harbor, ME" --date 2025-09-20
tideclock harbor --station "Bar Harbor, ME" --date 2025-09-20 --draft 2.0 --margin 0.5
```
