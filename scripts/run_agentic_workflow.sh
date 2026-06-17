#!/usr/bin/env bash
set -euo pipefail

# End-to-end launcher for the agentic VAD workflow.
#
# Usage:
#   1) Edit the variables below, then run:
#        bash scripts/run_agentic_workflow.sh
#      or on Linux:
#        chmod +x scripts/run_agentic_workflow.sh
#        ./scripts/run_agentic_workflow.sh
#
#   2) Or override by environment variables:
#        ROOT_PATH=/data/ucf_crime/frames \
#        ANNOTATION_FILE_PATH=/data/ucf_crime/annotations/test.txt \
#        CAPTIONS_DIR=/data/ucf_crime/captions/video_llama3_json_results \
#        TEMPORAL_ANNOTATION_FILE=/data/ucf_crime/annotations/temporal_test.txt \
#        BASELINE_SCORES_DIR=/data/ucf_crime/refined_scores/videollama3 \
#        bash scripts/run_agentic_workflow.sh
#
#   3) Or append extra Typer options:
#        bash scripts/run_agentic_workflow.sh --stage pipeline --no-use-chroma

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${SCRIPT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[ERROR] python3/python not found in PATH." >&2
    exit 1
  fi
fi

# ----------------------------
# Required paths
# ----------------------------
ROOT_PATH="${ROOT_PATH:-/path/to/dataset/frames}"
ANNOTATION_FILE_PATH="${ANNOTATION_FILE_PATH:-/path/to/dataset/annotations/test.txt}"
CAPTIONS_DIR="${CAPTIONS_DIR:-/path/to/dataset/captions/video_llama3_json_results}"
TEMPORAL_ANNOTATION_FILE="${TEMPORAL_ANNOTATION_FILE:-/path/to/dataset/annotations/temporal_test.txt}"

# ----------------------------
# Optional paths
# ----------------------------
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/data/agentic_outputs}"
MEMORY_DIR="${MEMORY_DIR:-${REPO_ROOT}/data/agentic_memory}"
BASELINE_SCORES_DIR="${BASELINE_SCORES_DIR:-}"
BASELINE_METRICS_DIR="${BASELINE_METRICS_DIR:-}"

# ----------------------------
# Runtime options
# ----------------------------
GPU_DEVICE="${GPU_DEVICE:-}"
FRAME_INTERVAL="${FRAME_INTERVAL:-16}"
ROLLING_WINDOW_SIZE="${ROLLING_WINDOW_SIZE:-4}"
TOP_K="${TOP_K:-5}"
RUN_MODE="${RUN_MODE:-online_inference}"
NORMAL_LABEL="${NORMAL_LABEL:-0}"
VIDEO_FPS="${VIDEO_FPS:-30.0}"
PATTERN_MIN_SUPPORT="${PATTERN_MIN_SUPPORT:-2}"
PROMOTE_HIGH_RISK_THRESHOLD="${PROMOTE_HIGH_RISK_THRESHOLD:-8.0}"
PROMOTE_HARD_NEGATIVE_THRESHOLD="${PROMOTE_HARD_NEGATIVE_THRESHOLD:-2.5}"
PROMOTE_MAX_UNCERTAINTY="${PROMOTE_MAX_UNCERTAINTY:-0.35}"
PROMOTE_MIN_EVIDENCE_TAGS="${PROMOTE_MIN_EVIDENCE_TAGS:-1}"

# Boolean flags: true / false
USE_AUDIO="${USE_AUDIO:-false}"
USE_OCR="${USE_OCR:-false}"
USE_CHROMA="${USE_CHROMA:-true}"
EXPORT_EVAL_SCORES="${EXPORT_EVAL_SCORES:-true}"
PROMOTE_DRY_RUN="${PROMOTE_DRY_RUN:-false}"

# Comma-separated stages, for example:
#   STAGES="pipeline,metrics,baseline-metrics,compare"
# Leave empty to use the workflow default stages.
STAGES="${STAGES:-}"

