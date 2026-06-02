from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(add_completion=False, help="Summarize agentic VAD reports.")


@app.command()
def main(
    reports_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_csv: Path = typer.Option(Path("./data/agentic_outputs/agentic_eval_summary.csv")),
) -> None:
    rows = []
    for report_file in sorted(reports_dir.glob("*.json")):
        with report_file.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        rows.append(
            {
                "video_id": report["video_id"],
                "video_level_score": report["video_level_score"],
                "num_abnormal_segments": len(report.get("abnormal_segments", [])),
                "num_retrieved_cases": len(report.get("retrieved_cases", [])),
                "num_patterns": len(report.get("matched_patterns", [])),
            }
        )
    frame = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_csv, index=False)
    typer.echo(f"Saved summary to {output_csv}")


if __name__ == "__main__":
    app()
