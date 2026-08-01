from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from src.research_mvp.config import REFERENCE_PROFILE, MvpInferenceConfig, validate_inference_boundary
from src.research_mvp.failures import MvpFailure
from src.research_mvp.artifacts.resolver import resolve_relative
from src.research_mvp.launcher import run_outer_attempt
from src.research_mvp.memory.snapshot import MvpMemoryWriter
from src.research_mvp.runtime.video_runner import run_synthetic_inference


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "research_mvp" / "fixtures" / "three_video_input.json"


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        junction = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "& { param($linkPath, $targetPath) New-Item -ItemType Junction -Path $linkPath -Target $targetPath | Out-Null }",
                str(link),
                str(target),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if junction.returncode != 0:
            pytest.skip("symlink and junction creation are unavailable for this account")


def test_reference_profile_is_isolated_and_attempt_bound() -> None:
    config = MvpInferenceConfig.reference(attempt_id="mvp-synth-a")

    assert config.runtime_profile == REFERENCE_PROFILE
    assert config.memory_namespace_id == config.attempt_id
    assert config.output_root.parts[-3:-1] == ("agentic_outputs", "mvp")
    assert config.memory_root.parts[-3:-1] == ("agentic_memory", "mvp")
    assert "legacy" not in str(config).casefold()
    assert "tfavad" not in str(config).casefold()
    assert config.resume is False


@pytest.mark.parametrize(
    "poison",
    [
        {"label": 1},
        {"nested": {"annotation_path": "secret.json"}},
        {"target": ["metric_target"]},
        {"ground_truth": False},
    ],
)
def test_ground_truth_poison_fails_before_root_creation(tmp_path: Path, poison: object) -> None:
    planned_root = tmp_path / "must-not-exist"

    with pytest.raises(MvpFailure, match="MVP_GROUND_TRUTH_POISON"):
        validate_inference_boundary({"attempt_id": "safe", "root": planned_root, "extra": poison})

    assert not planned_root.exists()


def test_outer_launcher_rejects_environment_poison_before_process_or_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_calls: list[object] = []

    def forbidden_process(*args: object, **kwargs: object) -> object:
        process_calls.append((args, kwargs))
        raise AssertionError("inference process must not start")

    monkeypatch.setenv("MVP_PRIVATE_INPUT", "annotation-capability.json")
    monkeypatch.setattr(subprocess, "Popen", forbidden_process)

    with pytest.raises(MvpFailure, match="MVP_GROUND_TRUTH_POISON"):
        run_outer_attempt(
            attempt_id="mvp-env-poison-a",
            project_root=tmp_path,
            fixture_path=FIXTURE,
            memory_enabled=True,
        )

    assert process_calls == []
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("relative", ["/absolute", "C:/drive", "../escape", "a/../../escape", "\\\\server\\share"])
def test_path_guard_rejects_absolute_parent_and_alias(tmp_path: Path, relative: str) -> None:
    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        resolve_relative(tmp_path, relative)


def test_path_guard_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    _create_directory_link(link, outside)

    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        resolve_relative(tmp_path, "link/file.json")


def test_path_guard_rejects_reparse_ancestor_of_authorized_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-ancestor-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "linked-root"
    _create_directory_link(link, outside)

    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        resolve_relative(link / "attempt", "facts.json")

    assert not (outside / "attempt" / "facts.json").exists()


def test_memory_genesis_rejects_reparse_ancestor(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-memory-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "linked-memory"
    _create_directory_link(link, outside)

    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        MvpMemoryWriter.create_fresh(link / "mvp-memory-link-a", "mvp-memory-link-a")

    assert not (outside / "mvp-memory-link-a").exists()


def test_reference_attempt_rejects_casefold_alias_before_other_root_creation(tmp_path: Path) -> None:
    aliased_parent = tmp_path / "data" / "agentic_outputs" / "MVP"
    aliased_parent.mkdir(parents=True)

    with pytest.raises(MvpFailure, match="MVP_PATH_ESCAPE"):
        run_synthetic_inference(
            attempt_id="mvp-casefold-a",
            project_root=tmp_path,
            fixture_path=FIXTURE,
            memory_enabled=True,
        )

    assert not (tmp_path / "data" / "agentic_memory").exists()


def test_fixture_and_golden_are_fixed_and_bounded() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "three_video_input.json"
    golden_path = Path(__file__).parent / "golden" / "expected_retrieval.json"
    fixture = json.loads(fixture_path.read_bytes())
    golden = json.loads(golden_path.read_bytes())

    assert [video["video_id"] for video in fixture["videos"]] == [
        "mvp-video-a-reference",
        "mvp-video-b-salient",
        "mvp-video-c-query",
    ]
    assert fixture["static_max_case_count"] == 3
    assert fixture["static_max_case_count"] <= 512
    assert golden["view_order"] == ["DENSE", "SPARSE_BM25", "TEMPORAL"]
    assert golden["views"]["DENSE"][0] == "mvp-case-b-salient-0000"
    assert golden["views"]["SPARSE_BM25"][0] == "mvp-case-b-salient-0000"
    assert golden["views"]["TEMPORAL"][0] == "mvp-case-b-salient-0000"
    assert golden["rrf_order"][0] == "mvp-case-b-salient-0000"


def test_research_mvp_has_no_forbidden_imports_or_artifact_v1_names() -> None:
    forbidden_prefixes = (
        "src.agents",
        "src.pipelines",
        "src.memory",
        "src.eval",
    )
    source_root = ROOT / "src" / "research_mvp"
    assert source_root.is_dir()

    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        assert "ContractAuditV1" not in text
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for name in imported:
                allowed_narrow_backend = (
                    path.parent.name == "adapters"
                    and name == "src.memory.embedding_builder"
                )
                assert allowed_narrow_backend or not name.startswith(forbidden_prefixes)
