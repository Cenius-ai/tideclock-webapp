"""TideClock test suite: CLI contract, tide model, moon model, harbor planner."""

import ast
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import tideclock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = PROJECT_ROOT / "tideclock.py"

TIDE_ROW = re.compile(r"^\s(\d{2}):(\d{2})\s+(-?\d+\.\d{2}) m\s+")
HARBOR_ROW = re.compile(
    r"^\s(\d{2}:\d{2})†?\s+(\d{2}:\d{2})†?\s+(\d+h \d{2}m)\s+"
    r"(\d+\.\d{2}) m\s+(\d+\.\d{2}) m\s+(SAFE|UNSAFE)\s+(\S.*)$"
)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI the way a user would, in a subprocess."""
    return subprocess.run(
        [sys.executable, str(ENTRYPOINT), *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=60,
        check=False,
    )


def tide_rows(stdout: str) -> list[tuple[str, float]]:
    rows = []
    for line in stdout.splitlines():
        match = TIDE_ROW.match(line)
        if match:
            rows.append((f"{match.group(1)}:{match.group(2)}", float(match.group(3))))
    return rows


def harbor_rows(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.splitlines():
        match = HARBOR_ROW.match(line)
        if match:
            rows.append(
                {
                    "start": match.group(1),
                    "end": match.group(2),
                    "duration": match.group(3),
                    "min_depth_m": float(match.group(4)),
                    "max_depth_m": float(match.group(5)),
                    "verdict": match.group(6),
                }
            )
    return rows


# ---------------------------------------------------------------- tide (F1)


def test_tide_prints_hourly_table_and_exits_zero():
    result = run_cli("tide", "--station", "Cape May, NJ", "--date", "2025-06-01")
    assert result.returncode == 0
    rows = tide_rows(result.stdout)
    assert len(rows) == 24, result.stdout
    assert [stamp for stamp, _ in rows] == [f"{hour:02d}:00" for hour in range(24)]
    assert "Cape May, NJ" in result.stdout
    assert "2025-06-01" in result.stdout
    assert result.stderr == ""


def test_tide_output_is_deterministic():
    first = run_cli("tide", "--station", "Seattle, WA", "--date", "2025-03-09")
    second = run_cli("tide", "--station", "Seattle, WA", "--date", "2025-03-09")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout


def test_tide_unknown_station_lists_embedded_stations():
    result = run_cli("tide", "--station", "Atlantis", "--date", "2025-06-01")
    assert result.returncode != 0
    assert "unknown station" in result.stderr
    assert "Atlantis" in result.stderr
    for name in tideclock.STATION_NAMES:
        assert name in result.stderr, f"{name} missing from unknown-station hint"
    assert result.stdout == ""


def test_tide_malformed_date_writes_validation_error_to_stderr():
    for bad_date in ("not-a-date", "2025-13-40", "2025-6-1", "06/01/2025", ""):
        result = run_cli("tide", "--station", "Cape May, NJ", "--date", bad_date)
        assert result.returncode != 0, bad_date
        assert "invalid date" in result.stderr, bad_date
        assert "YYYY-MM-DD" in result.stderr, bad_date
        assert "Traceback" not in result.stderr


def test_tide_requires_station_and_date():
    for args in (
        ("tide", "--date", "2025-06-01"),
        ("tide", "--station", "Cape May, NJ"),
    ):
        result = run_cli(*args)
        assert result.returncode != 0
        assert "required" in result.stderr


def test_station_lookup_is_exact_then_case_insensitive():
    station = tideclock.find_station("Cape May, NJ")
    assert station.name == "Cape May, NJ"
    assert tideclock.find_station("cape may, nj").name == "Cape May, NJ"
    with pytest.raises(tideclock.InputError):
        tideclock.find_station("Cape May")


def test_every_station_has_constituents_and_plausible_heights():
    for station in tideclock.STATIONS:
        assert station.constituents, station.name
        assert all(c.station_name == station.name for c in station.constituents)
        max_amplitude = sum(c.amplitude_m for c in station.constituents)
        moment = datetime(2025, 6, 1)
        for hour in range(0, 24 * 14, 7):  # two weeks of samples
            height = tideclock.tide_height_m(station, moment + timedelta(hours=hour))
            assert -max_amplitude - 1e-9 <= height <= max_amplitude + 1e-9


def test_stations_predict_different_tides():
    moment = datetime(2025, 6, 1, 12, 0)
    heights = {
        s.name: round(tideclock.tide_height_m(s, moment), 3) for s in tideclock.STATIONS
    }
    assert len(set(heights.values())) == len(heights)


def test_iso_date_parser_accepts_only_strict_iso():
    assert tideclock.parse_iso_date("2025-06-01") == date(2025, 6, 1)
    assert tideclock.parse_iso_date("2028-02-29") == date(2028, 2, 29)
    for bad in ("2025-02-29", "2025-06-01T00:00", "June 1 2025", "2025-06", "  "):
        with pytest.raises(tideclock.InputError):
            tideclock.parse_iso_date(bad)


# ---------------------------------------------------------------- moon (F2)


def test_moon_reports_phase_illumination_and_seven_day_outlook():
    result = run_cli("moon", "--date", "2025-06-01")
    assert result.returncode == 0
    assert "Waxing Crescent" in result.stdout
    assert "Illumination" in result.stdout
    assert "%" in result.stdout
    assert "7-day outlook" in result.stdout

    outlook_dates = re.findall(
        r"^\s(\d{4}-\d{2}-\d{2})\s+\w", result.stdout, re.MULTILINE
    )
    assert outlook_dates == [
        (date(2025, 6, 1) + timedelta(days=offset)).isoformat() for offset in range(7)
    ]


def test_moon_without_date_uses_today():
    result = run_cli("moon")
    assert result.returncode == 0
    assert date.today().isoformat() in result.stdout
    assert "Phase" in result.stdout


def test_moon_malformed_date_fails_loudly():
    result = run_cli("moon", "--date", "2025-13-40")
    assert result.returncode != 0
    assert "invalid date" in result.stderr
    assert result.stdout == ""


def test_moon_illumination_tracks_the_lunation():
    new_moon_day = date(2025, 5, 27)  # new moon 2025-05-27 03:02 UTC
    full_moon_day = date(2025, 6, 11)  # full moon 2025-06-11 07:44 UTC

    new_phase = tideclock.moon_phase(new_moon_day)
    assert new_phase.illumination_pct < 5.0
    assert new_phase.phase_name in {"New Moon", "Waning Crescent", "Waxing Crescent"}

    full_phase = tideclock.moon_phase(full_moon_day)
    assert full_phase.illumination_pct > 95.0
    assert full_phase.phase_name in {"Full Moon", "Waxing Gibbous", "Waning Gibbous"}


def test_moon_phase_cycle_is_continuous_over_a_lunation():
    ages = [
        tideclock.moon_age_days(date(2025, 6, 1) + timedelta(days=d)) for d in range(30)
    ]
    assert all(0.0 <= age < tideclock.SYNODIC_MONTH_DAYS for age in ages)
    for previous, current in zip(ages, ages[1:]):
        # ages advance by one day, wrapping at the end of the lunation
        assert abs(((current - previous) % tideclock.SYNODIC_MONTH_DAYS) - 1.0) < 0.01


def test_principal_phase_names_are_short_lived():
    names = {
        tideclock.classify_phase(age)
        for age in (
            index * 0.25 for index in range(int(tideclock.SYNODIC_MONTH_DAYS * 4))
        )
    }
    assert {"New Moon", "First Quarter", "Full Moon", "Last Quarter"} <= names
    assert {
        "Waxing Crescent",
        "Waxing Gibbous",
        "Waning Gibbous",
        "Waning Crescent",
    } <= names


# -------------------------------------------------------------- harbor (F3)


def test_harbor_windows_carry_verdicts_matching_the_threshold():
    result = run_cli(
        "harbor",
        "--station",
        "Cape May, NJ",
        "--date",
        "2025-06-01",
        "--draft",
        "2.0",
        "--margin",
        "0.5",
    )
    assert result.returncode == 0
    rows = harbor_rows(result.stdout)
    assert rows, result.stdout
    required = 2.0 + 0.5
    for row in rows:
        assert row["start"] != row["end"]
        assert row["end"] > row["start"]
        assert re.fullmatch(r"\d+h \d{2}m", row["duration"])
        assert row["max_depth_m"] >= row["min_depth_m"]
        expected = "SAFE" if row["min_depth_m"] >= required else "UNSAFE"
        assert row["verdict"] == expected, row
    assert {row["verdict"] for row in rows} <= {"SAFE", "UNSAFE"}


def test_harbor_plan_never_offers_a_window_below_the_draft():
    station = tideclock.find_station("Bar Harbor, ME")
    plan = tideclock.plan_harbor(station, date(2025, 9, 20), draft_m=2.6, margin_m=0.4)
    assert plan.windows
    step = timedelta(minutes=tideclock.SAMPLE_STEP_MINUTES)
    for window in plan.windows:
        moment = window.start
        while moment <= window.end:
            depth = tideclock.predicted_depth_m(station, moment)
            assert depth >= 2.6 - 1e-9, (window, moment, depth)
            moment += step
        assert round(window.min_depth_m, 2) >= 2.6
        assert window.is_safe == (window.min_depth_m >= plan.required_depth_m)


def test_harbor_rejects_non_positive_draft():
    for draft in ("0", "-1", "-2.5", "abc", ""):
        result = run_cli(
            "harbor",
            "--station",
            "Cape May, NJ",
            "--date",
            "2025-06-01",
            "--draft",
            draft,
            "--margin",
            "0.5",
        )
        assert result.returncode != 0, draft
        assert "draft must be a positive number" in result.stderr, (
            draft,
            result.stderr,
        )
        assert result.stdout == ""


def test_harbor_rejects_non_positive_or_non_numeric_margin():
    for margin in ("0", "-1", "abc"):
        result = run_cli(
            "harbor",
            "--station",
            "Cape May, NJ",
            "--date",
            "2025-06-01",
            "--draft",
            "2.0",
            "--margin",
            margin,
        )
        assert result.returncode != 0, margin
        assert "margin must be a positive number" in result.stderr, (
            margin,
            result.stderr,
        )
        assert result.stdout == ""


def test_harbor_prints_all_day_message_when_nothing_qualifies():
    result = run_cli(
        "harbor",
        "--station",
        "Cape May, NJ",
        "--date",
        "2025-06-01",
        "--draft",
        "99.0",
        "--margin",
        "0.5",
    )
    assert result.returncode == 0
    assert "No safe harbor windows" in result.stdout
    assert "Cape May, NJ" in result.stdout
    assert harbor_rows(result.stdout) == []
    assert result.stderr == ""


def test_harbor_all_day_message_is_carried_in_json_too():
    result = run_cli(
        "harbor",
        "--station",
        "Cape May, NJ",
        "--date",
        "2025-06-01",
        "--draft",
        "99.0",
        "--margin",
        "0.5",
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["windows"] == []
    assert payload["safe_window_count"] == 0
    assert "No safe harbor windows" in payload["all_day_message"]


def test_harbor_rejects_bad_date_and_station():
    bad_date = run_cli(
        "harbor",
        "--station",
        "Cape May, NJ",
        "--date",
        "2025-02-30",
        "--draft",
        "2.0",
        "--margin",
        "0.5",
    )
    assert bad_date.returncode != 0
    assert "invalid date" in bad_date.stderr

    bad_station = run_cli(
        "harbor",
        "--station",
        "Atlantis",
        "--date",
        "2025-06-01",
        "--draft",
        "2.0",
        "--margin",
        "0.5",
    )
    assert bad_station.returncode != 0
    assert "unknown station" in bad_station.stderr


# ------------------------------------------------------------ CLI contract


def test_bare_invocation_prints_help_and_exits_zero():
    result = run_cli()
    assert result.returncode == 0
    assert "usage: tideclock" in result.stdout
    assert (
        "tide" in result.stdout
        and "moon" in result.stdout
        and "harbor" in result.stdout
    )


def test_version_flag():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"tideclock {tideclock.__version__}"


def test_subcommand_help_lists_options():
    result = run_cli("harbor", "--help")
    assert result.returncode == 0
    for flag in ("--station", "--date", "--draft", "--margin", "--json"):
        assert flag in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("tide", "--station", "Cape May, NJ", "--date", "2025-06-01", "--json"),
        ("moon", "--date", "2025-06-01", "--json"),
        (
            "harbor",
            "--station",
            "Cape May, NJ",
            "--date",
            "2025-06-01",
            "--draft",
            "2.0",
            "--margin",
            "0.5",
            "--json",
        ),
    ],
)
def test_json_output_is_machine_readable(args):
    result = run_cli(*args)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["date"] == "2025-06-01"
    if args[0] == "tide":
        assert len(payload["hours"]) == 24
        assert payload["unit"] == "m"
        assert payload["station"] == "Cape May, NJ"
    elif args[0] == "moon":
        assert 0.0 <= payload["illumination_pct"] <= 100.0
        assert len(payload["outlook_7day"]) == 7
    else:
        assert payload["required_depth_m"] == 2.5
        assert all(
            window["verdict"] in {"SAFE", "UNSAFE"} for window in payload["windows"]
        )


def test_results_go_to_stdout_and_are_pipeable():
    result = run_cli("moon", "--date", "2025-06-01", "--json")
    assert result.stderr == ""
    payload = json.loads(result.stdout)  # parses cleanly => no diagnostics on stdout
    assert payload["phase_name"]


def test_module_imports_only_the_standard_library():
    tree = ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    allowed = {
        "__future__",
        "argparse",
        "dataclasses",
        "datetime",
        "json",
        "math",
        "os",
        "re",
        "sys",
        "typing",
        "collections",
    }
    assert modules <= allowed, modules - allowed


def test_no_network_calls_in_the_module():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    for forbidden in ("urllib", "socket", "http.client", "requests", "subprocess"):
        assert forbidden not in source, forbidden
