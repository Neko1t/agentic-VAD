# Agentic VAD Linux Run Guide

This document explains how to run the current agentic VAD workflow on a Linux
machine using the executable shell scripts stored in `scripts/`.

## 1. Available Entry Scripts

Script entrypoints:

- `scripts/run_agentic_workflow.sh`
  - Generic workflow launcher.
  - Use this when you want full control over dataset paths.
- `scripts/run_agentic_workflow_ucf_crime.sh`
  - UCF-Crime path template.
  - Uses README-style default paths under `data/ucf_crime/`.
- `scripts/run_agentic_workflow_xd_violence.sh`
  - XD-Violence path template.
  - Uses README-style default paths under `data/xd_violence/`.

All three scripts eventually call:

- `scripts/run_agentic_workflow.py`

The main orchestration logic lives in:

- `src/pipelines/run_agentic_workflow.py`

## 2. Prerequisites

Minimum requirements:

- Linux with `bash`
- Python `3.10+` recommended
- Project dependencies installed

Typical setup:

```bash
conda env create -f environment.yml
conda activate VAA
```

or:

```bash
pip install -r requirements.txt
```

## 3. Make Scripts Executable

Run once:

```bash
chmod +x scripts/run_agentic_workflow.sh
chmod +x scripts/run_agentic_workflow_ucf_crime.sh
chmod +x scripts/run_agentic_workflow_xd_violence.sh
```

## 4. Expected Dataset Structure

The scripts assume the repository follows the README-style dataset layout:

```text
data/
  ucf_crime/
    annotations/
      test.txt
      temporal_test.txt
    frames/
    captions/
      video_llama3_json_results/
    refined_scores/
      videollama3/

  xd_violence/
    annotations/
      test.txt
      temporal_test.txt
    frames/
    captions/
      video_llama3_json_results/
    refined_scores/
      videollama3/
```

Notes:

- `captions/.../*.json` are the precomputed caption files consumed by the
  current `VLMTool`.
- `refined_scores/videollama3` is the original-author baseline score directory
  used for comparison, if available.
- `temporal_test.txt` is required if you want `metrics` or `compare`.

## 5. Fastest Way To Run

### UCF-Crime

```bash
./scripts/run_agentic_workflow_ucf_crime.sh
```

### XD-Violence

```bash
./scripts/run_agentic_workflow_xd_violence.sh
```

These template scripts default to the full stage chain:

```text
pipeline -> promote -> patterns -> metrics -> baseline-metrics -> compare
```

## 6. Generic Launcher Example

Use the generic script when your paths do not match the template:

```bash
ROOT_PATH=/data/ucf_crime/frames \
ANNOTATION_FILE_PATH=/data/ucf_crime/annotations/test.txt \
CAPTIONS_DIR=/data/ucf_crime/captions/video_llama3_json_results \
TEMPORAL_ANNOTATION_FILE=/data/ucf_crime/annotations/temporal_test.txt \
OUTPUT_DIR=/data/agentic_outputs/ucf_crime \
MEMORY_DIR=/data/agentic_memory/ucf_crime \
BASELINE_SCORES_DIR=/data/ucf_crime/refined_scores/videollama3 \
./scripts/run_agentic_workflow.sh
```

## 7. Stage-Based Debugging

You can run only part of the workflow.

Examples:

### Pipeline only

```bash
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline
```

### Pipeline + metrics

```bash
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --stage metrics
```

### Metrics + baseline comparison only

```bash
./scripts/run_agentic_workflow_ucf_crime.sh \
  --stage metrics \
  --stage baseline-metrics \
  --stage compare
```

### Disable Chroma for lightweight debugging

```bash
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --no-use-chroma
```

## 8. Useful Environment Variables

The shell scripts support overriding these variables:

### Required path variables

- `ROOT_PATH`
- `ANNOTATION_FILE_PATH`
- `CAPTIONS_DIR`
- `TEMPORAL_ANNOTATION_FILE`

### Optional path variables

- `OUTPUT_DIR`
- `MEMORY_DIR`
- `BASELINE_SCORES_DIR`
- `BASELINE_METRICS_DIR`

### Runtime variables

- `FRAME_INTERVAL`
- `ROLLING_WINDOW_SIZE`
- `TOP_K`
- `RUN_MODE`
- `NORMAL_LABEL`
- `VIDEO_FPS`
- `PATTERN_MIN_SUPPORT`
- `PROMOTE_HIGH_RISK_THRESHOLD`
- `PROMOTE_HARD_NEGATIVE_THRESHOLD`
- `PROMOTE_MAX_UNCERTAINTY`
- `PROMOTE_MIN_EVIDENCE_TAGS`

### Boolean variables

Use `true` or `false`:

- `USE_AUDIO`
- `USE_OCR`
- `USE_CHROMA`
- `EXPORT_EVAL_SCORES`
- `PROMOTE_DRY_RUN`

### Stage selection

Use comma-separated values:

```bash
STAGES="pipeline,metrics,baseline-metrics,compare"
```

## 9. Output Artifacts

The workflow writes artifacts under `OUTPUT_DIR`.

Main outputs:

```text
OUTPUT_DIR/
  reports/
  observations/
  episodes/
  story_results/
  scores/
  metrics/
  baseline_metrics/
  promotion_report.json
  comparison_report.json
  workflow_summary.json
```

Meaning:

- `reports/`: final per-video anomaly report
- `observations/`: `ObservationCard` outputs
- `episodes/`: `EpisodeSummary` outputs
- `story_results/`: full `StoryMemoryResult`
- `scores/`: temporal score JSONs aligned to the original evaluator
- `metrics/`: current agentic ROC AUC / PR AUC outputs
- `baseline_metrics/`: baseline ROC AUC / PR AUC outputs
- `comparison_report.json`: side-by-side metric comparison
- `workflow_summary.json`: workflow-level summary

## 10. Common Problems

### Problem: placeholder path error

Cause:

- You used `scripts/run_agentic_workflow.sh` without replacing the default placeholder
  paths.

Fix:

- Export the required path variables explicitly, or use one of the dataset
  template scripts.

### Problem: `python3` not found

Cause:

- Python is not available in `PATH`.

Fix:

- Activate the correct environment first.
- Or override:

```bash
PYTHON_BIN=python ./scripts/run_agentic_workflow_ucf_crime.sh
```

### Problem: `temporal_annotation_file is required`

Cause:

- You requested `metrics`, `baseline-metrics`, or `compare` without providing a
  temporal annotation file.

Fix:

- Set `TEMPORAL_ANNOTATION_FILE`.

### Problem: no baseline comparison

Cause:

- `BASELINE_SCORES_DIR` or `BASELINE_METRICS_DIR` was not provided.

Fix:

- Set one of them if you want `compare` to be meaningful.

### Problem: Chroma or embedding dependencies fail

Cause:

- Local environment mismatch, missing optional dependency, or debugging on a
  lightweight machine.

Fix:

```bash
./scripts/run_agentic_workflow_ucf_crime.sh --no-use-chroma
```

## 11. Recommended First Run

For a first validation on Linux, use:

```bash
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --stage metrics --no-use-chroma
```

Reason:

- It verifies the core agentic path.
- It exports eval-compatible scores.
- It avoids extra Chroma variability during initial debugging.

## 12. Current Constraint

The current VLM path is still based on precomputed captions. The workflow does
not yet run a real GPU VLM backend directly. For now, make sure the caption
JSON files already exist under the configured `CAPTIONS_DIR`.
