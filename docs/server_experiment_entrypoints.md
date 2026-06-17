# Server Experiment Entrypoints

This document provides copy-ready server command templates for the current
Agentic VAD experiment flow.

## Scope

- All experiment runs must explicitly select a GPU device.
- `REPL`, `CLI`, and legacy `Textual/TUI` entrypoints now follow the same rule.
- `--no-use-vlm` reuses existing caption JSON files.
- `--use-vlm` requires original videos and a local VideoLLaMA3 model path.

## Common Environment

Run these commands from the repository root.

```bash
conda activate vaa-pip
cd ~/agentic-VAD
```

Optional tmux session for long-running jobs:

```bash
tmux new -s agentic-vad
```

Detach with `Ctrl+B` then `D`, and later reattach with:

```bash
tmux attach -t agentic-vad
```

## 1. REPL Entry

Default entry:

```bash
python agentic_vad.py
```

Recommended REPL sequence for mini smoke test without VLM:

```text
set gpu 0
set vlm off
doctor
run mini
results
compare
exit
```

Recommended REPL sequence for mini smoke test with VLM:

```text
set gpu 0
set vlm on
doctor
run mini
results
compare
exit
```

Notes:

- `set gpu <id>` is required before `run mini` or `run full`.
- `set vlm off` uses precomputed captions under the configured `captions_dir`.
- `set vlm on` uses the default dataset `videos/` directory and
  `libs/videollama3/VideoLLaMA3-7B`.

## 2. CLI Entry

### Mini without VLM

```bash
python agentic_vad.py run mini \
  --root-path ./data/ucf_crime_mini/frames \
  --annotation-file-path ./data/ucf_crime_mini/annotations/test.txt \
  --captions-dir ./data/ucf_crime_mini/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime_mini/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime_mini \
  --memory-dir ./data/agentic_memory/ucf_crime_mini \
  --gpu-device 0 \
  --no-use-vlm
```

### Mini with VLM

```bash
python agentic_vad.py run mini \
  --root-path ./data/ucf_crime_mini/frames \
  --annotation-file-path ./data/ucf_crime_mini/annotations/test.txt \
  --captions-dir ./data/ucf_crime_mini/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime_mini/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime_mini \
  --memory-dir ./data/agentic_memory/ucf_crime_mini \
  --gpu-device 0 \
  --use-vlm \
  --video-root-path ./data/ucf_crime_mini/videos \
  --vlm-model-path ./libs/videollama3/VideoLLaMA3-7B
```

### Full without VLM

```bash
python agentic_vad.py run full \
  --root-path ./data/ucf_crime/frames \
  --annotation-file-path ./data/ucf_crime/annotations/test.txt \
  --captions-dir ./data/ucf_crime/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime \
  --memory-dir ./data/agentic_memory/ucf_crime \
  --gpu-device 0 \
  --no-use-vlm
```

### Full with VLM

```bash
python agentic_vad.py run full \
  --root-path ./data/ucf_crime/frames \
  --annotation-file-path ./data/ucf_crime/annotations/test.txt \
  --captions-dir ./data/ucf_crime/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime \
  --memory-dir ./data/agentic_memory/ucf_crime \
  --gpu-device 0 \
  --use-vlm \
  --video-root-path ./data/ucf_crime/videos \
  --vlm-model-path ./libs/videollama3/VideoLLaMA3-7B
```

### Stage-only smoke test

Pipeline only, mini dataset, no VLM:

```bash
python agentic_vad.py run stage pipeline \
  --root-path ./data/ucf_crime_mini/frames \
  --annotation-file-path ./data/ucf_crime_mini/annotations/test.txt \
  --captions-dir ./data/ucf_crime_mini/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime_mini/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime_mini \
  --memory-dir ./data/agentic_memory/ucf_crime_mini \
  --gpu-device 0 \
  --no-use-vlm
```

## 3. Script Wrapper Entry

