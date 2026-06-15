# Scripts Guide

This document lists the executable scripts in the repository and how to use
them quickly.

## Conventions

- Run scripts from the repository root unless noted otherwise.
- Dataset paths below follow the project layout in `data/`.
- `agentic-vad` workflow scripts expect captions to already exist unless you
  replace the VLM backend.

## 1. Asset Download

### `download_agentic_assets.sh`

Purpose:

- Wrapper for the asset downloader.

Typical usage:

```bash
chmod +x download_agentic_assets.sh
./download_agentic_assets.sh --list --preset bootstrap
./download_agentic_assets.sh --preset models-core
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

## 2. Agentic Workflow

### `run_agentic_workflow.sh`

Purpose:

- Generic launcher for the full agentic VAD workflow.

Typical usage:

```bash
chmod +x run_agentic_workflow.sh
ROOT_PATH=/data/ucf_crime/frames \
ANNOTATION_FILE_PATH=/data/ucf_crime/annotations/test.txt \
CAPTIONS_DIR=/data/ucf_crime/captions/video_llama3_json_results \
TEMPORAL_ANNOTATION_FILE=/data/ucf_crime/annotations/temporal_test.txt \
BASELINE_SCORES_DIR=/data/ucf_crime/refined_scores/videollama3 \
./run_agentic_workflow.sh
```

Useful flags:

```bash
./run_agentic_workflow.sh --stage pipeline --no-use-chroma
./run_agentic_workflow.sh --stage pipeline --stage metrics
```

Main implementation:

- `scripts/run_agentic_workflow.py`
- `src/pipelines/run_agentic_workflow.py`

### `run_agentic_workflow_ucf_crime.sh`

Purpose:

- UCF-Crime preset launcher.

Typical usage:

```bash
chmod +x run_agentic_workflow_ucf_crime.sh
./run_agentic_workflow_ucf_crime.sh
./run_agentic_workflow_ucf_crime.sh --stage pipeline --no-use-chroma
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
chmod +x run_agentic_workflow_xd_violence.sh
./run_agentic_workflow_xd_violence.sh
./run_agentic_workflow_xd_violence.sh --stage pipeline --no-use-chroma
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

## 3. Original / Baseline Evaluation

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

## 4. Frame Extraction

### `scripts/extract_frames.sh`

Purpose:

- Example shell wrapper for frame extraction across datasets.

Typical usage:

```bash
bash scripts/extract_frames.sh
```

Notes:

- Edit dataset paths inside the file before running.

## 5. Python Utilities Used Directly

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

## 6. Maintenance Rule

Whenever a new script or executable entrypoint is added, update this file in
the same change so the usage guide stays complete.
