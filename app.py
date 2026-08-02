from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from maneuver_app.core import Segment, I18N, aggregate_statistics, analyze_session, calculate_metrics, load_preset, qualify_maneuvers, serializable_result, signed_angle_deg
from maneuver_app.report import build_report_html, distribution_figure, session_figure

ROOT = Path(__file__).parent
DEFAULT_PRESET = ROOT / "presets" / "olympic_formula_kite.json"
DEFAULT_ANNOTATIONS = (ROOT / "example_annotations.md").read_text(encoding="utf-8")

TEXT = {
    "pl": {"title": "Analiza manewrów Vakaros", "setup": "Import i ustawienia", "session": "Sesja i wiatr", "review": "Przegląd manewrów", "stats": "Statystyki", "report": "Raport", "run": "Analizuj plik", "language": "Język", "vkx": "Plik VKX", "annotations": "Zakresy treningu", "preset": "Preset klasy", "timezone": "Strefa czasowa (opcjonalnie)", "athlete": "Zawodnik / załoga", "class": "Klasa", "location": "Lokalizacja", "conditions": "Warunki", "equipment": "Sprzęt", "analyst": "Trener / analityk", "download": "Pobierz pakiet analizy", "html": "Pobierz raport HTML", "notice": "Otwórz raport HTML w przeglądarce i wybierz Drukuj → Zapisz jako PDF."},
    "en": {"title": "Vakaros maneuver analysis", "setup": "Import and setup", "session": "Session and wind", "review": "Maneuver review", "stats": "Statistics", "report": "Report", "run": "Analyze file", "language": "Language", "vkx": "VKX file", "annotations": "Training ranges", "preset": "Class preset", "timezone": "Timezone override (optional)", "athlete": "Athlete / crew", "class": "Class", "location": "Location", "conditions": "Conditions", "equipment": "Equipment", "analyst": "Coach / analyst", "download": "Download analysis bundle", "html": "Download HTML report", "notice": "Open the HTML report in a browser and choose Print → Save as PDF."},
}


def csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8")


def bundle_bytes(result: dict, annotation_text: str, metadata: dict) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("analysis.json", json.dumps(serializable_result(result), ensure_ascii=False, indent=2))
        archive.writestr("annotations.md", annotation_text)
        archive.writestr("maneuvers.csv", result["maneuvers"].to_csv(index=False))
        archive.writestr("statistics.csv", aggregate_statistics(result["maneuvers"]).to_csv(index=False))
        archive.writestr("telemetry_normalized.csv", result["telemetry"].to_csv(index=False))
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    return stream.getvalue()


def restore_bundle(upload) -> tuple[dict, str, dict]:
    with zipfile.ZipFile(io.BytesIO(upload.getvalue())) as archive:
        data = json.loads(archive.read("analysis.json"))
        telemetry = pd.read_csv(io.BytesIO(archive.read("telemetry_normalized.csv")), parse_dates=["timestamp_utc", "timestamp_local"])
        maneuvers = pd.read_csv(io.BytesIO(archive.read("maneuvers.csv")), parse_dates=["timestamp_utc", "timestamp_local"])
        metadata = json.loads(archive.read("metadata.json"))
        annotations = archive.read("annotations.md").decode("utf-8")
    segments = [Segment(start=pd.Timestamp(item["start"]), end=pd.Timestamp(item["end"]), maneuver_type=item["maneuver_type"], group=item.get("group", "standard"), notes=item.get("notes", ""), twd_deg=item.get("twd_deg")) for item in data["segments"]]
    return {"telemetry": telemetry, "maneuvers": maneuvers, "segments": segments, "preset": data["preset"], "meta": data["meta"], "timezone": data["timezone"], "inferred_timezone": data.get("inferred_timezone", data["timezone"]), "annotation_config": data.get("annotation_config", {})}, annotations, metadata


