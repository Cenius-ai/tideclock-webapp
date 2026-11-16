#!/usr/bin/env python3
"""TideClock — offline tide predictions, moon phase, and safe harbor windows.

A single-file, standard-library-only command line tool for coastal kayakers and
small-boat operators who plan a passage without internet access.

Commands
    tideclock tide   --station NAME --date YYYY-MM-DD
    tideclock moon   [--date YYYY-MM-DD]
    tideclock harbor --station NAME --date YYYY-MM-DD --draft M --margin M

Everything is computed locally from the embedded harmonic station table; the
tool never touches the network and needs no configuration, environment
variables, or external data files.

DESIGN TOKENS (calm-precise / terminal dark — the committed design source of truth)
    accent            oklch(0.58 0.12 200)  ->  #008e96  ->  ANSI truecolor 0;142;150
    surface (dark)    #0b1013   terminal default background
    text              #d7e0e4   muted  #8fa3a9   rule  #24343a (dim)
    type              system monospace only, one 1-step ramp (no proportional text)
    shape             box-drawing rules, no chrome, no elevation
    signal            ONE accent reserved for the primary status (SAFE verdict,
                      header title); UNSAFE is carried by the word itself plus a
                      bold weight, never by colour alone.

Exit codes
    0  success
    2  invalid input (date, number, or station name) — message on stderr
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime

__version__ = "1.0.0"

PROGRAM = "TideClock"
WIDTH = 78  # rendered block width in characters

# Local reference epoch for every harmonic argument (station local time).
EPOCH = datetime(2000, 1, 1)

DAYLIGHT_START = dtime(6, 0)
DAYLIGHT_END = dtime(20, 0)
SAMPLE_STEP_MINUTES = 5
EXTREME_STEP_MINUTES = 1

SYNODIC_MONTH_DAYS = 29.530588853
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14)


# --------------------------------------------------------------------------
# Embedded data: constituent speeds and the station harmonic table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HarmonicConstituent:
    """One tidal constituent: amplitude, phase lag, and angular speed."""

    station_name: str
    symbol: str
    amplitude_m: float
    phase_deg: float
    speed_deg_per_hour: float


@dataclass(frozen=True)
class Station:
    """An embedded tide station with its own harmonic constituents.

    ``chart_depth_m`` is the approach-channel depth below chart datum (a
    deliberately conservative stand-in for a real chart soundings minimum);
    predicted depth in the water is ``chart_depth_m + tide height``.
    """

    name: str
    latitude: float
    longitude: float
    chart_depth_m: float
    constituents: tuple[HarmonicConstituent, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(c.symbol for c in self.constituents)


CONSTITUENT_SPEEDS: dict[str, float] = {
    "M2": 28.984104,  # principal lunar semidiurnal
    "S2": 30.000000,  # principal solar semidiurnal
    "N2": 28.439730,  # larger lunar elliptic semidiurnal
    "K1": 15.041069,  # lunisolar diurnal
    "[redacted]": 13.943035,  # principal lunar diurnal
    "M4": 57.968208,  # shallow-water overtide of M2
}

# name, latitude, longitude, chart depth (m), ((symbol, amplitude m, phase deg), ...)
_STATION_SPECS: tuple[
    tuple[str, float, float, float, tuple[tuple[str, float, float], ...]], ...
] = (
    (
        "Bar Harbor, ME",
        44.3900,
        -68.2050,
        2.9,
        (
            ("M2", 1.55, 145.0),
            ("S2", 0.28, 175.0),
            ("N2", 0.31, 120.0),
            ("K1", 0.16, 95.0),
            ("[redacted]", 0.13, 78.0),
        ),
    ),
    (
        "Cape May, NJ",
        38.9683,
        -74.9600,
        3.0,
        (
            ("M2", 0.62, 96.0),
            ("S2", 0.11, 128.0),
            ("N2", 0.13, 72.0),
            ("K1", 0.06, 88.0),
            ("[redacted]", 0.05, 60.0),
            ("M4", 0.04, 310.0),
        ),
    ),
    (
        "Charleston, SC",
        32.7817,
        -79.9250,
        3.4,
        (
            ("M2", 0.79, 51.0),
            ("S2", 0.14, 79.0),
            ("N2", 0.17, 28.0),
            ("K1", 0.05, 62.0),
            ("[redacted]", 0.04, 44.0),
        ),
    ),
    (
        "Key West, FL",
        24.5551,
        -81.8080,
        2.6,
        (
            ("M2", 0.21, 108.0),
            ("S2", 0.07, 140.0),
            ("N2", 0.05, 84.0),
            ("K1", 0.13, 84.0),
            ("[redacted]", 0.10, 62.0),
        ),
    ),
    (
        "San Francisco, CA",
        37.8063,
        -122.4659,
        2.4,
        (
            ("M2", 0.58, 322.0),
            ("S2", 0.14, 353.0),
            ("N2", 0.13, 300.0),
            ("K1", 0.26, 105.0),
            ("[redacted]", 0.17, 92.0),
        ),
    ),
    (
        "Seattle, WA",
        47.6026,
        -122.3393,
        3.1,
        (
            ("M2", 1.03, 314.0),
            ("S2", 0.24, 344.0),
            ("N2", 0.21, 289.0),
            ("K1", 0.36, 108.0),
            ("[redacted]", 0.20, 95.0),
            ("M4", 0.06, 50.0),
        ),
    ),
)


def _build_station(
    name: str,
    latitude: float,
    longitude: float,
    chart_depth_m: float,
    specs: Sequence[tuple[str, float, float]],
) -> Station:
    constituents = tuple(
        HarmonicConstituent(
            station_name=name,
            symbol=symbol,
            amplitude_m=amplitude,
            phase_deg=phase,
            speed_deg_per_hour=CONSTITUENT_SPEEDS[symbol],
        )
        for symbol, amplitude, phase in specs
    )
    return Station(
        name=name,
        latitude=latitude,
        longitude=longitude,
        chart_depth_m=chart_depth_m,
        constituents=constituents,
    )


STATIONS: tuple[Station, ...] = tuple(_build_station(*spec) for spec in _STATION_SPECS)
STATION_NAMES: tuple[str, ...] = tuple(station.name for station in STATIONS)


# --------------------------------------------------------------------------
# Terminal styling (one accent, colour never the only signal)
# --------------------------------------------------------------------------

_ACCENT_CODE = "38;2;0;142;150"  # #008e96
_MUTED_CODE = "38;2;143;163;169"  # #8fa3a9
_COLOR_ENABLED = False


def set_color(enabled: bool) -> None:
    global _COLOR_ENABLED
    _COLOR_ENABLED = enabled


def _paint(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _COLOR_ENABLED else text


def accent(text: str) -> str:
    return _paint(text, _ACCENT_CODE)


def muted(text: str) -> str:
    return _paint(text, _MUTED_CODE)


def bold(text: str) -> str:
    return _paint(text, "1")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap so no important message is ever truncated."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def header_block(title: str, rows: Sequence[tuple[str, str]]) -> list[str]:
    """Render the shared box-drawing header used by every command."""
    prefix = f"{PROGRAM} ─ {title}"
    pad = max(4, WIDTH - 5 - len(prefix))
    lines = ["╭─ " + accent(prefix) + " " + "─" * pad + "╮"]
    for label, value in rows:
        body = _clip(f"{label:<11} {value}", WIDTH - 4)
        lines.append("│ " + body.ljust(WIDTH - 4) + " │")
    lines.append("╰" + "─" * (WIDTH - 2) + "╯")
    return lines


def section_rule(label: str = "") -> list[str]:
    if not label:
        return ["─" * WIDTH]
    text = f" {label} "
    return ["─" * 3 + muted(text) + "─" * max(3, WIDTH - 3 - len(text))]


def format_coordinates(station: Station) -> str:
    lat = f"{abs(station.latitude):.4f}°{'N' if station.latitude >= 0 else 'S'}"
    lon = f"{abs(station.longitude):.4f}°{'E' if station.longitude >= 0 else 'W'}"
    return f"{lat} {lon}"


def weekday_name(day: date) -> str:
    return day.strftime("%A")


def format_duration(minutes: int) -> str:
    hours, rest = divmod(max(0, minutes), 60)
    return f"{hours}h {rest:02d}m"


# --------------------------------------------------------------------------
# Validation (every failure is loud, on stderr, with a non-zero exit)
# --------------------------------------------------------------------------


class InputError(Exception):
    """A user-facing validation failure: message plus an optional hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(raw: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date or raise :class:`InputError`."""
    text = raw.strip()
    if not _ISO_DATE_PATTERN.match(text):
        raise InputError(
            f"invalid date {raw!r}: expected strict ISO format YYYY-MM-DD "
            "(for example 2025-06-01)"
        )
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise InputError(
            f"invalid date {raw!r}: that calendar day does not exist "
            "(expected YYYY-MM-DD, for example 2025-06-01)"
        ) from None


def find_station(name: str) -> Station:
    """Look a station up by exact name (case-insensitive as a courtesy)."""
    wanted = name.strip()
    for station in STATIONS:
        if station.name == wanted:
            return station
    folded = wanted.casefold()
    matches = [station for station in STATIONS if station.name.casefold() == folded]
    if len(matches) == 1:
        return matches[0]
    listing = " · ".join(STATION_NAMES)
    raise InputError(
        f"unknown station {name!r}",
        hint=(
            f"embedded stations: {listing}\n"
            '       quote names that contain spaces, for example --station "Cape May, NJ"'
        ),
    )


def positive_number(label: str):
    """argparse type factory: a finite, strictly positive float."""

    def parse(raw: str) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(
                f"{label} must be a positive number (got {raw!r})"
            ) from None
        if not math.isfinite(value) or value <= 0.0:
            raise argparse.ArgumentTypeError(
                f"{label} must be a positive number (got {raw!r})"
            )
        return value

    return parse


# --------------------------------------------------------------------------
# Tide model
# --------------------------------------------------------------------------


def tide_height_m(station: Station, moment: datetime) -> float:
    """Predicted tide height (m, relative to chart datum) at a local moment."""
    hours = (moment - EPOCH).total_seconds() / 3600.0
    height = 0.0
    for constituent in station.constituents:
        angle = math.radians(
            constituent.speed_deg_per_hour * hours - constituent.phase_deg
        )
        height += constituent.amplitude_m * math.cos(angle)
    return height


def predicted_depth_m(station: Station, moment: datetime) -> float:
    """Water depth (m) over the chart depth: chart depth plus tide height."""
    return station.chart_depth_m + tide_height_m(station, moment)


def hourly_predictions(station: Station, day: date) -> list[tuple[datetime, float]]:
    """One prediction per hour of the requested local day (24 rows)."""
    midnight = datetime.combine(day, dtime(0, 0))
    return [
        (
            midnight + timedelta(hours=hour),
            tide_height_m(station, midnight + timedelta(hours=hour)),
        )
        for hour in range(24)
    ]


def tide_extremes(
    station: Station, day: date, limit: int = 6
) -> list[tuple[datetime, str, float]]:
    """Local turning points (highs and lows) across the requested day."""
    midnight = datetime.combine(day, dtime(0, 0))
    step = timedelta(minutes=EXTREME_STEP_MINUTES)
    samples = []
    moment = midnight
    for _ in range(24 * 60 // EXTREME_STEP_MINUTES + 1):
        samples.append((moment, tide_height_m(station, moment)))
        moment += step

    extremes: list[tuple[datetime, str, float]] = []
    for index in range(1, len(samples) - 1):
        _, previous = samples[index - 1]
        stamp, current = samples[index]
        _, following = samples[index + 1]
        if current > previous and current >= following:
            extremes.append((stamp, "High", current))
        elif current < previous and current <= following:
            extremes.append((stamp, "Low", current))
    return extremes[:limit]


# --------------------------------------------------------------------------
# Moon model
# --------------------------------------------------------------------------

QUARTER_TOLERANCE_DAYS = 0.6  # principal phases are claimed only near their instant

PHASE_OUTLOOK: dict[str, str] = {
    "New Moon": "Dark nights and the smallest tidal range of the month (neap tides).",
    "Waxing Crescent": "Moonlight building; range still small, so high-tide depths stay modest.",
    "First Quarter": "Half-lit Moon; the tidal range is growing toward the next spring tide.",
    "Waxing Gibbous": "Bright evenings; range building toward the full-moon springs.",
    "Full Moon": "Full-moon springs: widest range of the month — highest highs, lowest lows.",
    "Waning Gibbous": "Bright late nights; the spring range is easing away.",
    "Last Quarter": "Half-lit waning Moon; range shrinking back toward neap.",
    "Waning Crescent": "Dark pre-dawn skies; the smallest ranges, with slack high water.",
}


@dataclass(frozen=True)
class MoonPhase:
    day: date
    phase_name: str
    illumination_pct: float
    age_days: float
    waxing: bool
    next_full_moon: date
    next_new_moon: date
    outlook: str


def moon_age_days(day: date) -> float:
    """Days since the last new moon, sampled at local noon for stability."""
    moment = datetime.combine(day, dtime(12, 0))
    elapsed = (moment - REFERENCE_NEW_MOON).total_seconds() / 86400.0
    return elapsed % SYNODIC_MONTH_DAYS


def _cycle_distance(age: float, target: float) -> float:
    """Shortest distance (days) between two ages on the lunation cycle."""
    delta = abs(age - target) % SYNODIC_MONTH_DAYS
    return min(delta, SYNODIC_MONTH_DAYS - delta)


def classify_phase(age: float) -> str:
    """Name the phase, claiming the four principal phases only near their instant.

    Cutting the lunation into equal eighths labels four consecutive days
    "First Quarter"; instead each quarter is reserved for a short window around
    its instant and the crescent/gibbous names fill the rest of the lunation.
    """
    quarter = SYNODIC_MONTH_DAYS / 4.0
    for target, name in (
        (0.0, "New Moon"),
        (quarter, "First Quarter"),
        (2.0 * quarter, "Full Moon"),
        (3.0 * quarter, "Last Quarter"),
    ):
        if _cycle_distance(age, target) <= QUARTER_TOLERANCE_DAYS:
            return name
    if age < quarter:
        return "Waxing Crescent"
    if age < 2.0 * quarter:
        return "Waxing Gibbous"
    if age < 3.0 * quarter:
        return "Waning Gibbous"
    return "Waning Crescent"


def moon_phase(day: date) -> MoonPhase:
    age = moon_age_days(day)
    phase_name = classify_phase(age)
    illumination = (
        (1.0 - math.cos(2.0 * math.pi * age / SYNODIC_MONTH_DAYS)) / 2.0 * 100.0
    )
    waxing = age < SYNODIC_MONTH_DAYS / 2.0
    days_to_full = (SYNODIC_MONTH_DAYS / 2.0 - age) % SYNODIC_MONTH_DAYS
    days_to_new = (-age) % SYNODIC_MONTH_DAYS
    return MoonPhase(
        day=day,
        phase_name=phase_name,
        illumination_pct=round(illumination, 1),
        age_days=round(age, 1),
        waxing=waxing,
        next_full_moon=day + timedelta(days=round(days_to_full)),
        next_new_moon=day + timedelta(days=round(days_to_new)),
        outlook=PHASE_OUTLOOK[phase_name],
    )


def moon_outlook(day: date, days: int = 7) -> list[MoonPhase]:
    return [moon_phase(day + timedelta(days=offset)) for offset in range(days)]


# --------------------------------------------------------------------------
# Safe harbor planning
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HarborWindow:
    """A daylight interval where the vessel floats, safe or not."""

    start: datetime
    end: datetime
    min_depth_m: float
    max_depth_m: float
    is_safe: bool
    touches_daylight_start: bool
    touches_daylight_end: bool

    @property
    def duration_minutes(self) -> int:
        return round((self.end - self.start).total_seconds() / 60.0)

    @property
    def verdict(self) -> str:
        return "SAFE" if self.is_safe else "UNSAFE"

    @property
    def note(self) -> str:
        return "clears draft + margin" if self.is_safe else "floats, below margin"


@dataclass(frozen=True)
class HarborPlan:
    station: Station
    day: date
    draft_m: float
    margin_m: float
    required_depth_m: float
    windows: tuple[HarborWindow, ...]
    peak_daylight_depth_m: float
    peak_daylight_time: datetime

    @property
    def safe_windows(self) -> tuple[HarborWindow, ...]:
        return tuple(window for window in self.windows if window.is_safe)

    @property
    def message(self) -> str | None:
        """Plain all-day message when nothing qualifies for this vessel."""
        if self.windows:
            return None
        return (
            f"No safe harbor windows for {self.station.name} on {self.day.isoformat()}: "
            f"predicted daylight depth peaks at {self.peak_daylight_depth_m:.2f} m at "
            f"{self.peak_daylight_time:%H:%M}, below the required "
            f"{self.required_depth_m:.2f} m (draft {self.draft_m:.2f} m + "
            f"margin {self.margin_m:.2f} m)."
        )


def plan_harbor(
    station: Station,
    day: date,
    draft_m: float,
    margin_m: float,
    step_minutes: int = SAMPLE_STEP_MINUTES,
) -> HarborPlan:
    """Split the daylight hours into stretches where the vessel floats.

    A window is a contiguous daylight stretch with predicted depth at or above
    the draft (the boat floats at all). Each window carries ``is_safe``, which
    is true only when its minimum depth also clears ``draft + margin`` — so a
    window can legitimately come back UNSAFE: enough water to float, none spare.
    """
    required = round(draft_m + margin_m, 2)
    start = datetime.combine(day, DAYLIGHT_START)
    end = datetime.combine(day, DAYLIGHT_END)
    step = timedelta(minutes=step_minutes)

    samples: list[tuple[datetime, float]] = []
    moment = start
    while moment <= end:
        samples.append((moment, predicted_depth_m(station, moment)))
        moment += step

    peak_time, peak_depth = max(samples, key=lambda sample: sample[1])

    windows: list[HarborWindow] = []
    run: list[tuple[datetime, float]] = []
    run_is_safe = False

    def close_run() -> None:
        if not run:
            return
        window_depths = [sample[1] for sample in run]
        windows.append(
            HarborWindow(
                start=run[0][0],
                end=run[-1][0],
                min_depth_m=round(min(window_depths), 2),
                max_depth_m=round(max(window_depths), 2),
                is_safe=run_is_safe,
                touches_daylight_start=run[0][0] == start,
                touches_daylight_end=run[-1][0] == end,
            )
        )

    for stamp, depth in samples:
        if depth < draft_m:
            close_run()
            run = []
            continue
        sample_is_safe = depth >= required
        if run and sample_is_safe != run_is_safe:
            close_run()
            run = []
        run_is_safe = sample_is_safe
        run.append((stamp, depth))
    close_run()

    return HarborPlan(
        station=station,
        day=day,
        draft_m=draft_m,
        margin_m=margin_m,
        required_depth_m=required,
        windows=tuple(windows),
        peak_daylight_depth_m=round(peak_depth, 2),
        peak_daylight_time=peak_time,
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _bar(
    value: float, low: float, high: float, width: int = 20, fill: str = "█"
) -> str:
    span = high - low
    fraction = 0.0 if span <= 0 else (value - low) / span
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return fill * filled + "·" * (width - filled)


def _trend(station: Station, moment: datetime, half_window: int = 30) -> str:
    """Slope of the tide around this hour (central difference, not hour-to-hour)."""
    delta = tide_height_m(
        station, moment + timedelta(minutes=half_window)
    ) - tide_height_m(station, moment - timedelta(minutes=half_window))
    if delta > 0.002:
        return "rising"
    if delta < -0.002:
        return "falling"
    return "slack"


def render_tide(station: Station, day: date) -> list[str]:
    predictions = hourly_predictions(station, day)
    heights = [height for _, height in predictions]
    low, high = min(heights), max(heights)

    lines = header_block(
        "tide",
        [
            ("Station", f"{station.name}  ({format_coordinates(station)})"),
            ("Date", f"{day.isoformat()}  {weekday_name(day)}"),
            ("Model", f"harmonics {' '.join(station.symbols)} · station local time"),
        ],
    )
    lines.append("")
    lines.append(f" {'Time':<5}  {'Height':>8}  {'Profile':<22}  Trend")
    lines += section_rule()
    for moment, height in predictions:
        lines.append(
            f" {moment:%H:%M}  {height:>6.2f} m  "
            f"{_bar(height, low, high):<22}  {_trend(station, moment)}"
        )
    lines += section_rule()

    extremes = tide_extremes(station, day)
    if extremes:
        parts = [
            f"{kind} {moment:%H:%M} {height:+.2f}" for moment, kind, height in extremes
        ]
        for index, chunk in enumerate(_wrap(" · ".join(parts), WIDTH - 2)):
            lines.append(muted((" " if index == 0 else "    ") + chunk))
    else:
        lines.append(muted(" no turning points inside this day (steady trend)"))
    lines.append(
        muted(
            f" heights in m · {len(predictions)} hourly rows · station local time"
            " · offline harmonic model"
        )
    )
    lines.append(
        muted(f" profile bar scaled to the day's range ({low:.2f} to {high:.2f} m)")
    )
    return lines


def render_moon(day: date) -> list[str]:
    phase = moon_phase(day)
    lines = header_block(
        "moon",
        [
            ("Date", f"{day.isoformat()}  {weekday_name(day)}"),
            ("Model", "local approximation · no time-zone conversion"),
        ],
    )
    lines.append("")
    lines.append(f" {'Phase':<13}{phase.phase_name}")
    lines.append(
        f" {'Illumination':<13}{phase.illumination_pct:>5.1f} %  "
        f"{_bar(phase.illumination_pct, 0.0, 100.0, width=20)}"
    )
    lines.append(
        f" {'Age':<13}{phase.age_days:>5.1f} days into a "
        f"{SYNODIC_MONTH_DAYS:.1f}-day lunation"
    )
    lines.append(f" {'Trend':<13}{'waxing' if phase.waxing else 'waning'}")
    lines.append(f" {'Next full':<13}{phase.next_full_moon.isoformat()}")
    lines.append(f" {'Next new':<13}{phase.next_new_moon.isoformat()}")
    outlook_lines = _wrap(phase.outlook, WIDTH - 15)
    lines.append(f" {'Outlook':<13}{outlook_lines[0] if outlook_lines else ''}")
    for extra in outlook_lines[1:]:
        lines.append(" " * 14 + extra)
    lines.append("")
    lines += section_rule("7-day outlook")
    lines.append(f" {'Date':<11}{'Phase':<18}{'Illum':>6}  Profile")
    lines += section_rule()
    for entry in moon_outlook(day, 7):
        bar = _bar(entry.illumination_pct, 0.0, 100.0, width=20)
        lines.append(
            f" {entry.day.isoformat():<11}{entry.phase_name:<18}"
            f"{entry.illumination_pct:>5.1f}%  {bar}"
        )
    lines += section_rule()
    lines.append(
        muted(
            " illumination and phase are approximate — a planning aid, not an ephemeris"
        )
    )
    return lines


def render_harbor(plan: HarborPlan) -> list[str]:
    station = plan.station
    lines = header_block(
        "harbor",
        [
            ("Station", f"{station.name}  ({format_coordinates(station)})"),
            ("Date", f"{plan.day.isoformat()}  {weekday_name(plan.day)}"),
            (
                "Vessel",
                (
                    f"draft {plan.draft_m:.2f} m + margin {plan.margin_m:.2f} m"
                    f" → need at least {plan.required_depth_m:.2f} m"
                ),
            ),
            (
                "Daylight",
                f"{DAYLIGHT_START:%H:%M} – {DAYLIGHT_END:%H:%M} station local time",
            ),
            (
                "Datum",
                f"{station.chart_depth_m:.2f} m chart depth, plus predicted tide",
            ),
        ],
    )
    lines.append("")

    if not plan.windows:
        message_lines = _wrap(plan.message or "No safe harbor windows.", WIDTH - 3)
        for index, chunk in enumerate(message_lines):
            lines.append((" ! " if index == 0 else "   ") + chunk)
        lines.append(
            muted(
                " suggest: a later date, a shallower draft, or a station with more water"
            )
        )
        return lines

    lines.append(
        f" windows are daylight stretches where depth clears the draft ({plan.draft_m:.2f} m);"
    )
    lines.append(
        f" SAFE needs the window minimum to clear {plan.required_depth_m:.2f} m"
        f" (draft + margin)"
    )
    lines.append(
        f" depth sampled every {SAMPLE_STEP_MINUTES} min across daylight; heights in m"
    )
    lines += section_rule()
    lines.append(
        f" {'Start':<7}{'End':<7}{'Duration':<10}{'Min depth':>9}"
        f"{'Peak':>9}  {'Verdict':<9}Note"
    )
    lines += section_rule()

    marked = False
    for window in plan.windows:
        start_label = f"{window.start:%H:%M}"
        end_label = f"{window.end:%H:%M}"
        if window.touches_daylight_start:
            start_label += "†"
            marked = True
        if window.touches_daylight_end:
            end_label += "†"
            marked = True
        verdict_render = (
            accent(window.verdict) if window.is_safe else bold(window.verdict)
        )
        lines.append(
            f" {start_label:<7}{end_label:<7}{format_duration(window.duration_minutes):<10}"
            f"{window.min_depth_m:>6.2f} m{window.max_depth_m:>6.2f} m  "
            f"{verdict_render:<9}{window.note}"
        )
    lines += section_rule()

    safe_count = len(plan.safe_windows)
    lines.append(
        bold(
            f" {len(plan.windows)} candidate window(s) · {safe_count} SAFE · "
            f"{len(plan.windows) - safe_count} UNSAFE"
        )
    )
    if marked:
        lines.append(muted(" † edge is the daylight limit, not a depth crossing"))
    if not safe_count:
        lines.append(
            f" ! No SAFE window: every candidate floats without the "
            f"{plan.margin_m:.2f} m margin."
        )
        lines.append(
            muted(
                " suggest: a later date, a shallower draft, or a station with more water"
            )
        )
    else:
        first = plan.safe_windows[0]
        lines.append(
            muted(
                f" best bet: {first.start:%H:%M}–{first.end:%H:%M} on {plan.day.isoformat()},"
                f" minimum {first.min_depth_m:.2f} m"
            )
        )
    return lines


def _moon_payload(phase: MoonPhase) -> dict[str, object]:
    return {
        "date": phase.day.isoformat(),
        "phase_name": phase.phase_name,
        "illumination_pct": phase.illumination_pct,
        "age_days": phase.age_days,
        "waxing": phase.waxing,
        "next_full_moon": phase.next_full_moon.isoformat(),
        "next_new_moon": phase.next_new_moon.isoformat(),
        "outlook": phase.outlook,
    }


def tide_payload(station: Station, day: date) -> dict[str, object]:
    predictions = hourly_predictions(station, day)
    return {
        "station": station.name,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "chart_depth_m": station.chart_depth_m,
        "constituents": [c.symbol for c in station.constituents],
        "date": day.isoformat(),
        "unit": "m",
        "hours": [
            {"time": f"{moment:%H:%M}", "height_m": round(height, 3)}
            for moment, height in predictions
        ],
        "extremes": [
            {
                "time": f"{moment:%H:%M}",
                "type": kind.lower(),
                "height_m": round(height, 3),
            }
            for moment, kind, height in tide_extremes(station, day)
        ],
    }


def moon_payload(day: date) -> dict[str, object]:
    phase = moon_phase(day)
    payload = _moon_payload(phase)
    payload["outlook_7day"] = [_moon_payload(entry) for entry in moon_outlook(day, 7)]
    return payload


def harbor_payload(plan: HarborPlan) -> dict[str, object]:
    return {
        "station": plan.station.name,
        "date": plan.day.isoformat(),
        "draft_m": plan.draft_m,
        "margin_m": plan.margin_m,
        "required_depth_m": plan.required_depth_m,
        "daylight": {
            "start": f"{DAYLIGHT_START:%H:%M}",
            "end": f"{DAYLIGHT_END:%H:%M}",
        },
        "sample_step_minutes": SAMPLE_STEP_MINUTES,
        "windows": [
            {
                "start_local": f"{window.start:%H:%M}",
                "end_local": f"{window.end:%H:%M}",
                "duration_minutes": window.duration_minutes,
                "min_depth_m": window.min_depth_m,
                "max_depth_m": window.max_depth_m,
                "margin_m": round(window.min_depth_m - plan.required_depth_m, 2),
                "is_safe": window.is_safe,
                "verdict": window.verdict,
                "touches_daylight_edge": window.touches_daylight_start
                or window.touches_daylight_end,
            }
            for window in plan.windows
        ],
        "safe_window_count": len(plan.safe_windows),
        "all_day_message": plan.message,
    }


# --------------------------------------------------------------------------
# Command handlers
# --------------------------------------------------------------------------


def emit(lines: Sequence[str]) -> None:
    print("\n".join(lines))


def emit_error(error: InputError) -> int:
    print(f"error: {error.message}", file=sys.stderr)
    if error.hint:
        print(f"hint: {error.hint}", file=sys.stderr)
    return 2


def _resolve_day(raw: str | None) -> date:
    if raw is None:
        return date.today()
    return parse_iso_date(raw)


def handle_tide(args: argparse.Namespace) -> int:
    try:
        station = find_station(args.station)
        day = parse_iso_date(args.date)
    except InputError as error:
        return emit_error(error)
    if args.json:
        print(json.dumps(tide_payload(station, day), indent=2))
    else:
        emit(render_tide(station, day))
    return 0


def handle_moon(args: argparse.Namespace) -> int:
    try:
        day = _resolve_day(args.date)
    except InputError as error:
        return emit_error(error)
    if args.json:
        print(json.dumps(moon_payload(day), indent=2))
    else:
        emit(render_moon(day))
    return 0


def handle_harbor(args: argparse.Namespace) -> int:
    try:
        station = find_station(args.station)
        day = parse_iso_date(args.date)
    except InputError as error:
        return emit_error(error)
    plan = plan_harbor(station, day, args.draft, args.margin)
    if args.json:
        print(json.dumps(harbor_payload(plan), indent=2))
    else:
        emit(render_harbor(plan))
    return 0


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

EPILOG = f"""\
embedded stations (exact names, quote the ones with spaces):
  {" · ".join(STATION_NAMES)}

examples:
  tideclock tide   --station "Cape May, NJ" --date 2025-06-01
  tideclock moon   --date 2025-06-01
  tideclock moon                        # today
  tideclock harbor --station "Bar Harbor, ME" --date 2025-06-01 --draft 2.0 --margin 0.5

exit codes: 0 success · 2 invalid date, number, or station name (message on stderr)
output:     results on stdout, diagnostics on stderr, --json for scripting
colour:     auto-disabled when stdout is not a TTY or NO_COLOR is set (also --no-color)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tideclock",
        description=(
            "Offline tide harmonic predictor, moon phase tracker, and safe harbor "
            "window planner for coastal paddlers and small boats."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"tideclock {__version__}"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colour even on a TTY",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{tide,moon,harbor}")

    tide = subparsers.add_parser(
        "tide",
        help="hourly tide heights for a station and date",
        description="Print an hourly tide-height table for a station and date.",
    )
    tide.add_argument(
        "--station", required=True, help='embedded station name, e.g. "Cape May, NJ"'
    )
    tide.add_argument(
        "--date", required=True, help="local date in strict ISO format YYYY-MM-DD"
    )
    tide.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tide.set_defaults(handler=handle_tide)

    moon = subparsers.add_parser(
        "moon",
        help="moon phase, illumination, and a 7-day outlook",
        description="Print the moon phase, illumination percentage, and a 7-day outlook.",
    )
    moon.add_argument("--date", help="local date YYYY-MM-DD (default: today)")
    moon.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    moon.set_defaults(handler=handle_moon)

    harbor = subparsers.add_parser(
        "harbor",
        help="daylight safe harbor windows from draft plus margin",
        description=(
            "Find daylight windows where predicted depth clears draft + margin, "
            "with start, end, minimum depth, and a SAFE/UNSAFE verdict."
        ),
    )
    harbor.add_argument(
        "--station", required=True, help='embedded station name, e.g. "Cape May, NJ"'
    )
    harbor.add_argument(
        "--date", required=True, help="local date in strict ISO format YYYY-MM-DD"
    )
    harbor.add_argument(
        "--draft",
        required=True,
        type=positive_number("draft"),
        help="vessel draft in metres (positive number)",
    )
    harbor.add_argument(
        "--margin",
        required=True,
        type=positive_number("margin"),
        help="safety margin in metres (positive number)",
    )
    harbor.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    harbor.set_defaults(handler=handle_harbor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    wants_json = bool(getattr(args, "json", False))
    requested_color = not getattr(args, "no_color", False)
    set_color(
        requested_color
        and not wants_json
        and sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
    )
    try:
        return int(args.handler(args))
    except BrokenPipeError:  # piped into `head` — exit quietly
        return 0


if __name__ == "__main__":
    sys.exit(main())
