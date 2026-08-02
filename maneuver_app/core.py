from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

KNOTS_PER_MPS = 1.9438444924


I18N = {
    "pl": {"tack": "Sztag", "gybe": "Rufa", "accepted": "Zaakceptowany", "pending": "Do sprawdzenia", "excluded": "Wykluczony", "non_qualifying": "Niekwalifikowany"},
    "en": {"tack": "Tack", "gybe": "Gybe", "accepted": "Accepted", "pending": "Review", "excluded": "Excluded", "non_qualifying": "Non-qualifying"},
}


@dataclass
class Segment:
    start: pd.Timestamp
    end: pd.Timestamp
    maneuver_type: str
    group: str = "standard"
    notes: str = ""
    twd_deg: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        return data


def circular_distance_deg(a: np.ndarray | float, b: np.ndarray | float) -> np.ndarray | float:
    return np.abs((np.asarray(a) - np.asarray(b) + 180) % 360 - 180)


def circular_midpoint_deg(a: float, b: float) -> float:
    return float(np.degrees(np.angle(np.exp(1j * np.radians(a)) + np.exp(1j * np.radians(b)))) % 360)


def signed_angle_deg(course: pd.Series, twd_deg: float) -> pd.Series:
    return (course - twd_deg + 180) % 360 - 180


def local_xy_m(latitude: pd.Series, longitude: pd.Series) -> tuple[pd.Series, pd.Series]:
    lat0, lon0 = float(latitude.median()), float(longitude.median())
    north = (latitude - lat0) * 111_320.0
    east = (longitude - lon0) * 111_320.0 * math.cos(math.radians(lat0))
    return east, north


def infer_timezone(latitude: float, longitude: float) -> str:
    try:
        from timezonefinder import TimezoneFinder

        timezone = TimezoneFinder().timezone_at(lat=latitude, lng=longitude)
        return timezone or "UTC"
    except Exception:
        # Dependency-free fallback. It deliberately favors a visible, editable
        # regional guess over silently interpreting local annotations as UTC.
        if 35 <= latitude <= 72 and -10 <= longitude <= 30:
            return "Europe/Paris"
        if 24 <= latitude <= 50 and -125 <= longitude <= -66:
            return "America/New_York" if longitude >= -90 else "America/Los_Angeles"
        if -45 <= latitude <= -10 and 110 <= longitude <= 155:
            return "Australia/Sydney"
        return "UTC"


