# Scripts Guide

This document lists the executable scripts in the repository and how to use
them quickly.

## Conventions

- Run scripts from the repository root unless noted otherwise.
- Dataset paths below follow the project layout in `data/`.
- `agentic-vad` workflow scripts expect captions to already exist unless you
  replace the VLM backend.

## 1. Unified Entry

### `agentic_vad.py`

Purpose:

- Unified project entrypoint for the ongoing REPL-console consolidation work.
- Gives the repository one top-level command surface while reusing the current
  workflow implementation under `src/pipelines/`.

Typical usage:

```bash
python agentic_vad.py
python agentic_vad.py doctor --help
python agentic_vad.py run mini --help
python agentic_vad.py run full --help
python agentic_vad.py run stage pipeline --help
python agentic_vad.py results show
```

Current commands:

- `doctor`: inspect whether key inputs and dependencies are in place
- `run mini`: run the unified mini-experiment path
- `run full`: run the unified full-experiment path
- `run stage`: run selected workflow stages only
- `assets download`: call the asset downloader
- `dataset build-mini`: call the mini subset builder
- `results show`: read persisted result summaries

Notes:

- This is the new recommended root-level entrypoint.
- Running `python agentic_vad.py` now launches a persistent REPL-style terminal
  console instead of the older Textual-first home screen.
- The REPL auto-runs a startup workspace overview and then accepts short
  commands such as:

```text
help
doctor
status
download models-core
build mini
run mini
run full
results
compare
exit
```

- The REPL currently handles:
  - startup readiness overview
  - `doctor`
  - `status`
  - `results`
  - `compare`
  - `run mini`
  - `run full`
  - recommendation-only `download ...` and `build mini` helper commands
- Direct Typer subcommands remain available for automation, debugging, and
  non-interactive server usage.

## 2. Asset Download

### `download_agentic_assets.sh`

Purpose:

- Wrapper for the asset downloader.

Typical usage:

```bash
chmod +x scripts/download_agentic_assets.sh
./scripts/download_agentic_assets.sh --list --preset bootstrap
./scripts/download_agentic_assets.sh --preset models-core
```

Main implementation:

- `scripts/download_agentic_assets.py`

Notes:

- Uses ModelScope first for models when possible.
- Falls back to `hf-mirror.com` only when requested.
- Can prepare manual directories for dataset/caption assets.

### `scripts/download_agentic_assets.py`

Purpose:

- Download or stage models and data assets with a clear progress table.

Examples:

```bash
python scripts/download_agentic_assets.py --preset models-core
python scripts/download_agentic_assets.py --preset bootstrap
python scripts/download_agentic_assets.py --preset all --skip-manual
```

Key presets:

- `models-core`: `BAAI/bge-base-en-v1.5`
- `models-all`: embedding + VideoLLaMA3 + Llama 3.1 8B
- `bootstrap`: annotation bundle + UCF-Crime placeholders + embedding model

## 3. Agentic Workflow

### `build_ucf_crime_mini_subset.sh`

Purpose:

- Build a compact UCF-Crime subset for pre-experiments.
- Copies selected annotations, captions, baseline scores, optional videos, and
  optional extracted frames into `data/ucf_crime_mini/`.

Typical usage:

```bash
chmod +x scripts/build_ucf_crime_mini_subset.sh
./scripts/build_ucf_crime_mini_subset.sh
```

Custom video list:

```bash
./scripts/build_ucf_crime_mini_subset.sh \
  --video Abuse028_x264 \
  --video Abuse030_x264 \
  --video Arrest001_x264 \
  --video Arson009_x264 \
  --video Arson010_x264
```

Main implementation:

- `scripts/build_ucf_crime_mini_subset.py`

Notes:

- Uses progress bars for subset copy and frame extraction.
- Automatically skips files and extracted frames that already exist unless
  `--force` is provided.

### `run_agentic_workflow.sh`

Purpose:

- Generic launcher for the full agentic VAD workflow.

Typical usage:

```bash
chmod +x scripts/run_agentic_workflow.sh
ROOT_PATH=/data/ucf_crime/frames \
ANNOTATION_FILE_PATH=/data/ucf_crime/annotations/test.txt \
CAPTIONS_DIR=/data/ucf_crime/captions/video_llama3_json_results \
TEMPORAL_ANNOTATION_FILE=/data/ucf_crime/annotations/temporal_test.txt \
BASELINE_SCORES_DIR=/data/ucf_crime/refined_scores/videollama3 \
./scripts/run_agentic_workflow.sh
```