def manual_candidate(result: dict, maneuver_type: str, group: str, local_time, previous_state: str = "pending") -> dict:
    df = result["telemetry"]
    local_time = pd.Timestamp(local_time)
    if local_time.tzinfo is None:
        local_time = local_time.tz_localize(result["timezone"])
    segment = next(segment for segment in result["segments"] if segment.maneuver_type == maneuver_type and segment.group == group and segment.start <= local_time <= segment.end)
    row_index = int((df["timestamp_local"] - local_time).abs().idxmin())
    centre = df.loc[row_index, "timestamp_local"]
    relative = signed_angle_deg(df["cog_smooth_deg"], float(segment.twd_deg))
    before = float(relative[(df["timestamp_local"] >= centre - pd.Timedelta(seconds=4)) & (df["timestamp_local"] < centre)].median())
    after = float(relative[(df["timestamp_local"] > centre) & (df["timestamp_local"] <= centre + pd.Timedelta(seconds=4))].median())
    candidate = {"id": f"manual-{maneuver_type}-{centre:%H%M%S}", "timestamp_local": centre, "timestamp_utc": df.loc[row_index, "timestamp_utc"], "row_index": row_index, "type": maneuver_type, "group": group, "twd_deg": float(segment.twd_deg), "direction": "P->L" if before < after else "L->P", "target_distance_deg": 0.0, "state": previous_state, "manual_override": True}
    qualified = qualify_maneuvers(df, [candidate], result["segments"], result["preset"])[0]
    qualified["state"] = previous_state
    qualified["qualification_reason"] = "Manual timestamp; " + qualified["qualification_reason"]
    return calculate_metrics(df, qualified, result["preset"])


def timeline_figure(result: dict) -> go.Figure:
    df = result["telemetry"]
    fig = go.Figure()
    fig.add_trace(go.Scattergl(x=df["timestamp_local"], y=df["sog_kn"], name="SOG", line={"color": "#0f766e"}))
    for segment in result["segments"]:
        fig.add_vrect(x0=segment.start, x1=segment.end, fillcolor="#0f766e" if segment.maneuver_type == "tack" else "#ea580c", opacity=0.10, line_width=0)
    maneuvers = result["maneuvers"]
    if not maneuvers.empty:
        fig.add_trace(go.Scatter(x=maneuvers["timestamp_local"], y=[df.loc[int(i), "sog_kn"] for i in maneuvers["row_index"]], mode="markers", name="Maneuvers", marker={"color": "#111827", "size": 7, "symbol": "x"}))
    fig.update_layout(template="plotly_white", height=330, margin={"l": 35, "r": 20, "t": 30, "b": 35}, yaxis_title="SOG (kt)", legend={"orientation": "h"})
    return fig


def maneuver_figure(result: dict, row: pd.Series) -> go.Figure:
    df = result["telemetry"]
    centre = pd.Timestamp(row["timestamp_local"])
    sample = df[(df["timestamp_local"] >= centre - pd.Timedelta(seconds=16)) & (df["timestamp_local"] <= centre + pd.Timedelta(seconds=20))].copy()
    rel_time = (sample["timestamp_local"] - centre).dt.total_seconds()
    rel = signed_angle_deg(sample["cog_smooth_deg"], float(row["twd_deg"]))
    chart_index = pd.DatetimeIndex(sample["timestamp_utc"])
    sog_smooth = pd.Series(sample["sog_kn"].to_numpy(), index=chart_index).rolling("1.5s", center=True, min_periods=2).mean().to_numpy()
    vmg = sample["sog_kn"].to_numpy() * np.abs(np.cos(np.radians(rel.to_numpy())))
    vmg_smooth = pd.Series(vmg, index=chart_index).rolling("1.5s", center=True, min_periods=2).mean().to_numpy()
    angle_smooth = pd.Series(np.abs(rel.to_numpy()), index=chart_index).rolling("1.5s", center=True, min_periods=2).mean().to_numpy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rel_time, y=sog_smooth, name="SOG", line={"color": "#0f766e"}))
    fig.add_trace(go.Scatter(x=rel_time, y=vmg_smooth, name="VMG", line={"color": "#1d4ed8"}))
    fig.add_trace(go.Scatter(x=rel_time, y=angle_smooth, name="Angle to wind", yaxis="y2", line={"color": "#ea580c"}))
    before = result["preset"][row["type"]]["before_crossing_s"]
    after = result["preset"][row["type"]]["after_crossing_s"]
    fig.add_vrect(x0=-before, x1=after, fillcolor="#ea580c", opacity=0.12, line_width=0)
    for x, label in [(-before, f"-{before:.0f} s"), (0, "0"), (after, f"+{after:.0f} s")]:
        fig.add_vline(x=x, line_width=1, line_color="#111827", line_dash="dot")
        fig.add_annotation(x=x, y=1.02, yref="paper", text=label, showarrow=False, font={"size": 11, "color": "#111827"})
    fig.update_layout(template="plotly_white", height=380, margin={"l": 35, "r": 45, "t": 30, "b": 35}, xaxis_title="Seconds relative to crossing", yaxis_title="SOG / VMG (kt)", yaxis2={"title": "Angle (°)", "overlaying": "y", "side": "right"}, legend={"orientation": "h"})
    return fig


