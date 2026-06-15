from __future__ import annotations

from pathlib import Path


def test_collect_home_state_includes_snapshot_and_workspace(tmp_path: Path):
    from src.app.tui_app import collect_home_state

    data_root = tmp_path / "data" / "ucf_crime"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )

    state = collect_home_state(repo_root=tmp_path, preferred_dataset="ucf_crime")

    assert "snapshot" in state
    assert "workspace" in state
    assert state["workspace"]["preferred_dataset"] == "ucf_crime"


def test_launch_home_uses_textual_when_available_by_default(monkeypatch, tmp_path: Path):
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

    result = tui_app.launch_home(repo_root=tmp_path, preferred_dataset="ucf_crime")

    assert result is None
    assert created["app"].called is True


def test_launch_home_can_force_text_fallback_even_when_textual_is_available(monkeypatch, tmp_path: Path):
    from src.app import tui_app

    data_root = tmp_path / "data" / "ucf_crime"
    (data_root / "frames").mkdir(parents=True)
    (data_root / "annotations").mkdir(parents=True)
    (data_root / "captions" / "video_llama3_json_results").mkdir(parents=True)
    (data_root / "annotations" / "test.txt").write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    (data_root / "annotations" / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").write_text(
        "video_1.mp4 0 0 31\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(tui_app, "TEXTUAL_AVAILABLE", True)

    rendered = tui_app.launch_home(repo_root=tmp_path, preferred_dataset="ucf_crime", force_text=True)

    assert rendered is not None
    assert "Project Status" in rendered
