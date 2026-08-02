from __future__ import annotations

import argparse
import json
from pathlib import Path

from maneuver_app.core import aggregate_statistics, analyze_session, serializable_result
from maneuver_app.report import build_report_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Vakaros tacks and gybes.")
    parser.add_argument("--vkx", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--preset", default="presets/olympic_formula_kite.json")
    parser.add_argument("--output", default="output/analysis")
    parser.add_argument("--timezone")
    parser.add_argument("--language", choices=["pl", "en"], default="pl")
    parser.add_argument("--athlete", default="")
    parser.add_argument("--sailing-class", default="")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = analyze_session(args.vkx, Path(args.annotations).read_text(encoding="utf-8"), args.preset, args.timezone)
    result["telemetry"].to_csv(output / "telemetry_normalized.csv", index=False)
    result["maneuvers"].to_csv(output / "maneuvers.csv", index=False)
    aggregate_statistics(result["maneuvers"]).to_csv(output / "statistics.csv", index=False)
    (output / "analysis.json").write_text(json.dumps(serializable_result(result), indent=2, ensure_ascii=False), encoding="utf-8")
    report = build_report_html(result, {"athlete": args.athlete, "sailing_class": args.sailing_class}, args.language)
    (output / "report.html").write_text(report, encoding="utf-8")
    print(f"Created {output.resolve()}")


if __name__ == "__main__":
    main()
