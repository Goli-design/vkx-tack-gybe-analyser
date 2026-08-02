from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

from .core import I18N, aggregate_statistics, signed_angle_deg


LABELS = {
    "pl": {"title": "Analiza manewrów", "session": "Sesja", "quality": "Jakość danych", "definition": "Definicje i ustawienia", "track": "Trasa i bloki manewrów", "tacks": "Sztagi", "gybes": "Rufy", "statistics": "Statystyki", "appendix": "Lista manewrów", "time": "Czas lokalny", "direction": "Kierunek", "group": "Grupa", "athlete": "Zawodnik / załoga", "class": "Klasa", "location": "Lokalizacja", "conditions": "Warunki", "equipment": "Sprzęt", "analyst": "Trener / analityk", "data_quality": "Jakość danych", "description": "Opis", "loss_m": "Strata (m)", "loss_s": "Strata (s)", "pre_vmg_kn": "PreVMG (kt)", "in_vmg_kn": "InVMG (kt)", "post_vmg_kn": "PostVMG (kt)", "pre_sog_kn": "PreSOG (kt)", "in_sog_kn": "InSOG (kt)", "post_sog_kn": "PostSOG (kt)", "min_sog_kn": "MinSOG (kt)", "up_dist_m": "UpDist (m)", "count": "Liczba"},
    "en": {"title": "Maneuver analysis", "session": "Session", "quality": "Data quality", "definition": "Definitions and settings", "track": "Track and maneuver blocks", "tacks": "Tacks", "gybes": "Gybes", "statistics": "Statistics", "appendix": "Maneuver list", "time": "Local time", "direction": "Direction", "group": "Group", "athlete": "Athlete / crew", "class": "Class", "location": "Location", "conditions": "Conditions", "equipment": "Equipment", "analyst": "Coach / analyst", "data_quality": "Data Quality", "description": "Description", "loss_m": "Loss (m)", "loss_s": "Loss (s)", "pre_vmg_kn": "PreVMG (kt)", "in_vmg_kn": "InVMG (kt)", "post_vmg_kn": "PostVMG (kt)", "pre_sog_kn": "PreSOG (kt)", "in_sog_kn": "InSOG (kt)", "post_sog_kn": "PostSOG (kt)", "min_sog_kn": "MinSOG (kt)", "up_dist_m": "UpDist (m)", "count": "Count"},
}


def _fig_html(fig: go.Figure, include_js: bool = False) -> str:
    return pio.to_html(fig, full_html=False, include_plotlyjs="inline" if include_js else False, config={"displayModeBar": False, "responsive": True})


def session_figure(result: dict[str, Any]) -> go.Figure:
    df = result["telemetry"]
    twd_values = [segment.twd_deg for segment in result["segments"] if segment.twd_deg is not None]
    twd = float((np.angle(np.mean(np.exp(1j * np.radians(twd_values)))) * 180 / np.pi) % 360) if twd_values else 0.0
    east, north = df["east_m"].to_numpy(), df["north_m"].to_numpy()
    twd_rad = np.radians(twd)
    crosswind = east * np.cos(twd_rad) - north * np.sin(twd_rad)
    toward_wind = east * np.sin(twd_rad) + north * np.cos(twd_rad)
    fig = go.Figure(go.Scattergl(x=crosswind, y=toward_wind, mode="lines", line={"width": 1.5, "color": "#7b8794"}, name="Track"))
    colors = {"tack": "#0f766e", "gybe": "#ea580c"}
    for segment in result["segments"]:
        block = df[(df["timestamp_local"] >= segment.start) & (df["timestamp_local"] <= segment.end)]
        block_east, block_north = block["east_m"].to_numpy(), block["north_m"].to_numpy()
        fig.add_trace(go.Scattergl(x=block_east * np.cos(twd_rad) - block_north * np.sin(twd_rad), y=block_east * np.sin(twd_rad) + block_north * np.cos(twd_rad), mode="lines", line={"width": 3, "color": colors[segment.maneuver_type]}, name=segment.group))
    m = result["maneuvers"]
    if not m.empty:
        rows = df.loc[m["row_index"].astype(int)]
        row_east, row_north = rows["east_m"].to_numpy(), rows["north_m"].to_numpy()
        fig.add_trace(go.Scatter(x=row_east * np.cos(twd_rad) - row_north * np.sin(twd_rad), y=row_east * np.sin(twd_rad) + row_north * np.cos(twd_rad), mode="markers", marker={"size": 7, "color": "#111827", "symbol": "x"}, name="Maneuvers"))
    fig.update_layout(template="plotly_white", height=430, margin={"l": 30, "r": 20, "t": 35, "b": 35}, xaxis_title="Cross-wind (m)", yaxis_title=f"Toward TWD (m) · TWD {twd:.1f}°T", yaxis={"scaleanchor": "x", "scaleratio": 1}, legend={"orientation": "h"})
    return fig


