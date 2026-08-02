# Micro-manual: editing a class preset

The preset tells the analyzer what a tack or gybe means for a particular boat, board or sailing class. Copy an existing JSON file, edit the numbers, then select it in the app. Keep the JSON structure and use decimal numbers with a dot, for example `1.5`, not `1,5`.

## The main settings

| Setting | Plain-language meaning | Practical guidance |
|---|---|---|
| `name` | Name shown in the report. | Use the class and format, for example `Olympic Formula Kite`. |
| `board_or_hull_length_m` | Board or hull length in metres. | Used for distance-related normalization or future class comparisons. |
| `smoothing_seconds` | Smoothing applied to compass/course direction. | More smoothing removes GPS noise but can hide very quick maneuvers. |
| `sog_smoothing_seconds` | Smoothing applied to speed-over-ground when calculating the minimum speed during a maneuver. | Usually 2–4 seconds; do not make it longer than the maneuver itself. |
| `stable_speed_kn` | Minimum speed for a sample to count as stable sailing. | Set below the normal upwind/downwind sailing speed, but above drifting or launching speed. |

## Tack and gybe definitions

The `tack` and `gybe` sections have the same timing controls. They can be different because classes often perform tacks and gybes at different speeds.

| Setting | Plain-language meaning |
|---|---|
| `before_crossing_s` | Seconds before the wind-axis crossing included in the maneuver window. |
| `after_crossing_s` | Seconds after the crossing included in the maneuver window. |
| `reference_before_s` | Length of the normal-sailing reference period before the maneuver. |
| `reference_after_s` | Length of the normal-sailing reference period after the maneuver. |
| `best_reference_s` | Rolling period used to find the best representative speed/VMG in each reference period. |
| `angle_threshold_deg` | Minimum total course change required for the event to be considered a real tack/gybe. This is a definition safeguard. |
| `target_threshold_deg` | How close the course must get to the wind axis: close to TWD for a tack, close to dead downwind for a gybe. |
| `min_separation_s` | Minimum time between two detected maneuvers. Increase it if one maneuver is being detected twice. |

The current default window is:

```text
Reference 10 s | Before 4 s | Crossing / maneuver 8 s | After 10 s
```

For a tack, the crossing is near head-to-wind. For a gybe, it is near dead downwind. The analyzer then measures entry, maneuver, and recovery performance around that crossing.

## Entry qualification

These settings decide whether the maneuver began with enough speed to be useful in statistics.

| Setting | Plain-language meaning |
|---|---|
| `threshold` | Required entry performance as a fraction of the block’s reference ceiling. `0.8` means 80%. |
| `ceiling_percentile` | Robust reference ceiling. `0.95` means the 95th percentile is used instead of the absolute fastest, noisy sample. |
| `entry_window_s` | How far before the maneuver window the analyzer looks for entry performance. |
| `rolling_seconds` | Rolling averaging period used when comparing speed and VMG. |
| `mode` | Which measure qualifies the entry: `either` = SOG or VMG can qualify; `both` = both must qualify; `sog` or `vmg` = use only that measure. |

Recommended starting point: `threshold: 0.8`, `ceiling_percentile: 0.95`, and `mode: "either"`. Review borderline or incorrectly recognized maneuvers in the app and exclude them manually when necessary.

## Example

```json
{
  "id": "my_class",
  "name": "My Class",
  "board_or_hull_length_m": 4.5,
  "smoothing_seconds": 1.5,
  "sog_smoothing_seconds": 3.0,
  "stable_speed_kn": 8.0,
  "tack": {
    "before_crossing_s": 4.0,
    "after_crossing_s": 8.0,
    "reference_before_s": 10.0,
    "reference_after_s": 10.0,
    "best_reference_s": 8.0,
    "angle_threshold_deg": 45.0,
    "target_threshold_deg": 30.0,
    "min_separation_s": 12.0
  },
  "gybe": {
    "before_crossing_s": 4.0,
    "after_crossing_s": 8.0,
    "reference_before_s": 10.0,
    "reference_after_s": 10.0,
    "best_reference_s": 8.0,
    "angle_threshold_deg": 20.0,
    "target_threshold_deg": 25.0,
    "min_separation_s": 12.0
  },
  "qualification": {
    "threshold": 0.8,
    "ceiling_percentile": 0.95,
    "entry_window_s": 10.0,
    "rolling_seconds": 3.0,
    "mode": "either"
  }
}
```

After editing, run one known session and check the number and timing of detected maneuvers. Change only a few settings at a time so the effect is easy to interpret.