Useful flags:

```bash
./scripts/run_agentic_workflow.sh --stage pipeline --no-use-chroma
./scripts/run_agentic_workflow.sh --stage pipeline --stage metrics
```

Main implementation:

- `scripts/run_agentic_workflow.py`
- `src/pipelines/run_agentic_workflow.py`

### `run_agentic_workflow_ucf_crime.sh`

Purpose:

- UCF-Crime preset launcher.

Typical usage:

```bash
chmod +x scripts/run_agentic_workflow_ucf_crime.sh
./scripts/run_agentic_workflow_ucf_crime.sh
./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --no-use-chroma
```

Defaults:

- `data/ucf_crime/frames`
- `data/ucf_crime/annotations/test.txt`
- `data/ucf_crime/captions/video_llama3_json_results`
- `data/ucf_crime/refined_scores/videollama3`

### `run_agentic_workflow_xd_violence.sh`

Purpose:

- XD-Violence preset launcher.

Typical usage:

```bash
chmod +x scripts/run_agentic_workflow_xd_violence.sh
./scripts/run_agentic_workflow_xd_violence.sh
./scripts/run_agentic_workflow_xd_violence.sh --stage pipeline --no-use-chroma
```

Defaults:

- `data/xd_violence/frames`
- `data/xd_violence/annotations/test.txt`
- `data/xd_violence/captions/video_llama3_json_results`
- `data/xd_violence/refined_scores/videollama3`

### `scripts/run_agentic_workflow.py`

Purpose:

- Python entrypoint for the agentic workflow CLI.

Typical usage:

```bash
python scripts/run_agentic_workflow.py --help
```

## 4. Original / Baseline Evaluation

### `scripts/query_llm_vad.sh`

Purpose:

- Original first-round score generation using Llama 3.1 8B.

Typical usage:

```bash
bash scripts/query_llm_vad.sh
```

Inputs:

- `data/ucf_crime/captions/video_llama3_json_results`
- `data/ucf_crime/annotations/test.txt`

Outputs:

- `data/ucf_crime/scores/videollama3`

### `scripts/refine_score.sh`

Purpose:

- Original score refinement stage.

Typical usage:

```bash
bash scripts/refine_score.sh
```

Inputs:

- `data/ucf_crime/scores/videollama3`
- `data/ucf_crime/captions/<experiment_name>`

Outputs:

- `data/ucf_crime/refined_scores/videollama3`

### `scripts/eval_ucf.sh`

Purpose:

- Evaluate UCF-Crime scores with the original metric pipeline.

Typical usage:

```bash
bash scripts/eval_ucf.sh
```

### `scripts/eval_xd.sh`

Purpose:

- Evaluate XD-Violence scores with the original metric pipeline.

Typical usage:

```bash
bash scripts/eval_xd.sh
```

### `scripts/eval_ub.sh`

Purpose:

- Evaluate UBNormal-style data with the original metric pipeline.

### `scripts/eval_msad.sh`

Purpose:

- Evaluate MSAD-style data with the original metric pipeline.

## 5. Frame Extraction

### `scripts/extract_frames.sh`

Purpose:

- Example shell wrapper for frame extraction across datasets.

Typical usage:

```bash
bash scripts/extract_frames.sh
```

Notes:

- Edit dataset paths inside the file before running.

## 6. Python Utilities Used Directly

These are script-like entrypoints but are usually called through the workflow.

- `src/video_pre_caption.py`
- `src/summarize_window.py`
- `src/score_filter.py`
- `src/refine_with_tag.py`
- `src/val_priors.py`
- `src/vau_priors.py`
- `src/draw_bboxes.py`
- `src/extract_frames.py`
- `src/compute_bleu.py`
- `src/gpt_score_eval.py`
- `src/eval.py`
- `src/eval/agentic_vad_metrics.py`
- `src/pipelines/run_agentic_vad.py`
- `src/pipelines/promote_case_memory.py`
- `src/pipelines/extract_patterns_offline.py`

## 7. Maintenance Rule

Whenever a new script or executable entrypoint is added, update this file in
the same change so the usage guide stays complete.