def distribution_figure(maneuvers: pd.DataFrame, language: str) -> go.Figure:
    labels = LABELS[language]
    included = maneuvers[maneuvers["state"] == "accepted"]
    fig = go.Figure()
    colors = {"tack": "#0f766e", "gybe": "#ea580c"}
    for (maneuver_type, group, direction), data in included.groupby(["type", "group", "direction"], sort=True):
        if data.empty:
            continue
        direction_label = direction_for_language(direction, language)
        group_label = group if group != "standard" else I18N[language][maneuver_type]
        values = data["loss_m"].dropna().to_numpy()
        if not len(values):
            continue
        q1, median, q3 = np.percentile(values, [25, 50, 75])
        iqr = q3 - q1
        lower_fence, upper_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        category = f"{group_label} {direction_label}"
        # Explicitly provide the category on the x axis.  When q1/median/q3
        # are supplied without x, Plotly puts every summary box at the same
        # implicit numeric position (usually x=0), which makes the boxes
        # overlap and pushes the observed-value markers away from them.
        fig.add_trace(go.Box(x=[category], q1=[q1], median=[median], q3=[q3], lowerfence=[lower_fence], upperfence=[upper_fence], name=category, boxpoints=False, marker_color=colors[maneuver_type], legendgroup=maneuver_type, hovertemplate="Fence: %{y:.1f} m<extra>" + category + "</extra>"))
        fig.add_trace(go.Scatter(x=[category, category], y=[float(values.min()), float(values.max())], mode="markers", marker={"symbol": "line-ew", "size": 11, "color": "#111827"}, name="Observed min/max", showlegend=False, hovertemplate="Observed min/max: %{y:.1f} m<extra>" + category + "</extra>"))
    fig.update_layout(template="plotly_white", height=360, margin={"l": 35, "r": 20, "t": 35, "b": 75}, yaxis_title=labels["loss_m"], showlegend=False, xaxis={"tickangle": -35})
    return fig


def direction_for_language(direction: str, language: str) -> str:
    if language == "en":
        return {"P->L": "S->P", "L->P": "P->S"}.get(direction, direction)
    return direction


def definition_html(result: dict[str, Any], labels: dict[str, str], language: str) -> str:
    tack = result["preset"]["tack"]
    gybe = result["preset"]["gybe"]
    qualification = result["preset"]["qualification"]
    if language == "pl":
        tack_text = f"Sztag to zmiana między dwoma halsami na wiatr. Przecięcie następuje w najbliższym punkcie względem TWD (bajdewind / head-to-wind), przy całkowitej zmianie kursu co najmniej {tack['angle_threshold_deg']:.0f}°."
        tack_note = "Linia środkowa oznacza przecięcie osi wiatru. Metryki porównują wejście, wykonanie manewru i odzyskanie prędkości."
        gybe_text = f"Rufa to zmiana między dwoma halsami z wiatrem. Przecięcie następuje w najbliższym punkcie względem kierunku z wiatrem (180° od TWD), przy całkowitej zmianie kursu co najmniej {gybe['angle_threshold_deg']:.0f}°."
        gybe_note = f"Kwalifikacja wejścia: domyślnie co najmniej {qualification['threshold']:.0%} odpornego maksimum SOG lub VMG dla bloku."
        reference, before, crossing, after = "Referencja", "Przed", "Przecięcie / manewr", "Po"
    else:
        tack_text = f"A tack is a change between the two upwind sides. The crossing is the closest point to TWD (head-to-wind), with a total course-angle change of at least {tack['angle_threshold_deg']:.0f}°."
        tack_note = "The central line is the head-to-wind crossing. Metrics compare entry, maneuver, and recovery performance."
        gybe_text = f"A gybe is a change between the two downwind sides. The crossing is the closest point to dead downwind (180° from TWD), with a total course-angle change of at least {gybe['angle_threshold_deg']:.0f}°."
        gybe_note = f"Entry qualification: at least {qualification['threshold']:.0%} of the robust block SOG or VMG ceiling by default."
        reference, before, crossing, after = "Reference", "Before", "Crossing / maneuver", "After"
    return f"""<div class=\"definition-grid\"><div class=\"definition-card\"><h3>{labels['tacks']}</h3><p>{tack_text}</p><div class=\"timeline\"><span class=\"sail\">{reference} {tack['reference_before_s']:.0f}s</span><span class=\"pre\">{before} {tack['before_crossing_s']:.0f}s</span><span class=\"maneuver\">{crossing} {tack['after_crossing_s']:.0f}s</span><span class=\"sail\">{after} {tack['reference_after_s']:.0f}s</span></div><p class=\"muted\">{tack_note}</p></div><div class=\"definition-card\"><h3>{labels['gybes']}</h3><p>{gybe_text}</p><div class=\"timeline\"><span class=\"sail\">{reference} {gybe['reference_before_s']:.0f}s</span><span class=\"pre\">{before} {gybe['before_crossing_s']:.0f}s</span><span class=\"maneuver\">{crossing} {gybe['after_crossing_s']:.0f}s</span><span class=\"sail\">{after} {gybe['reference_after_s']:.0f}s</span></div><p class=\"muted\">{gybe_note}</p></div></div>"""


