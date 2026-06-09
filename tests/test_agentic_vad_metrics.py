from pathlib import Path

from src.eval import agentic_vad_metrics


class _DummyOriginalEvalModule:
    def __init__(self):
        self.called_with = None

    def main(self, **kwargs):
        self.called_with = kwargs


def test_agentic_vad_metrics_delegates_to_original_eval(monkeypatch, tmp_path: Path):
    dummy = _DummyOriginalEvalModule()
    monkeypatch.setattr(agentic_vad_metrics, "_load_original_eval_module", lambda: dummy)

    root_path = tmp_path / "frames"
    annotation_file = tmp_path / "test.txt"
    temporal_annotation_file = tmp_path / "temporal.txt"
    scores_dir = tmp_path / "scores"
    captions_dir = tmp_path / "captions"
    output_dir = tmp_path / "metrics"
    root_path.mkdir()
    scores_dir.mkdir()
    captions_dir.mkdir()
    annotation_file.write_text("video_1.mp4 0 31 1\n", encoding="utf-8")
    temporal_annotation_file.write_text("video_1.mp4 0 0 31\n", encoding="utf-8")

    agentic_vad_metrics.main(
        root_path=root_path,
        annotation_file_path=annotation_file,
        temporal_annotation_file=temporal_annotation_file,
        scores_dir=scores_dir,
        captions_dir=captions_dir,
        output_dir=output_dir,
        frame_interval=16,
        normal_label=0,
        video_fps=30.0,
    )

    assert dummy.called_with is not None
    assert dummy.called_with["scores_dir"] == str(scores_dir)
    assert dummy.called_with["output_dir"] == str(output_dir)
    assert dummy.called_with["frame_interval"] == 16
    assert dummy.called_with["without_labels"] is False
