from __future__ import annotations

from pathlib import Path

from src.app.models import CheckStatus, ProjectStatusSnapshot


def test_build_home_sections_creates_named_text_blocks():
    from src.app.tui_app import build_home_sections

    snapshot = ProjectStatusSnapshot(
        ready=False,
        checks=[
            CheckStatus(name="python", ready=True, level="ok", message="python=3.13.5"),
            CheckStatus(name="frames_root", ready=False, level="error", message="missing directory"),
        ],
        root_path=Path("./data/ucf_crime/frames"),
        annotation_file_path=Path("./data/ucf_crime/annotations/test.txt"),
        captions_dir=Path("./data/ucf_crime/captions/video_llama3_json_results"),
    )
    workspace = {
        "datasets": [{"name": "ucf_crime", "ready": False, "path": "./data/ucf_crime"}],
        "models": [{"name": "embedding", "ready": True, "path": "./libs/embeddings/bge-base-en-v1.5"}],
        "required_actions": ["download at least one required model asset"],
        "recent_result": {"status": "ok", "summary": "latest comparison", "path": "./data/agentic_outputs/latest"},
        "live_progress": {
            "latest": {"stage": "pipeline", "message": "processed", "tool_name": "vlm_describe"},
            "stages": {"pipeline": {"completed": 2, "total": 5}},
        },
    }

    sections = build_home_sections(snapshot=snapshot, workspace=workspace)

    assert set(sections.keys()) == {
        "overview",
        "project_status",
        "dataset_readiness",
        "model_assets",
        "recent_results",
        "live_progress",
        "required_actions",
        "suggested_commands",
    }
    assert "python=3.13.5" in sections["project_status"]
    assert "ucf_crime" in sections["dataset_readiness"]
    assert "latest comparison" in sections["recent_results"]
    assert "pipeline" in sections["live_progress"]
