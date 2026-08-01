# Original-Evaluation-Compatible Temporal Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare five-video and later full-dataset Research MVP runs on an exact 16-frame prediction grid with independent offline/causal evidence context and original-compatible frame-level ROC AUC / PR AUC.

**Architecture:** A pure temporal planner owns rational frame/time conversion and produces closed V1 source manifests. Real backends consume evidence intervals, while the runtime freezes decision intervals into prediction records. The isolated evaluator validates the grid, projects predictions to original frames, applies the registered Gaussian/direct-B4 policy, and evaluates frame targets without exposing annotations to inference.

**Tech Stack:** Python 3.10+, dataclasses, `pathlib`, `fractions.Fraction`, FFmpeg/ffprobe subprocesses, NumPy, SciPy, scikit-learn, pytest.

---

### Task 1: Freeze the domain and implementation contract

**Files:**
- Modify: `CONTEXT.md`
- Create: `docs/adr/0002-separate-decision-grid-from-evidence-context.md`
- Create: `docs/superpowers/plans/2026-08-01-original-evaluation-compatible-temporal-protocol.md`

- [ ] **Step 1: Record canonical temporal terms**

Define Decision Interval, Evidence Context, Prediction Grid, Frame Prediction, and Temporal Protocol without implementation details.

- [ ] **Step 2: Record the architectural decision**

Record why a 16-frame decision cadence is independent from approximately 10-second centered/trailing evidence.

- [ ] **Step 3: Check documentation scope**

Run: `git diff -- CONTEXT.md docs/adr/0002-separate-decision-grid-from-evidence-context.md docs/superpowers/plans/2026-08-01-original-evaluation-compatible-temporal-protocol.md`

Expected: only the glossary, ADR, and this plan are present.

### Task 2: Implement the pure temporal planner

**Files:**
- Create: `src/research_mvp/media.py`
- Create: `tests/research_mvp/test_temporal_media_protocol.py`

- [ ] **Step 1: Write failing planner tests**

```python
def test_plan_uses_exact_rational_frame_boundaries():
    plan = plan_video_windows(
        video_id="mvp-video-arson010",
        frame_count=33,
        fps_num=30,
        fps_den=1,
        temporal_protocol="ZS_INDEPENDENT_OFFLINE",
    )
    assert [(w.start_frame, w.end_frame) for w in plan] == [(0, 15), (16, 31), (32, 32)]
    assert [w.delta_us for w in plan] == [533333, 533334, 33333]
```

Add independent centered-context, causal trailing-context, short-video clipping, and all-five-video 580-window assertions.

- [ ] **Step 2: Verify RED**

Run: `E:\\Anaconda3\\python.exe -m pytest tests/research_mvp/test_temporal_media_protocol.py -q --basetemp=.pytest_tmp_protocol_red`

Expected: FAIL because `src.research_mvp.media` does not exist.

- [ ] **Step 3: Implement rational planning**

```python
def frame_boundary_us(frame_index: int, fps_num: int, fps_den: int) -> int:
    numerator = frame_index * fps_den * 1_000_000
    return (numerator + fps_num // 2) // fps_num

def plan_video_windows(..., decision_stride_frames: int = 16, evidence_context_frames: int = 300):
    # Produce contiguous half-open decision frame ranges and protocol-specific evidence ranges.
```

Use inclusive stored end-frame fields, half-open microsecond intervals, centered offline context, and no-future causal context.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 targeted pytest command with a fresh `--basetemp`; expect all tests to pass.

### Task 3: Build hash-bound V1 media assets and source manifests

**Files:**
- Modify: `src/research_mvp/media.py`
- Modify: `src/research_mvp/cli.py`
- Modify: `tests/research_mvp/test_temporal_media_protocol.py`

- [ ] **Step 1: Write failing preparation tests**

```python
def test_prepare_media_publishes_manifest_last_and_reuses_verified_cache(tmp_path):
    receipt = prepare_media_assets(..., command_runner=fake_ffmpeg)
    assert receipt.source_manifest_path.name == "mvp_real_asset_source_v1.json"
    assert prepare_media_assets(..., command_runner=forbid_calls).cache_hit is True
```

Cover ffprobe stream selection `0:v:0` / `0:a:0`, mono 16 kHz PCM WAV commands, sampled evidence frames, source/config/output hashes, stale-cache rebuild, and publication-last behavior.

- [ ] **Step 2: Verify RED**

Run the media test file; expect missing preparation API failures.

- [ ] **Step 3: Implement preparation and CLI**

Add `prepare-real-media` with explicit video root, output root, dataset ID, protocol, ffmpeg/ffprobe executables, and an ignored `.asset_status/` cache. Do not put labels in the source manifest.

- [ ] **Step 4: Verify GREEN**

Run the media test file; expect all preparation tests to pass without requiring local FFmpeg.

### Task 4: Carry V1 decision/evidence metadata through precomputation and inference

