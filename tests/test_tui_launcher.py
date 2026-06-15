from __future__ import annotations

from pathlib import Path


def test_build_recent_result_rows_extracts_metric_deltas():
    from src.app.dashboard import build_recent_result_rows

    rows = build_recent_result_rows(
        {
            "status": "ok",
            "summary": "latest comparison",
            "path": "data/agentic_outputs/run_01",
            "comparison": {
                "diff": {
                    "roc_auc": {"delta": 0.1234},
                    "pr_auc": {"delta": -0.0567},
                }
            },
        }
    )

    assert ("status", "ok") in rows
    assert ("roc_auc_delta", "0.1234") in rows
    assert ("pr_auc_delta", "-0.0567") in rows


def test_launch_home_returns_text_dashboard_when_textual_is_unavailable(tmp_path: Path, monkeypatch):
    from src.app import tui_app

    repo_root = tmp_path
    data_root = repo_root / "data" / "ucf_crime"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(tui_app, "TEXTUAL_AVAILABLE", False)

    rendered = tui_app.launch_home(repo_root=repo_root, preferred_dataset="ucf_crime", force_text=True)

    assert rendered is not None
    assert "Agentic VAD" in rendered
    assert "Project Status" in rendered


def test_launch_home_prefers_textual_when_enabled(monkeypatch, tmp_path: Path):
    from src.app import tui_app

    class _FakeApp:
        def __init__(self, repo_root: Path, preferred_dataset: str):
            self.repo_root = repo_root
            self.preferred_dataset = preferred_dataset
            self.called = False

        def run(self) -> None:
            self.called = True

    created: dict[str, object] = {}

    def _factory(repo_root: Path, preferred_dataset: str):
        app = _FakeApp(repo_root, preferred_dataset)
        created["app"] = app
        return app

    monkeypatch.setattr(tui_app, "TEXTUAL_AVAILABLE", True)
    monkeypatch.setattr(tui_app, "create_textual_app", _factory)

    result = tui_app.launch_home(repo_root=tmp_path, preferred_dataset="ucf_crime", force_textual=True)

    assert result is None
    assert created["app"].called is True
