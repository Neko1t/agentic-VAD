#!/usr/bin/env bash
set -euo pipefail

# UCF-Crime template launcher for the agentic VAD workflow.
#
# Linux:
#   chmod +x scripts/run_agentic_workflow_ucf_crime.sh
#   ./scripts/run_agentic_workflow_ucf_crime.sh
#
# Override any variable inline if your paths differ:
#   GPU_DEVICE=0 \
#   DATASET_DIR=/data/ucf_crime \
#   CAPTIONS_DIR=/data/ucf_crime/captions/video_llama3_json_results \
#   BASELINE_SCORES_DIR=/data/ucf_crime/refined_scores/videollama3 \
#   ./scripts/run_agentic_workflow_ucf_crime.sh --stage pipeline --no-use-chroma

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${SCRIPT_DIR}"

export DATASET_DIR="${DATASET_DIR:-${REPO_ROOT}/data/ucf_crime}"

export ROOT_PATH="${ROOT_PATH:-${DATASET_DIR}/frames}"
export ANNOTATION_FILE_PATH="${ANNOTATION_FILE_PATH:-${DATASET_DIR}/annotations/test.txt}"
export CAPTIONS_DIR="${CAPTIONS_DIR:-${DATASET_DIR}/captions/video_llama3_json_results}"
export TEMPORAL_ANNOTATION_FILE="${TEMPORAL_ANNOTATION_FILE:-${DATASET_DIR}/annotations/temporal_test.txt}"

export OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/data/agentic_outputs/ucf_crime}"
export MEMORY_DIR="${MEMORY_DIR:-${REPO_ROOT}/data/agentic_memory/ucf_crime}"

# Original/baseline scores from the author pipeline for comparison.
export BASELINE_SCORES_DIR="${BASELINE_SCORES_DIR:-${DATASET_DIR}/refined_scores/videollama3}"

# Recommended defaults for the current prototype.
export FRAME_INTERVAL="${FRAME_INTERVAL:-16}"
export ROLLING_WINDOW_SIZE="${ROLLING_WINDOW_SIZE:-4}"
export TOP_K="${TOP_K:-5}"
export RUN_MODE="${RUN_MODE:-online_inference}"
export NORMAL_LABEL="${NORMAL_LABEL:-0}"
export VIDEO_FPS="${VIDEO_FPS:-30.0}"
export USE_AUDIO="${USE_AUDIO:-false}"
export USE_OCR="${USE_OCR:-false}"
export USE_CHROMA="${USE_CHROMA:-true}"
export EXPORT_EVAL_SCORES="${EXPORT_EVAL_SCORES:-true}"

# Default full workflow with baseline comparison.
export STAGES="${STAGES:-pipeline,promote,patterns,metrics,baseline-metrics,compare}"

exec bash "${SCRIPT_DIR}/run_agentic_workflow.sh" "$@"