if [[ "${ROOT_PATH}" == "/path/to/dataset/frames" ]] || \
   [[ "${ANNOTATION_FILE_PATH}" == "/path/to/dataset/annotations/test.txt" ]] || \
   [[ "${CAPTIONS_DIR}" == "/path/to/dataset/captions/video_llama3_json_results" ]] || \
   [[ "${TEMPORAL_ANNOTATION_FILE}" == "/path/to/dataset/annotations/temporal_test.txt" ]]; then
  cat >&2 <<'EOF'
[ERROR] Required paths are still placeholders.
Set these variables before running:
  ROOT_PATH
  ANNOTATION_FILE_PATH
  CAPTIONS_DIR
  TEMPORAL_ANNOTATION_FILE
EOF
  exit 1
fi

if [[ -z "${GPU_DEVICE}" ]]; then
  cat >&2 <<'EOF'
[ERROR] GPU_DEVICE is required.
Set it explicitly before running, for example:
  GPU_DEVICE=0 bash scripts/run_agentic_workflow.sh
EOF
  exit 1
fi

ARGS=(
  --root-path "${ROOT_PATH}"
  --annotation-file-path "${ANNOTATION_FILE_PATH}"
  --captions-dir "${CAPTIONS_DIR}"
  --output-dir "${OUTPUT_DIR}"
  --memory-dir "${MEMORY_DIR}"
  --gpu-device "${GPU_DEVICE}"
  --temporal-annotation-file "${TEMPORAL_ANNOTATION_FILE}"
  --frame-interval "${FRAME_INTERVAL}"
  --rolling-window-size "${ROLLING_WINDOW_SIZE}"
  --top-k "${TOP_K}"
  --run-mode "${RUN_MODE}"
  --normal-label "${NORMAL_LABEL}"
  --video-fps "${VIDEO_FPS}"
  --pattern-min-support "${PATTERN_MIN_SUPPORT}"
  --promote-high-risk-threshold "${PROMOTE_HIGH_RISK_THRESHOLD}"
  --promote-hard-negative-threshold "${PROMOTE_HARD_NEGATIVE_THRESHOLD}"
  --promote-max-uncertainty "${PROMOTE_MAX_UNCERTAINTY}"
  --promote-min-evidence-tags "${PROMOTE_MIN_EVIDENCE_TAGS}"
)

if [[ -n "${BASELINE_SCORES_DIR}" ]]; then
  ARGS+=(--baseline-scores-dir "${BASELINE_SCORES_DIR}")
fi

if [[ -n "${BASELINE_METRICS_DIR}" ]]; then
  ARGS+=(--baseline-metrics-dir "${BASELINE_METRICS_DIR}")
fi

if [[ "${USE_AUDIO}" == "true" ]]; then
  ARGS+=(--use-audio)
else
  ARGS+=(--no-use-audio)
fi

if [[ "${USE_OCR}" == "true" ]]; then
  ARGS+=(--use-ocr)
else
  ARGS+=(--no-use-ocr)
fi

if [[ "${USE_CHROMA}" == "true" ]]; then
  ARGS+=(--use-chroma)
else
  ARGS+=(--no-use-chroma)
fi

if [[ "${EXPORT_EVAL_SCORES}" == "true" ]]; then
  ARGS+=(--export-eval-scores)
else
  ARGS+=(--no-export-eval-scores)
fi

if [[ "${PROMOTE_DRY_RUN}" == "true" ]]; then
  ARGS+=(--promote-dry-run)
else
  ARGS+=(--no-promote-dry-run)
fi

if [[ -n "${STAGES}" ]]; then
  IFS=',' read -r -a STAGE_ARRAY <<< "${STAGES}"
  for stage in "${STAGE_ARRAY[@]}"; do
    stage="$(echo "${stage}" | xargs)"
    [[ -n "${stage}" ]] && ARGS+=(--stage "${stage}")
  done
fi

echo "[INFO] Python: ${PYTHON_BIN}"
echo "[INFO] Repo: ${REPO_ROOT}"
echo "[INFO] Output dir: ${OUTPUT_DIR}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/run_agentic_workflow.py" "${ARGS[@]}" "$@"