st.set_page_config(page_title="Vakaros Maneuver Analysis", page_icon="⛵", layout="wide")
language = st.sidebar.selectbox("Language / Język", ["pl", "en"], format_func=lambda x: "Polski" if x == "pl" else "English")
t = TEXT[language]
st.title(t["title"])
st.caption("VKX telemetry • segment-specific TWD • reviewable maneuver statistics")

with st.sidebar:
    st.header(t["setup"])
    vkx_upload = st.file_uploader(t["vkx"], type=["vkx"])
    bundle_upload = st.file_uploader("Analysis bundle / Pakiet analizy", type=["zip"])
    preset_upload = st.file_uploader(t["preset"], type=["json"])
    timezone_override = st.text_input(t["timezone"], placeholder="Europe/Paris")
    athlete = st.text_input(t["athlete"])
    sailing_class = st.text_input(t["class"], value="Olympic Formula Kite")
    location = st.text_input(t["location"])
    conditions = st.text_input(t["conditions"])
    equipment = st.text_input(t["equipment"])
    analyst = st.text_input(t["analyst"])
    analyze = st.button(t["run"], type="primary", disabled=vkx_upload is None)

annotations = st.text_area(t["annotations"], value=DEFAULT_ANNOTATIONS, height=180, help="Use local time ranges: 16:20:00-16:24:30 | sztagi | standard")

if analyze and vkx_upload:
    with tempfile.NamedTemporaryFile(suffix=".vkx", delete=False) as temp:
        temp.write(vkx_upload.getvalue())
        vkx_path = temp.name
    preset = load_preset(json.loads(preset_upload.getvalue().decode("utf-8"))) if preset_upload else load_preset(DEFAULT_PRESET)
    try:
        with st.spinner("Analyzing VKX telemetry..."):
            st.session_state.result = analyze_session(vkx_path, annotations, preset, timezone_override or None)
            st.session_state.annotation_text = annotations
            st.session_state.preset = preset
    except Exception as error:
        st.error(str(error))

if bundle_upload and st.button("Load bundle / Wczytaj pakiet"):
    try:
        restored, restored_annotations, restored_metadata = restore_bundle(bundle_upload)
        st.session_state.result = restored
        st.session_state.annotation_text = restored_annotations
        st.session_state.restored_metadata = restored_metadata
        st.rerun()
    except Exception as error:
        st.error(str(error))

if "result" not in st.session_state:
    st.info("Upload a VKX file, check the local-time ranges, and run the analysis.")
    st.stop()

result = st.session_state.result
restored_metadata = st.session_state.get("restored_metadata", {})
metadata = {"athlete": athlete or restored_metadata.get("athlete", ""), "sailing_class": sailing_class or restored_metadata.get("sailing_class", ""), "location": location or restored_metadata.get("location", ""), "conditions": conditions or restored_metadata.get("conditions", ""), "equipment": equipment or restored_metadata.get("equipment", ""), "analyst": analyst or restored_metadata.get("analyst", "")}
tabs = st.tabs([t["session"], t["review"], t["stats"], t["report"]])

with tabs[0]:
    columns = st.columns(4)
    columns[0].metric("Timezone", result["timezone"])
    columns[1].metric("Samples", f"{len(result['telemetry']):,}")
    columns[2].metric("Detected", len(result["maneuvers"]))
    columns[3].metric("Accepted", int((result["maneuvers"].get("state", pd.Series(dtype=str)) == "accepted").sum()))
    st.plotly_chart(session_figure(result), use_container_width=True)
    st.plotly_chart(timeline_figure(result), use_container_width=True)
    st.caption("TWD by block: " + ", ".join(f"{segment.group} {segment.maneuver_type}: {segment.twd_deg:.1f}°T" for segment in result["segments"]))

