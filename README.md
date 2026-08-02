# VKX Tack & Gybe Analyser

Streamlit application for analysing sailing maneuvers from Vakaros Atlas / Atlas 2 VKX telemetry logs.

The app helps sailing coaches review tacks and gybes, compare maneuver groups, identify speed and VMG losses, and prepare a bilingual Polish/English report that can be printed or saved as PDF.

## What the app does

The analysis workflow:

1. Reads GPS, course, speed-over-ground (SOG), and timing data from a VKX file.
2. Estimates the true wind direction (TWD) for the session.
3. Separates the track into upwind and downwind maneuver blocks.
4. Refines TWD separately for each block when conditions change.
5. Detects tacks in upwind blocks and gybes in downwind blocks.
6. Qualifies maneuver entries using configurable SOG and/or VMG thresholds.
7. Lets the coach review, regroup, accept, or exclude individual maneuvers.
8. Produces interactive charts, statistics, and a printable HTML report.

## Inputs

The app accepts:

- a Vakaros `.vkx` telemetry file;
- a `.txt` or `.md` annotation file containing approximate local times and maneuver groups.

Annotation lines may use this form:

```text
HH:MM:SS-HH:MM:SS | maneuver type | group name
```

Supported maneuver labels include:

- Polish: `sztag`, `sztagi`, `rufa`, `rufy`;
- English: `tack`, `gybe`.

The third field is a coach-defined comparison group. The app can infer a timezone from the VKX GPS position; a timezone can also be explicitly provided in the annotation file.

## Maneuver definitions

Tack and gybe definitions are configured separately for each sailing class.

Presets control:

- the course-angle threshold for recognizing a maneuver;
- how close the course must get to head-to-wind or dead downwind;
- the analysis window before and after the crossing;
- the reference periods used to compare normal sailing performance;
- the minimum time between two detected maneuvers;
- the minimum entry-performance threshold for inclusion in statistics.

Presets are stored as JSON files in `presets/`. Coaches can copy and edit a preset for another boat, board, or class.

See [PRESET_MICRO_MANUAL.md](PRESET_MICRO_MANUAL.md) for a plain-language explanation of every setting.

## Report contents

The report includes:

- session information and data-quality indicators;
- class definitions and analysis settings;
- track and maneuver blocks oriented to the wind direction;
- maneuver statistics grouped by type, group, and direction;
- box-and-whisker distributions;
- an individual maneuver list;
- Entry SOG Ratio and Entry VMG Ratio;
- maneuver speed/VMG charts with timing reference lines.

The HTML report can be saved as a PDF using the browser's **Print -> Save as PDF** command.

## Run locally

Create a virtual environment and install the pinned dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the application:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app.py
```

Open the local URL shown by Streamlit, normally `http://localhost:8501`.

The local `.venv`, uploaded telemetry, generated reports, and analysis bundles are intentionally excluded from Git.

## Streamlit Community Cloud

1. Connect the GitHub repository to Streamlit Community Cloud.
2. Select the `main` branch.
3. Set the entrypoint file to `app.py`.
4. Select Python 3.12 in the advanced deployment settings.
5. Deploy.

Streamlit installs the packages listed in `requirements.txt`. The repository contains a light-theme configuration in `.streamlit/config.toml`.

Uploaded files are processed in the app session. Download the analysis bundle or report if the results need to be retained.

## Command-line analysis

The non-UI workflow can be run with:

```powershell
.\.venv\Scripts\python.exe run_analysis.py `
  --vkx "path\to\session.vkx" `
  --annotations "path\to\annotations.md" `
  --output "output\session"
```

The command creates normalized telemetry, maneuver data, statistics, analysis JSON, and an HTML report.

## Project structure

```text
app.py                    Streamlit user interface
maneuver_app/core.py      VKX parsing and maneuver analysis
maneuver_app/report.py    HTML report and charts
presets/                  Class preset JSON files
tests/                    Automated tests
requirements.txt          Pinned Python dependencies
.streamlit/config.toml    Streamlit configuration
```

## Validation

Run the automated checks locally:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py maneuver_app run_analysis.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

GitHub Actions repeats the source compilation and test checks after pushes and pull requests.

## Language

The user interface and generated report support Polish and English. Sailing and telemetry abbreviations such as TWD, SOG, VMG, and COG remain unchanged between languages.