def parse_vkx(path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse VKX 1.4 telemetry without dropping unknown record types."""
    raw = Path(path).read_bytes()
    payload_sizes = {0x01: 32, 0x02: 44, 0x03: 20, 0x04: 13, 0x05: 17, 0x06: 18, 0x07: 12, 0x08: 13, 0x0A: 16, 0x0B: 16, 0x0C: 12, 0x0E: 16, 0x0F: 16, 0x10: 12, 0x20: 13, 0x21: 52, 0xFE: 2, 0xFF: 7}
    telemetry: list[tuple[Any, ...]] = []
    page_versions: dict[str, int] = {}
    record_counts: dict[str, int] = {}
    warnings: list[str] = []
    logging_rate_hz: int | None = None
    idx = 0
    while idx < len(raw):
        key = raw[idx]
        if key not in payload_sizes:
            raise ValueError(f"Unknown VKX record key 0x{key:02X} at byte {idx}; parsing stopped to preserve data integrity.")
        size = payload_sizes[key]
        end = idx + 1 + size
        if end > len(raw):
            raise ValueError(f"Truncated VKX record 0x{key:02X} at byte {idx}.")
        payload = raw[idx + 1:end]
        name = f"0x{key:02X}"
        record_counts[name] = record_counts.get(name, 0) + 1
        if key == 0xFF:
            version = payload[0]
            page_versions[str(version)] = page_versions.get(str(version), 0) + 1
        elif key == 0x08:
            _, _, logging_rate_hz = struct.unpack("<QIB", payload)
        elif key == 0x02:
            telemetry.append(struct.unpack("<Qii7f", payload))
        idx = end
    if not telemetry:
        raise ValueError("No primary 0x02 position/velocity/orientation records found in VKX file.")
    frame = pd.DataFrame(telemetry, columns=["timestamp_utc_ms", "latitude_deg_raw", "longitude_deg_raw", "sog_mps", "cog_rad", "altitude_m", "quaternion_w", "quaternion_x", "quaternion_y", "quaternion_z"])
    frame["latitude_deg"] = frame.pop("latitude_deg_raw") / 1e7
    frame["longitude_deg"] = frame.pop("longitude_deg_raw") / 1e7
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc_ms"], unit="ms", utc=True)
    frame["sog_kn"] = frame["sog_mps"] * KNOTS_PER_MPS
    frame["cog_deg"] = np.degrees(frame["cog_rad"]) % 360
    frame = frame.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").reset_index(drop=True)
    start, end = frame["timestamp_utc"].iloc[[0, -1]]
    meta = {"format": "Vakaros VKX", "page_versions": page_versions, "record_counts": record_counts, "warnings": warnings, "logging_rate_hz": logging_rate_hz, "telemetry_time_range_utc": [start.isoformat(), end.isoformat()]}
    return frame, meta


def prepare_telemetry(frame: pd.DataFrame, timezone_name: str, smoothing_seconds: float) -> pd.DataFrame:
    df = frame.copy()
    df["timestamp_local"] = df["timestamp_utc"].dt.tz_convert(timezone_name)
    index = pd.DatetimeIndex(df["timestamp_utc"])
    median_dt = max(float(index.to_series().diff().dt.total_seconds().median() or 0.2), 0.05)
    samples = max(3, int(round(smoothing_seconds / median_dt)))
    radians = np.radians(df["cog_deg"].to_numpy())
    # Pandas rolling coerces complex values to float. Average each circular
    # component separately so a 359°/1° course stays near north, not 180°.
    min_periods = max(2, samples // 2)
    mean_cos = pd.Series(np.cos(radians), index=index).rolling(samples, center=True, min_periods=min_periods).mean().to_numpy()
    mean_sin = pd.Series(np.sin(radians), index=index).rolling(samples, center=True, min_periods=min_periods).mean().to_numpy()
    df["cog_smooth_deg"] = np.degrees(np.arctan2(mean_sin, mean_cos)) % 360
    df["turn_rate_deg_s"] = np.gradient(np.unwrap(np.radians(df["cog_smooth_deg"])), index.view("int64") / 1e9) * 180 / np.pi
    df["east_m"], df["north_m"] = local_xy_m(df["latitude_deg"], df["longitude_deg"])
    return df


def load_preset(path_or_data: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(path_or_data, dict):
        return path_or_data
    return json.loads(Path(path_or_data).read_text(encoding="utf-8"))


def parse_annotations(text: str, session_date: date, timezone_name: str) -> tuple[list[Segment], dict[str, str]]:
    config: dict[str, str] = {}
    segments: list[Segment] = []
    tz = ZoneInfo(timezone_name)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and "|" not in line and not re.match(r"^\d{1,2}:\d{2}", line):
            key, value = line.split(":", 1)
            config[key.strip().lower()] = value.strip()
            continue
        parts = [part.strip() for part in line.split("|")]
        time_part = parts[0]
        match = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)(?:\s+(.*))?$", time_part)
        if match:
            start_text, end_text, trailing = match.groups()
            labels = " ".join([trailing or ""] + parts[1:]).lower()
        else:
            simple = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$", line)
            if not simple:
                raise ValueError(f"Cannot parse annotation line: {line}")
            start_text, labels = simple.groups()
            start = pd.Timestamp(f"{session_date.isoformat()} {start_text}", tz=tz)
            end = start + pd.Timedelta(minutes=4)
            maneuver_type = "tack" if any(word in labels.lower() for word in ("sztag", "tack")) else "gybe"
            segments.append(Segment(start=start, end=end, maneuver_type=maneuver_type, group="standard"))
            continue
        start = pd.Timestamp(f"{session_date.isoformat()} {start_text}", tz=tz)
        end = pd.Timestamp(f"{session_date.isoformat()} {end_text}", tz=tz)
        if end <= start:
            end += pd.Timedelta(days=1)
        maneuver_type = "tack" if any(word in labels for word in ("sztag", "tack")) else "gybe"
        group = next((x for x in ("szybkie", "wolne", "fast", "slow", "standard") if x in labels), "standard")
        segments.append(Segment(start=start, end=end, maneuver_type=maneuver_type, group=group))
    if not segments:
        raise ValueError("No maneuver ranges found in annotation file.")
    return segments, config


def _heading_peaks(courses: np.ndarray, speeds: np.ndarray) -> list[float]:
    usable = courses[np.isfinite(courses) & np.isfinite(speeds) & (speeds >= np.nanpercentile(speeds, 45))]
    if len(usable) < 20:
        return []
    hist, edges = np.histogram(usable, bins=np.arange(0, 362, 2))
    candidates: list[float] = []
    for index in np.argsort(hist)[::-1]:
        degree = float((edges[index] + edges[index + 1]) / 2) % 360
        if all(float(circular_distance_deg(degree, prior)) >= 25 for prior in candidates):
            candidates.append(degree)
        if len(candidates) == 2:
            break
    return candidates


def estimate_twd(df: pd.DataFrame, segment: Segment) -> float:
    block = df[(df["timestamp_local"] >= segment.start) & (df["timestamp_local"] <= segment.end)]
    peaks = _heading_peaks(block["cog_smooth_deg"].to_numpy(), block["sog_kn"].to_numpy())
    if len(peaks) < 2:
        raise ValueError(f"Insufficient stable heading data to estimate TWD for {segment.start:%H:%M:%S}-{segment.end:%H:%M:%S}.")
    midpoint = circular_midpoint_deg(peaks[0], peaks[1])
    return (midpoint + 180) % 360 if segment.maneuver_type == "gybe" else midpoint


def detect_maneuvers(df: pd.DataFrame, segment: Segment, preset: dict[str, Any]) -> list[dict[str, Any]]:
    twd = segment.twd_deg if segment.twd_deg is not None else estimate_twd(df, segment)
    settings = preset[segment.maneuver_type]
    block = df[(df["timestamp_local"] >= segment.start) & (df["timestamp_local"] <= segment.end)].copy().reset_index()
    rel = signed_angle_deg(block["cog_smooth_deg"], twd)
    target_distance = np.abs(rel) if segment.maneuver_type == "tack" else np.abs(np.abs(rel) - 180)
    threshold = settings["target_threshold_deg"]
    separated = pd.Timedelta(seconds=settings["min_separation_s"])
    candidates: list[int] = []
    radius = max(4, int(round(settings["min_separation_s"] * 1.25)))
    for i in range(radius, len(block) - radius):
        if target_distance.iloc[i] > threshold or target_distance.iloc[i] != target_distance.iloc[i - radius:i + radius + 1].min():
            continue
        ts = block.loc[i, "timestamp_local"]
        if candidates and ts - block.loc[candidates[-1], "timestamp_local"] < separated:
            if target_distance.iloc[i] < target_distance.iloc[candidates[-1]]:
                candidates[-1] = i
            continue
        before = float(rel.iloc[max(0, i - radius):i].median())
        after = float(rel.iloc[i + 1:min(len(block), i + radius + 1)].median())
        if before == 0 or after == 0 or np.sign(before) == np.sign(after):
            continue
        candidates.append(i)
    detected = []
    for number, i in enumerate(candidates, 1):
        before = float(rel.iloc[max(0, i - radius):i].median())
        after = float(rel.iloc[i + 1:min(len(block), i + radius + 1)].median())
        detected.append({"id": f"{segment.maneuver_type}-{segment.start:%H%M%S}-{number}", "timestamp_local": block.loc[i, "timestamp_local"], "timestamp_utc": block.loc[i, "timestamp_utc"], "row_index": int(block.loc[i, "index"]), "type": segment.maneuver_type, "group": segment.group, "twd_deg": twd, "direction": "P->L" if before < after else "L->P", "target_distance_deg": float(target_distance.iloc[i]), "state": "accepted", "manual_override": False})
    return detected


def refine_twd_from_maneuvers(df: pd.DataFrame, candidates: list[dict[str, Any]], maneuver_type: str) -> float | None:
    """Use stable headings either side of detected crossings to refine a block TWD."""
    estimates: list[float] = []
    for candidate in candidates:
        centre = pd.Timestamp(candidate["timestamp_local"])
        before = df[(df["timestamp_local"] >= centre - pd.Timedelta(seconds=8)) & (df["timestamp_local"] <= centre - pd.Timedelta(seconds=2))]["cog_smooth_deg"].median()
        after = df[(df["timestamp_local"] >= centre + pd.Timedelta(seconds=2)) & (df["timestamp_local"] <= centre + pd.Timedelta(seconds=8))]["cog_smooth_deg"].median()
        if pd.notna(before) and pd.notna(after):
            midpoint = circular_midpoint_deg(float(before), float(after))
            estimates.append((midpoint + 180) % 360 if maneuver_type == "gybe" else midpoint)
    if not estimates:
        return None
    return float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(estimates))))) % 360)


def _window(df: pd.DataFrame, centre: pd.Timestamp, start_s: float, end_s: float) -> pd.DataFrame:
    return df[(df["timestamp_local"] >= centre + pd.Timedelta(seconds=start_s)) & (df["timestamp_local"] <= centre + pd.Timedelta(seconds=end_s))].copy()


def _best_rolling(window: pd.DataFrame, column: str, seconds: float) -> float:
    if window.empty:
        return float("nan")
    series = window.set_index("timestamp_utc")[column].rolling(f"{seconds}s", min_periods=2).mean()
    return float(series.max())


def _integral_m(window: pd.DataFrame, column: str) -> float:
    if len(window) < 2:
        return float("nan")
    # Pandas 3 can store timestamps at microsecond precision; calculate an
    # explicit timedelta instead of assuming an int64 nanosecond unit.
    seconds = (window["timestamp_utc"] - window["timestamp_utc"].iloc[0]).dt.total_seconds().to_numpy()
    return float(np.trapezoid(window[column].to_numpy() / KNOTS_PER_MPS, seconds))


def calculate_metrics(df: pd.DataFrame, candidate: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    centre = pd.Timestamp(candidate["timestamp_local"])
    settings = preset[candidate["type"]]
    twd = candidate["twd_deg"]
    work = df.copy()
    relative = signed_angle_deg(work["cog_smooth_deg"], twd)
    work["vmg_kn"] = work["sog_kn"] * np.abs(np.cos(np.radians(relative)))
    work["vmg_signed_kn"] = work["sog_kn"] * np.cos(np.radians(relative))
    before = settings["before_crossing_s"]
    after = settings["after_crossing_s"]
    pre = _window(work, centre, -(settings["reference_before_s"] + before), -before)
    inside = _window(work, centre, -before, after)
    post = _window(work, centre, after, after + settings["reference_after_s"])
    best = settings["best_reference_s"]
    pre_vmg, post_vmg = _best_rolling(pre, "vmg_kn", best), _best_rolling(post, "vmg_kn", best)
    pre_sog, post_sog = _best_rolling(pre, "sog_kn", best), _best_rolling(post, "sog_kn", best)
    in_vmg = float(inside["vmg_kn"].mean())
    in_sog = float(inside["sog_kn"].mean())
    min_sog = float(inside.set_index("timestamp_utc")["sog_kn"].rolling(f"{preset['sog_smoothing_seconds']}s", center=True, min_periods=2).mean().min())
    reference_vmg = float(np.nanmean([pre_vmg, post_vmg]))
    duration_s = before + after
    loss_m = (reference_vmg - in_vmg) / KNOTS_PER_MPS * duration_s
    loss_s = loss_m / max(reference_vmg / KNOTS_PER_MPS, 0.01)
    return {**candidate, "pre_vmg_kn": pre_vmg, "in_vmg_kn": in_vmg, "post_vmg_kn": post_vmg, "pre_sog_kn": pre_sog, "in_sog_kn": in_sog, "post_sog_kn": post_sog, "min_sog_kn": min_sog, "up_dist_m": _integral_m(inside, "vmg_signed_kn"), "loss_m": loss_m, "loss_s": loss_s, "reference_vmg_kn": reference_vmg}


def qualify_maneuvers(df: pd.DataFrame, candidates: list[dict[str, Any]], segments: Iterable[Segment], preset: dict[str, Any]) -> list[dict[str, Any]]:
    qualification = preset["qualification"]
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        segment = next(s for s in segments if s.maneuver_type == candidate["type"] and s.group == candidate["group"] and s.start <= candidate["timestamp_local"] <= s.end)
        block = df[(df["timestamp_local"] >= segment.start) & (df["timestamp_local"] <= segment.end)].copy()
        rel = signed_angle_deg(block["cog_smooth_deg"], candidate["twd_deg"])
        block["vmg_kn"] = block["sog_kn"] * np.abs(np.cos(np.radians(rel)))
        settings = preset[candidate["type"]]
        target = np.abs(rel) if candidate["type"] == "tack" else np.abs(np.abs(rel) - 180)
        stable = block[(target > settings["target_threshold_deg"] + 10) & (block["sog_kn"] >= preset["stable_speed_kn"])]
        rolling = qualification["rolling_seconds"]
        sog_ceiling = _best_rolling(stable, "sog_kn", rolling)
        vmg_ceiling = _best_rolling(stable, "vmg_kn", rolling)
        entry = _window(block, candidate["timestamp_local"], -(settings["before_crossing_s"] + qualification["entry_window_s"]), -settings["before_crossing_s"])
        entry_sog, entry_vmg = _best_rolling(entry, "sog_kn", rolling), _best_rolling(entry, "vmg_kn", rolling)
        sog_ratio = entry_sog / sog_ceiling if sog_ceiling else float("nan")
        vmg_ratio = entry_vmg / vmg_ceiling if vmg_ceiling else float("nan")
        mode = qualification["mode"]
        if mode == "both":
            ratio, qualifies = min(sog_ratio, vmg_ratio), sog_ratio >= qualification["threshold"] and vmg_ratio >= qualification["threshold"]
        elif mode == "vmg":
            ratio, qualifies = vmg_ratio, vmg_ratio >= qualification["threshold"]
        elif mode == "sog":
            ratio, qualifies = sog_ratio, sog_ratio >= qualification["threshold"]
        else:
            ratio, qualifies = max(sog_ratio, vmg_ratio), max(sog_ratio, vmg_ratio) >= qualification["threshold"]
        item = {**candidate, "entry_sog_ratio": sog_ratio, "entry_vmg_ratio": vmg_ratio, "entry_performance_ratio": ratio, "qualifies": bool(qualifies), "qualification_reason": "Entry performance meets threshold" if qualifies else "Entry SOG and VMG below threshold"}
        if not qualifies and item["state"] == "accepted":
            item["state"] = "excluded"
        result.append(item)
    return result


def analyze_session(vkx_path: str | Path, annotation_text: str, preset: dict[str, Any] | str | Path, timezone_override: str | None = None) -> dict[str, Any]:
    preset_data = load_preset(preset)
    raw, meta = parse_vkx(vkx_path)
    inferred_timezone = infer_timezone(float(raw["latitude_deg"].median()), float(raw["longitude_deg"].median()))
    timezone_name = timezone_override or inferred_timezone
    df = prepare_telemetry(raw, timezone_name, preset_data["smoothing_seconds"])
    local_date = df["timestamp_local"].iloc[0].date()
    segments, annotation_config = parse_annotations(annotation_text, local_date, timezone_name)
    all_candidates: list[dict[str, Any]] = []
    for segment in segments:
        segment.twd_deg = estimate_twd(df, segment)
        candidates = detect_maneuvers(df, segment, preset_data)
        refined_twd = refine_twd_from_maneuvers(df, candidates, segment.maneuver_type)
        if refined_twd is not None:
            segment.twd_deg = refined_twd
            candidates = detect_maneuvers(df, segment, preset_data)
        all_candidates.extend(candidates)
    qualified = qualify_maneuvers(df, all_candidates, segments, preset_data)
    metrics = [calculate_metrics(df, candidate, preset_data) for candidate in qualified]
    maneuvers = pd.DataFrame(metrics)
    if not maneuvers.empty:
        maneuvers["timestamp_local"] = pd.to_datetime(maneuvers["timestamp_local"])
        maneuvers["timestamp_utc"] = pd.to_datetime(maneuvers["timestamp_utc"])
    return {"telemetry": df, "maneuvers": maneuvers, "segments": segments, "preset": preset_data, "meta": meta, "timezone": timezone_name, "inferred_timezone": inferred_timezone, "annotation_config": annotation_config}


def aggregate_statistics(maneuvers: pd.DataFrame) -> pd.DataFrame:
    if maneuvers.empty:
        return pd.DataFrame()
    included = maneuvers[maneuvers["state"] == "accepted"]
    metrics = ["loss_m", "loss_s", "pre_vmg_kn", "in_vmg_kn", "post_vmg_kn", "pre_sog_kn", "in_sog_kn", "post_sog_kn", "min_sog_kn", "up_dist_m"]
    summary = included.groupby(["type", "group", "direction"])[metrics].median().reset_index()
    counts = included.groupby(["type", "group", "direction"]).size().rename("count").reset_index()
    return summary.merge(counts, on=["type", "group", "direction"], how="left")


def serializable_result(result: dict[str, Any]) -> dict[str, Any]:
    return {"meta": result["meta"], "timezone": result["timezone"], "inferred_timezone": result["inferred_timezone"], "annotation_config": result["annotation_config"], "preset": result["preset"], "segments": [segment.to_dict() for segment in result["segments"]], "maneuvers": json.loads(result["maneuvers"].to_json(orient="records", date_format="iso")), "statistics": json.loads(aggregate_statistics(result["maneuvers"]).to_json(orient="records"))}
