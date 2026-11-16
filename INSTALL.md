# Installing TideClock

TideClock is a single Python file that uses only the standard library. "Installing" it is
optional — copying `tideclock.py` to a machine with Python 3.9+ is enough to run it.

## Prerequisites

| Requirement | Version | Notes |
| --- | --- | --- |
| Python interpreter | 3.9 or newer | `python3 --version`. The tool uses no third-party runtime packages. |
| pip (optional) | any recent | Only needed for the `tideclock` console script and the test runner. |

Nothing else is required: no compiler, no database, no network access at runtime, no system
packages. Do **not** run `sudo`, and do not install system packages — `install.sh` installs
project-level Python packages only and needs no privileges (it falls back to a per-user install
if the interpreter's `site-packages` is read-only).

## 1. Set up (one command, then it exits)

```bash
bash install.sh
```

What it does, in order:

1. refreshes `pip`/`setuptools`/`wheel` (best effort — an offline machine keeps the installed ones);
2. installs the declared dependencies from `requirements.txt` (the `pytest` test runner);
3. registers the `tideclock` console script with `pip install -e .`;
4. self-checks by importing the module and rendering one prediction.

It is idempotent — run it again any time — and it **exits**; the tool is a CLI, not a server, so
there is nothing to start afterwards.

## 2. Run it

```bash
tideclock --help
tideclock tide   --station "Cape May, NJ" --date 2025-06-01
tideclock moon   --date 2025-06-01
tideclock harbor --station "Bar Harbor, ME" --date 2025-09-20 --draft 2.6 --margin 0.4
```

If `tideclock` is not on your `PATH` (common with `pip install --user`, where scripts land in
`~/.local/bin`), run the file directly — it is the same program:

```bash
python3 tideclock.py moon --date 2025-06-01
```

## 3. Verify the install

```bash
python3 -m pytest        # the project test suite
sh demo.sh               # non-interactive walkthrough of all three commands
```

## No environment file needed

TideClock reads **no** environment variables and needs no configuration, no `.env`, and no
credentials. `.env.example` is committed only to document that fact — copying it changes nothing.

## Uninstalling

```bash
python3 -m pip uninstall tideclock
```

Deleting the project directory removes everything else; no state is written outside it.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `tideclock: command not found` | The console script directory is not on `PATH`. Use `python3 tideclock.py …` or add `~/.local/bin` to `PATH`. |
| `error: invalid date '2025-6-1'` | Dates must be strict ISO `YYYY-MM-DD`, zero-padded. |
| `error: unknown station 'Cape May'` | Station names must match an embedded name exactly (case-insensitive). Quote names with spaces: `--station "Cape May, NJ"`. The error lists every embedded station. |
| `error: argument --draft: draft must be a positive number` | Draft and margin must be finite values greater than zero. |
| `No safe harbor windows …` (exit 0) | A valid answer: no daylight stretch in this model reaches `draft + margin`. Try a later date, a shallower draft, or a station with more water. |