### Generic workflow wrapper, mini without VLM

```bash
GPU_DEVICE=0 \
ROOT_PATH=./data/ucf_crime_mini/frames \
ANNOTATION_FILE_PATH=./data/ucf_crime_mini/annotations/test.txt \
CAPTIONS_DIR=./data/ucf_crime_mini/captions/video_llama3_json_results \
TEMPORAL_ANNOTATION_FILE=./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
BASELINE_SCORES_DIR=./data/ucf_crime_mini/refined_scores/videollama3 \
OUTPUT_DIR=./data/agentic_outputs/ucf_crime_mini \
MEMORY_DIR=./data/agentic_memory/ucf_crime_mini \
bash scripts/run_agentic_workflow.sh --no-use-vlm
```

### Generic workflow wrapper, mini with VLM

```bash
GPU_DEVICE=0 \
ROOT_PATH=./data/ucf_crime_mini/frames \
ANNOTATION_FILE_PATH=./data/ucf_crime_mini/annotations/test.txt \
CAPTIONS_DIR=./data/ucf_crime_mini/captions/video_llama3_json_results \
TEMPORAL_ANNOTATION_FILE=./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
BASELINE_SCORES_DIR=./data/ucf_crime_mini/refined_scores/videollama3 \
OUTPUT_DIR=./data/agentic_outputs/ucf_crime_mini \
MEMORY_DIR=./data/agentic_memory/ucf_crime_mini \
bash scripts/run_agentic_workflow.sh \
  --use-vlm \
  --video-root-path ./data/ucf_crime_mini/videos \
  --vlm-model-path ./libs/videollama3/VideoLLaMA3-7B
```

### Preset wrapper, full UCF-Crime without VLM

```bash
GPU_DEVICE=0 bash scripts/run_agentic_workflow_ucf_crime.sh --no-use-vlm
```

### Preset wrapper, full UCF-Crime with VLM

```bash
GPU_DEVICE=0 bash scripts/run_agentic_workflow_ucf_crime.sh \
  --use-vlm \
  --video-root-path ./data/ucf_crime/videos \
  --vlm-model-path ./libs/videollama3/VideoLLaMA3-7B
```

## 4. Legacy Textual / TUI Entry

This path is now legacy and is no longer the default launcher, but it still
works if `textual` is installed and `GPU_DEVICE` is set explicitly.

```bash
GPU_DEVICE=0 python -c "from pathlib import Path; from src.app.tui_app import launch_home; launch_home(repo_root=Path('.').resolve(), preferred_dataset='ucf_crime', force_textual=True)"
```

Notes:

- This path reads `GPU_DEVICE` from the environment.
- It is mainly kept for compatibility and debugging.
- For experiment control, prefer the REPL or direct CLI commands.

## 5. Quick Checks

Check current command surface:

```bash
python agentic_vad.py run mini --help
python agentic_vad.py run full --help
python agentic_vad.py run stage pipeline --help
```

Check dataset and output readiness:

```bash
python agentic_vad.py doctor \
  --root-path ./data/ucf_crime_mini/frames \
  --annotation-file-path ./data/ucf_crime_mini/annotations/test.txt \
  --captions-dir ./data/ucf_crime_mini/captions/video_llama3_json_results \
  --temporal-annotation-file ./data/ucf_crime_mini/annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt \
  --baseline-scores-dir ./data/ucf_crime_mini/refined_scores/videollama3 \
  --output-dir ./data/agentic_outputs/ucf_crime_mini
```

## 6. Recommended Defaults

- Mini smoke test first:
  - `--gpu-device 0`
  - `--no-use-vlm`
  - `run stage pipeline` or `run mini`
- Full comparison run after smoke test:
  - `--gpu-device 0`
  - `--no-use-vlm` first
  - then `--use-vlm` after confirming video path and model path
- If you leave the terminal during runs:
  - use `tmux`
  - or use the shell wrappers with explicit `GPU_DEVICE`