with tabs[1]:
    maneuvers = result["maneuvers"].copy()
    if maneuvers.empty:
        st.warning("No maneuvers detected in the supplied ranges.")
    else:
        review_columns = ["id", "timestamp_local", "type", "group", "direction", "state", "qualifies", "entry_sog_ratio", "entry_vmg_ratio", "loss_m", "loss_s"]
        review_display = maneuvers[review_columns].copy()
        for column in ["entry_sog_ratio", "entry_vmg_ratio"]:
            review_display[column] = (review_display[column] * 100).round(1).map(lambda value: f"{value:.1f}%")
        for column in ["loss_m", "loss_s"]:
            review_display[column] = review_display[column].round(1)
        edited = st.data_editor(review_display, use_container_width=True, hide_index=True, disabled=[column for column in review_columns if column not in ["state", "group"]], key="review_table")
        if st.button("Apply review decisions"):
            for index, record in edited.iterrows():
                match = result["maneuvers"]["id"] == record["id"]
                result["maneuvers"].loc[match, "state"] = record["state"]
                result["maneuvers"].loc[match, "group"] = record["group"]
                result["maneuvers"].loc[match, "manual_override"] = True
            st.session_state.result = result
            st.rerun()
        with st.expander("Add or move a maneuver / Dodaj lub przesuń manewr"):
            operation = st.radio("Operation / Operacja", ["Add / Dodaj", "Move / Przesuń"], horizontal=True)
            target_id = st.selectbox("Existing maneuver / Istniejący manewr", maneuvers["id"], disabled=operation.startswith("Add"))
            default_row = maneuvers.loc[maneuvers["id"] == target_id].iloc[0]
            local_date = result["telemetry"]["timestamp_local"].iloc[0].date()
            new_time = st.time_input("Local crossing time / Lokalny czas przecięcia", value=pd.Timestamp(default_row["timestamp_local"]).time())
            manual_type = st.selectbox("Type / Typ", ["tack", "gybe"], index=["tack", "gybe"].index(default_row["type"]))
            group_options = sorted({segment.group for segment in result["segments"] if segment.maneuver_type == manual_type})
            manual_group = st.selectbox("Group / Grupa", group_options)
            if st.button("Apply timestamp / Zastosuj czas"):
                timestamp = pd.Timestamp.combine(local_date, new_time).tz_localize(result["timezone"])
                try:
                    prior_state = "pending" if operation.startswith("Add") else str(default_row["state"])
                    replacement = manual_candidate(result, manual_type, manual_group, timestamp, prior_state)
                    if operation.startswith("Move"):
                        result["maneuvers"] = result["maneuvers"].loc[result["maneuvers"]["id"] != target_id]
                    result["maneuvers"] = pd.concat([result["maneuvers"], pd.DataFrame([replacement])], ignore_index=True)
                    st.session_state.result = result
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        choice = st.selectbox("Inspect maneuver", maneuvers["id"])
        row = result["maneuvers"].loc[result["maneuvers"]["id"] == choice].iloc[0]
        st.plotly_chart(maneuver_figure(result, row), use_container_width=True)
        st.caption(f"TWD {row.twd_deg:.1f}°T · entry SOG {row.entry_sog_ratio:.0%} · entry VMG {row.entry_vmg_ratio:.0%} · {row.qualification_reason}")

with tabs[2]:
    statistics = aggregate_statistics(result["maneuvers"])
    statistics_display = statistics.copy()
    for column in statistics_display.columns:
        if column not in ["type", "group", "direction", "count"]:
            statistics_display[column] = statistics_display[column].round(1)
    st.dataframe(statistics_display, use_container_width=True, hide_index=True)
    st.plotly_chart(distribution_figure(result["maneuvers"], language), use_container_width=True)

with tabs[3]:
    report_html = build_report_html(result, metadata, language)
    st.info(t["notice"])
    st.download_button(t["html"], report_html.encode("utf-8"), file_name="maneuver_report.html", mime="text/html")
    st.download_button(t["download"], bundle_bytes(result, st.session_state.annotation_text, metadata), file_name="maneuver_analysis_bundle.zip", mime="application/zip")
    st.components.v1.html(report_html, height=680, scrolling=True)
