from __future__ import annotations

from pathlib import Path


def test_agentic_vad_app_refreshes_home_state(monkeypatch, tmp_path: Path):
    from src.app.tui_app import AgenticVADApp

    states = [
        {
            "snapshot": type("Snapshot", (), {"checks": [type("Check", (), {"name": "python", "level": "ok", "message": "python=3.13.5"})()]})(),
            "workspace": {"datasets": [], "models": [], "required_actions": ["first"], "recent_result": None},
        },
        {
            "snapshot": type("Snapshot", (), {"checks": [type("Check", (), {"name": "python", "level": "ok", "message": "python=3.13.6"})()]})(),
            "workspace": {"datasets": [], "models": [], "required_actions": ["second"], "recent_result": None},
        },
    ]

    def _collect_home_state(*, repo_root: Path, preferred_dataset: str):
        return states.pop(0)

    monkeypatch.setattr("src.app.tui_app.collect_home_state", _collect_home_state)

    app = AgenticVADApp(repo_root=tmp_path, preferred_dataset="ucf_crime")
    assert "python=3.13.5" in app.sections["project_status"]

    app.refresh_home_state()

    assert "python=3.13.6" in app.sections["project_status"]
