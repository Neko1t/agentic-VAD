from __future__ import annotations

from src.runtime.progress import ProgressEvent


def test_workflow_monitor_tracks_latest_event_and_stage_progress():
    from src.app.run_monitor import WorkflowMonitor

    monitor = WorkflowMonitor()
    monitor.consume(ProgressEvent(stage="workflow", event="stage_start", message="starting", completed=0, total=4))
    monitor.consume(
        ProgressEvent(
            stage="pipeline",
            event="window_end",
            message="processed",
            completed=2,
            total=5,
            video_id="video_1",
            window_id="video_1_0002",
            tool_name="vlm_describe",
        )
    )

    snapshot = monitor.snapshot()

    assert snapshot["latest"]["stage"] == "pipeline"
    assert snapshot["stages"]["pipeline"]["completed"] == 2
    assert snapshot["stages"]["pipeline"]["total"] == 5
    assert snapshot["stages"]["pipeline"]["tool_name"] == "vlm_describe"


def test_queue_progress_reporter_forwards_events_to_monitor():
    from src.app.run_monitor import QueueProgressReporter, WorkflowMonitor

    monitor = WorkflowMonitor()
    reporter = QueueProgressReporter(monitor)
    reporter.emit(ProgressEvent(stage="metrics", event="stage_end", message="roc=0.9", completed=1, total=1))

    snapshot = monitor.snapshot()

    assert snapshot["latest"]["stage"] == "metrics"
    assert snapshot["stages"]["metrics"]["message"] == "roc=0.9"