def build_report_html(result: dict[str, Any], metadata: dict[str, str], language: str = "pl") -> str:
    labels = LABELS[language]
    maneuvers = result["maneuvers"].copy()
    stats = aggregate_statistics(maneuvers)
    session = session_figure(result)
    distributions = distribution_figure(maneuvers, language)
    settings = result["preset"]
    fields_left = [(labels["athlete"], metadata.get("athlete", "")), (labels["class"], metadata.get("sailing_class", "")), (labels["location"], metadata.get("location", "")), (labels["conditions"], metadata.get("conditions", ""))]
    fields_right = [(labels["equipment"], metadata.get("equipment", "")), (labels["analyst"], metadata.get("analyst", "")), (labels["time"], f"{str(result['telemetry']['timestamp_local'].iloc[0])[:19]} - {str(result['telemetry']['timestamp_local'].iloc[-1])[:19]}"), ("TWD blocks", ", ".join(f"{s.twd_deg:.1f}°T" for s in result["segments"]))]
    metadata_left_html = "".join(f"<tr><th>{escape(key)}</th><td>{escape(value or '—')}</td></tr>" for key, value in fields_left)
    metadata_right_html = "".join(f"<tr><th>{escape(key)}</th><td>{escape(value or '—')}</td></tr>" for key, value in fields_right)
    columns = ["type", "group", "direction", "count", "loss_m", "loss_s", "pre_vmg_kn", "in_vmg_kn", "post_vmg_kn", "pre_sog_kn", "in_sog_kn", "post_sog_kn", "min_sog_kn", "up_dist_m"]
    display = stats.reindex(columns=columns)
    display = display.rename(columns={key: labels.get(key, key) for key in display.columns})
    direction_column = labels["direction"]
    if direction_column in display:
        display[direction_column] = display[direction_column].map(lambda value: direction_for_language(value, language))
    type_column = "type"
    if type_column in display:
        display[type_column] = display[type_column].map(lambda value: I18N[language].get(value, value))
    stats_html = display.round(1).to_html(index=False, border=0, classes="data-table") if not display.empty else "<p>—</p>"
    appendix = maneuvers[["timestamp_local", "type", "group", "direction", "state", "qualifies", "loss_m", "loss_s", "entry_sog_ratio", "entry_vmg_ratio"]].copy() if not maneuvers.empty else pd.DataFrame()
    if not appendix.empty:
        appendix["timestamp_local"] = appendix["timestamp_local"].dt.strftime("%H:%M:%S")
        appendix["type"] = appendix["type"].map(lambda value: I18N[language].get(value, value))
        appendix["state"] = appendix["state"].map(lambda value: I18N[language].get(value, value))
        appendix["entry_sog_ratio"] = (appendix["entry_sog_ratio"] * 100).round(1).map(lambda value: f"{value:.1f}%")
        appendix["entry_vmg_ratio"] = (appendix["entry_vmg_ratio"] * 100).round(1).map(lambda value: f"{value:.1f}%")
        appendix = appendix.rename(columns={"timestamp_local": labels["time"], "type": "Type", "group": labels["group"], "direction": labels["direction"], "state": "Status", "qualifies": "Qualifies", "loss_m": labels["loss_m"], "loss_s": labels["loss_s"], "entry_sog_ratio": "Entry SOG ratio", "entry_vmg_ratio": "Entry VMG ratio"})
    appendix_html = appendix.round(1).to_html(index=False, border=0, classes="data-table") if not appendix.empty else "<p>—</p>"
    quality = result["meta"]
    definition = (f"Okno sztagu/rufy: {settings['tack']['before_crossing_s']:.0f}s + {settings['tack']['after_crossing_s']:.0f}s. Kwalifikacja wejścia: {settings['qualification']['threshold']:.0%}, SOG lub VMG, odporne maksimum p{settings['qualification']['ceiling_percentile']:.0%}." if language == "pl" else f"Tack/Gybe window: {settings['tack']['before_crossing_s']:.0f}s + {settings['tack']['after_crossing_s']:.0f}s. Entry qualification: {settings['qualification']['threshold']:.0%}, either SOG/VMG, robust ceiling p{settings['qualification']['ceiling_percentile']:.0%}.")
    quality_row = f"<table><tr><th>VKX</th><td>1.4</td><th>Logging rate</th><td>{quality.get('logging_rate_hz') or 'unknown'} Hz</td><th>Samples</th><td>{len(result['telemetry']):,}</td><th>Timezone</th><td>{escape(result['timezone'])}</td></tr><tr><th>Warnings</th><td colspan=\"7\">{escape(', '.join(quality.get('warnings', [])) or 'none')}</td></tr></table>"
    return f"""<!doctype html><html lang=\"{language}\"><head><meta charset=\"utf-8\"><title>{escape(labels['title'])}</title><style>
@page {{ size: A4; margin: 14mm; }} html, body {{ background:#ffffff !important; color:#172033; }} body {{ font-family: Arial, sans-serif; max-width: 1050px; margin:auto; }} h1 {{ font-size: 27px; margin-bottom: 4px; }} h2 {{ border-bottom:2px solid #0f766e; padding-bottom:4px; margin-top:30px; }} h3 {{ margin-top:6px; }} .subtitle {{ color:#52616b; }} .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:20px; }} table {{ border-collapse:collapse; width:100%; }} th,td {{ padding:6px 8px; border-bottom:1px solid #dce3e8; text-align:left; }} th {{ background:#edf4f3; }} .data-table {{ font-size:12px; }} .note, .definition-card {{ background:#f3f6f8; padding:12px; border-left:4px solid #0f766e; }} .definition-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }} .definition-card:nth-child(2) {{ border-left-color:#ea580c; }} .muted {{ color:#52616b; font-size:12px; }} .timeline {{ display:flex; min-height:46px; margin:14px 0; }} .timeline span {{ display:flex; align-items:center; justify-content:center; text-align:center; padding:8px; font-size:12px; }} .timeline .sail {{ background:#dcfce7; flex:1; }} .timeline .pre {{ background:#fee2e2; flex:.55; }} .timeline .maneuver {{ background:#ffedd5; flex:.8; font-weight:bold; }} .quality-row {{ margin-top:16px; }} .quality-row h3 {{ margin-bottom:5px; }} @media print {{ * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }} .plotly-graph-div, .definition-card {{ break-inside: avoid; }} h2 {{ break-after: avoid; }} }} </style></head><body>
<h1>{escape(labels['title'])}</h1><p class=\"subtitle\">{escape(metadata.get('athlete',''))} · {escape(metadata.get('sailing_class',''))}</p>
<section><h2>{escape(labels['session'])}</h2><div class=\"grid\"><div><table>{metadata_left_html}</table></div><div><table>{metadata_right_html}</table></div></div><div class=\"quality-row\"><h3>{escape(labels['data_quality'])}</h3>{quality_row}</div></section>
<h2>{escape(labels['definition'])}</h2><p class=\"note\">{escape(definition)}</p>{definition_html(result, labels, language)}
<h2>{escape(labels['track'])}</h2>{_fig_html(session, include_js=True)}
<h2>{escape(labels['statistics'])}</h2>{stats_html}<p class=\"muted\">Box plots are separated by maneuver group and direction so comparable S->P/P->S or L->P/P->L distributions can be inspected independently.</p>{_fig_html(distributions)}
<h2>{escape(labels['appendix'])}</h2><p class=\"note\">Entry SOG Ratio is entry speed divided by the robust high-performance SOG ceiling for the block. Entry VMG Ratio is entry VMG divided by the corresponding robust VMG ceiling. A ratio of 80% means the maneuver began at 80% of that block's reference performance.</p>{appendix_html}
</body></html>"""