**Files:**
- Modify: `src/research_mvp/adapters/real_assets.py`
- Modify: `src/research_mvp/runtime/window_runner.py`
- Modify: `src/research_mvp/runtime/video_runner.py`
- Modify: `src/research_mvp/config.py`
- Modify: `tests/research_mvp/test_real_asset_pipeline.py`

- [ ] **Step 1: Write failing V1 integration tests**

```python
def test_v1_precompute_binds_evidence_context_but_prediction_binds_decision_interval(...):
    prepared, _, _ = load_precomputed_input(input_manifest)
    window = prepared["videos"][0]["windows"][0]
    assert window["evidence_start_frame"] == 0
    assert window["start_frame"] == 0
    assert window["end_frame"] == 15
```

Also assert predictions freeze `start_frame`, `end_frame`, `frame_count`, and exact ordinal, and that more than 512 decision points are accepted while Memory capacity remains 512.

- [ ] **Step 2: Verify RED**

Run the named real-asset tests; expect closed-schema or missing-field failures.

- [ ] **Step 3: Implement V1 adapter/runtime support**

Accept V0 only for existing synthetic/compatibility tests and V1 for real preparation. Pass Evidence Context to caption/OCR/audio adapters, pass Decision Interval and `delta_us` to B4, and include decision metadata in frozen prediction records. Remove the input-window-count check against `memory_capacity`; retain the 512 bound only for stored Memory cases.

- [ ] **Step 4: Verify GREEN**

Run `tests/research_mvp/test_real_asset_pipeline.py`, `test_temporal_media_protocol.py`, and existing causality tests with a fresh base temp.

### Task 5: Add frame targets and original-compatible evaluation

**Files:**
- Modify: `src/research_mvp/evaluator/metrics.py`
- Modify: `src/research_mvp/evaluator/cli.py`
- Modify: `src/research_mvp/launcher.py`
- Create: `tests/research_mvp/test_frame_level_evaluator.py`
- Modify: `tests/research_mvp/test_evaluator_isolation.py`

- [ ] **Step 1: Write failing projection and policy tests**

```python
def test_project_direct_b4_scores_to_every_original_frame():
    projected = project_video_predictions(predictions, frame_count=33, frame_interval=16, gaussian_sigma=None)
    assert projected == (0.1,) * 16 + (0.2,) * 16 + (0.3,)

def test_original_style_policy_applies_sigma_ten_before_repeat():
    projected = project_video_predictions(predictions, frame_count=33, frame_interval=16, gaussian_sigma=10.0)
    assert projected == pytest.approx(tuple(np.repeat(gaussian_filter1d([0.1, 0.2, 0.3], 10), 16)[:33]))
```

Also test inclusive anomaly intervals, exact grid validation, missing/extra prediction rejection, O0/O1/I0/I1/I2 Gaussian registration, I3/I4/C0/C1/S0 direct-B4 registration, and V0 target compatibility.

- [ ] **Step 2: Verify RED**

Run the frame evaluator tests; expect missing projection/registry failures.

- [ ] **Step 3: Implement frame-level evaluator**

Add a closed `MVP_FRAME_TARGETS_V1` parser with `frame_interval=16`, `normal_label=0`, per-video frame counts, inclusive anomaly intervals, and registered protocol postprocessing. Sort predictions by `(video_id bytes, window_ordinal)`, validate exact intervals, project to frames, flatten videos, and call `evaluate_binary_metrics`.

- [ ] **Step 4: Preserve V0 synthetic evaluation**

Keep the existing `{records:[{video_id,window_id,target}]}` path for synthetic smoke runs; reject mixed schemas.

- [ ] **Step 5: Verify GREEN**

Run evaluator isolation, frame evaluator, real-asset pipeline, and end-to-end tests with a fresh base temp.

### Task 6: Validate, commit, push, and sync AutoDL

**Files:**
- Verify all files listed above

- [ ] **Step 1: Run focused suite**

Run: `E:\\Anaconda3\\python.exe -m pytest tests/research_mvp -q --basetemp=.pytest_tmp_protocol_full`

Expected: all Research MVP tests pass.

- [ ] **Step 2: Run repository suite**

Run: `E:\\Anaconda3\\python.exe -m pytest -q --basetemp=.pytest_tmp_protocol_repo`

Expected: exit code 0, or report pre-existing failures with exact evidence before committing.

- [ ] **Step 3: Review and stage only scoped changes**

Run `git diff --check`, inspect `git diff`, then explicitly `git add` only the protocol files. Verify with `git diff --cached --name-status` that unrelated deletions/moves are absent.

- [ ] **Step 4: Commit and push**

Run:

```powershell
git commit -m "feat: align mvp temporal evaluation with original protocol"
git push origin codex/autodl-migration
```

- [ ] **Step 5: Sync and verify AutoDL**

Use the supplied SSH endpoint to fetch and fast-forward `/root/autodl-tmp/agentic-VAD`, then verify remote HEAD equals the pushed commit. Run the focused server-side tests in `/root/miniconda3/envs/VAA` before starting media preparation.
